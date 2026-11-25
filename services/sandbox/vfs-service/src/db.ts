import Database from "better-sqlite3";
import path from "path";
import fs from "fs";

export interface FileRecord {
  path: string;
  content: Buffer;
  size: number;
  sha256: string;
  mtime: string;
  is_binary: number;
}

export interface RevisionRecord {
  id: number;
  path: string;
  patch: string;
  before_sha: string;
  after_sha: string;
  created_at: string;
}

export interface GitMetaRecord {
  id: number;
  head_commit: string | null;
  branch: string;
  remote_url: string | null;
}

const connections = new Map<string, Database.Database>();

export function getWorkspacesDir(): string {
  const base = process.env.VFS_DATA_DIR || path.join(process.cwd(), "data", "workspaces");
  if (!fs.existsSync(base)) {
    fs.mkdirSync(base, { recursive: true });
  }
  return base;
}

export function sanitizeWorkspaceId(workspaceId: string): string {
  return workspaceId.replace(/[^a-zA-Z0-9_\-\.]/g, "_");
}

export function getWorkspaceDbPath(workspaceId: string): string {
  const cleanId = sanitizeWorkspaceId(workspaceId);
  return path.join(getWorkspacesDir(), `${cleanId}.sqlite`);
}

/** True when the workspace sqlite file already exists on disk (never creates one). */
export function workspaceExists(workspaceId: string): boolean {
  return fs.existsSync(getWorkspaceDbPath(workspaceId));
}

export function getWorkspaceDatabase(workspaceId: string): Database.Database {
  const cleanId = sanitizeWorkspaceId(workspaceId);
  let db = connections.get(cleanId);
  if (db && db.open) return db;

  const dbPath = getWorkspaceDbPath(cleanId);
  db = new Database(dbPath);
  db.pragma("journal_mode = WAL");
  db.pragma("synchronous = NORMAL");
  db.pragma("foreign_keys = ON");

  // Exact camelAI DO SQLite isolated schema
  db.exec(`
    CREATE TABLE IF NOT EXISTS files (
      path TEXT PRIMARY KEY,
      content BLOB NOT NULL,
      size INTEGER NOT NULL,
      sha256 TEXT NOT NULL,
      mtime TEXT NOT NULL,
      is_binary INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS file_revisions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      path TEXT NOT NULL,
      patch TEXT NOT NULL,
      before_sha TEXT NOT NULL,
      after_sha TEXT NOT NULL,
      created_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_revisions_path ON file_revisions(path);

    CREATE TABLE IF NOT EXISTS git_meta (
      id INTEGER PRIMARY KEY DEFAULT 1,
      head_commit TEXT,
      branch TEXT NOT NULL DEFAULT 'main',
      remote_url TEXT
    );
  `);

  connections.set(cleanId, db);
  return db;
}

export function closeWorkspaceDatabase(workspaceId: string): void {
  const cleanId = sanitizeWorkspaceId(workspaceId);
  const db = connections.get(cleanId);
  if (db) {
    try {
      db.close();
    } catch {}
    connections.delete(cleanId);
  }
}

export function deleteWorkspaceDatabase(workspaceId: string): boolean {
  closeWorkspaceDatabase(workspaceId);
  const dbPath = getWorkspaceDbPath(workspaceId);
  let deleted = false;
  if (fs.existsSync(dbPath)) {
    fs.unlinkSync(dbPath);
    deleted = true;
  }
  const wal = dbPath + "-wal";
  const shm = dbPath + "-shm";
  if (fs.existsSync(wal)) {
    try { fs.unlinkSync(wal); } catch {}
  }
  if (fs.existsSync(shm)) {
    try { fs.unlinkSync(shm); } catch {}
  }
  return deleted;
}

export function listWorkspaces(): string[] {
  const dir = getWorkspacesDir();
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(".sqlite"))
    .map((f) => f.replace(/\.sqlite$/, ""));
}

export function closeAllDatabases(): void {
  for (const [_, db] of connections.entries()) {
    try {
      db.close();
    } catch {}
  }
  connections.clear();
}
