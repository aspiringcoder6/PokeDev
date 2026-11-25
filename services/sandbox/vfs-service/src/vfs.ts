import crypto from "crypto";
import {
  getWorkspaceDatabase,
  deleteWorkspaceDatabase,
  listWorkspaces,
  workspaceExists,
  FileRecord,
  RevisionRecord,
} from "./db";
import { applyTextEdits, TextEdit, AppliedTextEdits } from "./text-edit";
import { normalizeVfsPath, shouldIgnoreVfsPath, isScratchPath } from "./ignore-rules";

export interface WriteFileOptions {
  isBinary?: boolean;
  encoding?: "utf-8" | "base64";
}

export interface ReadFileResult {
  path: string;
  content: string;
  size: number;
  sha256: string;
  mtime: string;
  isBinary: boolean;
  encoding: "utf-8" | "base64";
}

export interface ListEntry {
  path: string;
  size: number;
  sha256: string;
  mtime: string;
  isBinary: boolean;
}

export interface ManifestEntry {
  path: string;
  size: number;
  sha256: string;
  mtime: string;
}

export function computeSha256(buffer: Buffer): string {
  return crypto.createHash("sha256").update(buffer).digest("hex");
}

export class VfsService {
  /**
   * Write file to the dedicated SQLite database for this workspace.
   */
  writeFile(
    workspaceId: string,
    rawPath: string,
    content: string | Buffer,
    options: WriteFileOptions = {}
  ): { path: string; size: number; sha256: string; mtime: string } {
    const filePath = normalizeVfsPath(rawPath);
    if (isScratchPath(filePath)) {
      throw new Error(
        `Cannot save scratch/temporary file '${filePath}' to VFS. Scratch files must live only in ephemeral sandbox RAM.`
      );
    }

    let buffer: Buffer;
    let isBinary = Boolean(options.isBinary);

    if (Buffer.isBuffer(content)) {
      buffer = content;
    } else if (options.encoding === "base64") {
      buffer = Buffer.from(content, "base64");
      isBinary = true;
    } else {
      buffer = Buffer.from(content, "utf-8");
    }

    const sha256 = computeSha256(buffer);
    const mtime = new Date().toISOString();
    const size = buffer.length;

    const db = getWorkspaceDatabase(workspaceId);
    const stmt = db.prepare(`
      INSERT INTO files (path, content, size, sha256, mtime, is_binary)
      VALUES (?, ?, ?, ?, ?, ?)
      ON CONFLICT(path) DO UPDATE SET
        content = excluded.content,
        size = excluded.size,
        sha256 = excluded.sha256,
        mtime = excluded.mtime,
        is_binary = excluded.is_binary
    `);

    stmt.run(filePath, buffer, size, sha256, mtime, isBinary ? 1 : 0);

    return { path: filePath, size, sha256, mtime };
  }

  /**
   * Read file from the dedicated workspace SQLite database.
   */
  readFile(workspaceId: string, rawPath: string): ReadFileResult {
    const filePath = normalizeVfsPath(rawPath);
    const db = getWorkspaceDatabase(workspaceId);
    const stmt = db.prepare(`
      SELECT path, content, size, sha256, mtime, is_binary
      FROM files
      WHERE path = ?
    `);

    const row = stmt.get(filePath) as FileRecord | undefined;
    if (!row) {
      throw new Error(`File not found: ${filePath}`);
    }

    const isBinary = Boolean(row.is_binary);
    const encoding = isBinary ? "base64" : "utf-8";
    const contentStr = isBinary
      ? row.content.toString("base64")
      : row.content.toString("utf-8");

    return {
      path: row.path,
      content: contentStr,
      size: row.size,
      sha256: row.sha256,
      mtime: row.mtime,
      isBinary,
      encoding,
    };
  }

  /**
   * Apply fuzzy text edits, update workspace SQLite, and save revision.
   */
  editFile(
    workspaceId: string,
    rawPath: string,
    edits: TextEdit[]
  ): AppliedTextEdits & { path: string; size: number; beforeSha: string; afterSha: string } {
    const filePath = normalizeVfsPath(rawPath);
    const existing = this.readFile(workspaceId, filePath);

    if (existing.isBinary) {
      throw new Error(`Cannot apply text edit to binary file: ${filePath}`);
    }

    const beforeSha = existing.sha256;
    const applied = applyTextEdits(existing.content, edits, filePath);

    const newBuffer = Buffer.from(applied.after, "utf-8");
    const afterSha = computeSha256(newBuffer);
    const mtime = new Date().toISOString();
    const size = newBuffer.length;

    const db = getWorkspaceDatabase(workspaceId);
    const updateFileStmt = db.prepare(`
      UPDATE files
      SET content = ?, size = ?, sha256 = ?, mtime = ?
      WHERE path = ?
    `);

    const insertRevisionStmt = db.prepare(`
      INSERT INTO file_revisions (path, patch, before_sha, after_sha, created_at)
      VALUES (?, ?, ?, ?, ?)
    `);

    const txn = db.transaction(() => {
      updateFileStmt.run(newBuffer, size, afterSha, mtime, filePath);
      insertRevisionStmt.run(filePath, applied.patch, beforeSha, afterSha, mtime);

      // Keep only last 20 revisions for this path
      db.prepare(`
        DELETE FROM file_revisions
        WHERE path = ? AND id NOT IN (
          SELECT id FROM file_revisions
          WHERE path = ?
          ORDER BY id DESC LIMIT 20
        )
      `).run(filePath, filePath);
    });

    txn();

    return {
      ...applied,
      path: filePath,
      size,
      beforeSha,
      afterSha,
    };
  }

  /**
   * Delete a file or directory.
   */
  deleteFile(workspaceId: string, rawPath: string, recursive = false): { deletedCount: number } {
    const filePath = normalizeVfsPath(rawPath);
    const db = getWorkspaceDatabase(workspaceId);

    if (recursive) {
      const prefix = filePath.endsWith("/") ? filePath : filePath + "/";
      const stmt = db.prepare(`
        DELETE FROM files
        WHERE path = ? OR path LIKE ? || '%'
      `);
      const result = stmt.run(filePath, prefix);
      return { deletedCount: result.changes };
    } else {
      const stmt = db.prepare(`
        DELETE FROM files
        WHERE path = ?
      `);
      const result = stmt.run(filePath);
      return { deletedCount: result.changes };
    }
  }

  /**
   * List files in the workspace database.
   */
  listFiles(
    workspaceId: string,
    options: { prefix?: string; includeIgnored?: boolean } = {}
  ): ListEntry[] {
    // Read-only: never auto-create a workspace sqlite on a listing request
    if (!workspaceExists(workspaceId)) return [];
    const prefix = options.prefix ? normalizeVfsPath(options.prefix) : "/";
    const db = getWorkspaceDatabase(workspaceId);
    let rows: Array<{ path: string; size: number; sha256: string; mtime: string; is_binary: number }>;

    if (prefix === "/") {
      const stmt = db.prepare(`
        SELECT path, size, sha256, mtime, is_binary
        FROM files
        ORDER BY path ASC
      `);
      rows = stmt.all() as typeof rows;
    } else {
      const stmt = db.prepare(`
        SELECT path, size, sha256, mtime, is_binary
        FROM files
        WHERE path = ? OR path LIKE ? || '%'
        ORDER BY path ASC
      `);
      rows = stmt.all(prefix, prefix.endsWith("/") ? prefix : prefix + "/") as typeof rows;
    }

    return rows
      .filter((row) => options.includeIgnored || !shouldIgnoreVfsPath(row.path))
      .map((row) => ({
        path: row.path,
        size: row.size,
        sha256: row.sha256,
        mtime: row.mtime,
        isBinary: Boolean(row.is_binary),
      }));
  }

  /**
   * Get full manifest for delta synchronization.
   */
  getManifest(workspaceId: string): ManifestEntry[] {
    const db = getWorkspaceDatabase(workspaceId);
    const stmt = db.prepare(`
      SELECT path, size, sha256, mtime
      FROM files
      ORDER BY path ASC
    `);

    const rows = stmt.all() as Array<{ path: string; size: number; sha256: string; mtime: string }>;
    return rows
      .filter((row) => !shouldIgnoreVfsPath(row.path))
      .map((row) => ({
        path: row.path,
        size: row.size,
        sha256: row.sha256,
        mtime: row.mtime,
      }));
  }

  /**
   * Get revision history for a file.
   */
  getRevisions(workspaceId: string, rawPath: string): RevisionRecord[] {
    const filePath = normalizeVfsPath(rawPath);
    const db = getWorkspaceDatabase(workspaceId);
    const stmt = db.prepare(`
      SELECT id, path, patch, before_sha, after_sha, created_at
      FROM file_revisions
      WHERE path = ?
      ORDER BY id DESC
    `);
    return stmt.all(filePath) as RevisionRecord[];
  }

  /**
   * Delete entire workspace database file.
   */
  deleteWorkspace(workspaceId: string): boolean {
    return deleteWorkspaceDatabase(workspaceId);
  }

  /**
   * List all workspace IDs currently in storage.
   */
  listAllWorkspaces(): string[] {
    return listWorkspaces();
  }
}
