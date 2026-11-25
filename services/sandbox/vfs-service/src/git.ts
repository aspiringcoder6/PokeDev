import fs from "fs";
import path from "path";
import os from "os";
import git from "isomorphic-git";
import http from "isomorphic-git/http/node";
import { VfsService } from "./vfs";
import { getWorkspaceDatabase, GitMetaRecord, workspaceExists } from "./db";
import { shouldIgnoreVfsPath } from "./ignore-rules";

/**
 * Git layer for VFS-centric architecture.
 *
 * - VFS (SQLite) is the single source of truth for source code.
 * - Each workspace keeps a persistent git worktree mirror at
 *   data/git-worktrees/<workspaceId> so commits build REAL incremental
 *   history (no more single-commit force pushes).
 * - Role-based branch protection: role "agent" may only create/commit/push
 *   on branches starting with "agent-", while keeping READ access to any
 *   branch (listBranches, readBlob). Role "human" is unrestricted.
 * - Supports GitHub, GitLab and any git remote via host-aware token auth.
 */

const AGENT_BRANCH_PREFIX = "agent-";

export type GitRole = "agent" | "human";

/** Thrown when a role tries to operate outside its allowed branch scope. */
export class GitPolicyError extends Error {
  status = 403;
  constructor(message: string) {
    super(message);
    this.name = "GitPolicyError";
  }
}

/**
 * Host-aware auth for isomorphic-git http transport.
 * Returns a CALLBACK (isomorphic-git expects onAuth to be a function).
 * - GitHub PATs:  https://x-access-token:<token>@github.com/...
 * - GitLab PATs:  https://oauth2:<token>@gitlab.com/...
 * - Other hosts:  token as username.
 */
function onAuthFor(url: string, token?: string): (() => { username: string; password: string }) | undefined {
  if (!token) return undefined;
  let username = token;
  try {
    const host = new URL(url).hostname;
    if (host.includes("github")) username = "x-access-token";
    else if (host.includes("gitlab")) username = "oauth2";
  } catch {
    /* keep token as username */
  }
  return () => ({ username, password: token });
}

export interface GitCloneOptions {
  workspaceId: string;
  url: string;
  branch?: string;
  token?: string;
  depth?: number;
  role?: GitRole;
}

export interface GitCommitOptions {
  workspaceId: string;
  message: string;
  authorName?: string;
  authorEmail?: string;
  role?: GitRole;
}

export interface GitPushOptions {
  workspaceId: string;
  remoteUrl?: string;
  token?: string;
  branch?: string;
  force?: boolean;
  role?: GitRole;
}

export interface GitSyncOptions {
  workspaceId: string;
  message?: string;
  authorName?: string;
  authorEmail?: string;
  remoteUrl?: string;
  token?: string;
  role?: GitRole;
}

export interface GitPullOptions {
  workspaceId: string;
  base?: string;
  remoteUrl?: string;
  token?: string;
  role?: GitRole;
}

export interface GitRefsOptions {
  workspaceId: string;
  remoteUrl?: string;
  token?: string;
  role?: GitRole;
}

export interface GitBlobOptions {
  workspaceId: string;
  ref: string;
  path: string;
  role?: GitRole;
}

export class GitService {
  private vfs = new VfsService();

  private worktreePath(workspaceId: string): string {
    // process.cwd() is vfs-service/ -> data/git-worktrees/<workspaceId>
    return path.join(process.cwd(), "data", "git-worktrees", workspaceId);
  }

  private assertBranchAllowed(branch: string, role: GitRole = "human"): void {
    if (role === "agent" && !branch.startsWith(AGENT_BRANCH_PREFIX)) {
      throw new GitPolicyError(
        `Role 'agent' may only operate on branches starting with '${AGENT_BRANCH_PREFIX}' (got '${branch}')`
      );
    }
  }

  private assertHuman(role: GitRole = "human", action: string): void {
    if (role === "agent") {
      throw new GitPolicyError(`Role 'agent' is not allowed to '${action}' (human only)`);
    }
  }

  private scanDir(dir: string, baseDir: string = dir): string[] {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    let files: string[] = [];

    for (const entry of entries) {
      if (entry.name === ".git") continue;
      const fullPath = path.join(dir, entry.name);

      if (entry.isDirectory()) {
        files = files.concat(this.scanDir(fullPath, baseDir));
      } else if (entry.isFile()) {
        const rel = "/" + path.relative(baseDir, fullPath).replace(/\\/g, "/");
        if (!shouldIgnoreVfsPath(rel)) {
          files.push(rel);
        }
      }
    }
    return files;
  }

  private async getMeta(workspaceId: string): Promise<{
    headCommit: string | null;
    branch: string;
    remoteUrl: string | null;
  }> {
    // Read-only: unknown workspaces get default meta without creating a sqlite
    if (!workspaceExists(workspaceId)) {
      return { headCommit: null, branch: "main", remoteUrl: null };
    }
    const db = getWorkspaceDatabase(workspaceId);
    const stmt = db.prepare(`
      SELECT head_commit, branch, remote_url
      FROM git_meta
      WHERE id = 1
    `);
    const meta = (stmt.get() as GitMetaRecord | undefined) || {
      id: 1,
      head_commit: null,
      branch: "main",
      remote_url: null,
    };
    return {
      headCommit: meta.head_commit,
      branch: meta.branch || "main",
      remoteUrl: meta.remote_url,
    };
  }

  private saveMeta(
    workspaceId: string,
    patch: { headCommit?: string | null; branch?: string; remoteUrl?: string | null }
  ): void {
    const db = getWorkspaceDatabase(workspaceId);
    const stmt = db.prepare(`
      INSERT INTO git_meta (id, head_commit, branch, remote_url)
      VALUES (1, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        head_commit = excluded.head_commit,
        branch = excluded.branch,
        remote_url = excluded.remote_url
    `);
    stmt.run(patch.headCommit ?? null, patch.branch ?? "main", patch.remoteUrl ?? null);
  }

  /** Ensure the worktree has an "origin" remote configured with the given url. */
  private async ensureRemote(dir: string, url: string): Promise<void> {
    try {
      const remotes = await git.listRemotes({ fs, dir });
      const origin = remotes.find((r) => r.remote === "origin");
      if (!origin) {
        await git.addRemote({ fs, dir, remote: "origin", url });
      } else if (origin.url !== url) {
        await git.deleteRemote({ fs, dir, remote: "origin" });
        await git.addRemote({ fs, dir, remote: "origin", url });
      }
    } catch {
      /* best effort */
    }
  }

  /**
   * Ensure a git worktree exists for the workspace.
   * If missing, initialize a fresh repo and materialize the current VFS state.
   */
  private async ensureWorktree(workspaceId: string): Promise<string> {
    await this.repairFromWorktreeIfOrphaned(workspaceId);
    const dir = this.worktreePath(workspaceId);
    const meta = await this.getMeta(workspaceId);

    if (!fs.existsSync(path.join(dir, ".git"))) {
      fs.mkdirSync(dir, { recursive: true });
      await git.init({ fs, dir, defaultBranch: meta.branch || "main" });
      await this.materializeVfsIntoWorktree(workspaceId, dir);
    }
    if (meta.remoteUrl) {
      await this.ensureRemote(dir, meta.remoteUrl);
    }
    return dir;
  }

  /**
   * Self-heal an ORPHANED worktree: a worktree directory with a .git exists
   * while the workspace SQLite database does not. This happens when the VFS
   * service dies between `git.clone()` finishing and the ingest loop writing
   * files into SQLite (the worktree is only cleaned up when clone() throws —
   * a killed process skips the cleanup). Repair = ingest the worktree back
   * into VFS (the master store) and restore git_meta from the worktree.
   */
  private async repairFromWorktreeIfOrphaned(workspaceId: string): Promise<void> {
    const dir = this.worktreePath(workspaceId);
    if (!fs.existsSync(path.join(dir, ".git"))) return;
    if (workspaceExists(workspaceId)) return;

    console.warn(
      `[GitService] Orphaned worktree detected for workspace '${workspaceId}' ` +
        `(worktree without SQLite) — re-ingesting worktree into VFS`
    );
    const scanned = this.scanDir(dir);
    for (const relPath of scanned) {
      const localPath = path.join(dir, relPath.replace(/^\//, ""));
      const content = fs.readFileSync(localPath);
      this.vfs.writeFile(workspaceId, relPath, content);
    }

    const headSha = await git.resolveRef({ fs, dir, ref: "HEAD" }).catch(() => null);
    const branch =
      (await git.currentBranch({ fs, dir, fullname: false }).catch(() => null)) || "main";
    let remoteUrl: string | null = null;
    try {
      const remotes = await git.listRemotes({ fs, dir });
      remoteUrl = remotes.find((r) => r.remote === "origin")?.url ?? null;
    } catch {
      /* best effort */
    }
    this.saveMeta(workspaceId, { headCommit: headSha, branch, remoteUrl });
    console.warn(
      `[GitService] Repaired workspace '${workspaceId}' from worktree: ` +
        `${scanned.length} files, head=${headSha ?? "null"}, branch=${branch ?? "main"}`
    );
  }

  /**
   * Mirror VFS state into the worktree:
   * - write/update every VFS file
   * - delete worktree files that no longer exist in VFS
   * Returns the list of deleted relative paths (for git remove).
   */
  private async materializeVfsIntoWorktree(workspaceId: string, dir: string): Promise<string[]> {
    const files = this.vfs.listFiles(workspaceId);
    const vfsPaths = new Set<string>();

    for (const file of files) {
      const record = this.vfs.readFile(workspaceId, file.path);
      const relPath = file.path.replace(/^\//, "");
      vfsPaths.add("/" + relPath.replace(/\\/g, "/"));
      const targetPath = path.join(dir, relPath);
      fs.mkdirSync(path.dirname(targetPath), { recursive: true });
      if (record.isBinary) {
        fs.writeFileSync(targetPath, Buffer.from(record.content, "base64"));
      } else {
        fs.writeFileSync(targetPath, record.content, "utf-8");
      }
    }

    // Remove worktree files that were deleted from VFS (staging handled by git add -A)
    const removed: string[] = [];
    const worktreeFiles = fs.existsSync(dir) ? this.scanDir(dir) : [];
    for (const wf of worktreeFiles) {
      if (!vfsPaths.has(wf)) {
        const targetPath = path.join(dir, wf.replace(/^\//, ""));
        try {
          fs.rmSync(targetPath, { force: true });
        } catch {
          /* best effort */
        }
        removed.push(wf.replace(/^\//, ""));
      }
    }
    return removed;
  }

  async clone(options: GitCloneOptions): Promise<{ headCommit: string; filesIngested: number; branch: string }> {
    const { workspaceId, url, branch, token, depth } = options;
    const dir = this.worktreePath(workspaceId);

    try {
      // Fresh clone: wipe any previous worktree for this workspace
      if (fs.existsSync(dir)) {
        fs.rmSync(dir, { recursive: true, force: true });
      }
      fs.mkdirSync(dir, { recursive: true });

      // Empty repository (no commits yet): initialize a fresh worktree instead of failing
      const remoteInfo = await git
        .getRemoteInfo({ http, url, onAuth: onAuthFor(url, token) })
        .catch(() => undefined);
      if (!remoteInfo || Object.keys(remoteInfo.refs || {}).length === 0) {
        const startBranch = branch || "main";
        await git.init({ fs, dir, defaultBranch: startBranch });
        this.saveMeta(workspaceId, { headCommit: null, branch: startBranch, remoteUrl: url });
        return { headCommit: "", filesIngested: 0, branch: startBranch };
      }

      const cloneOptions: any = {
        fs,
        http,
        dir,
        url,
        onAuth: onAuthFor(url, token),
      };
      if (branch) {
        cloneOptions.ref = branch;
      }
      if (depth && depth > 0) {
        cloneOptions.depth = depth;
      }
      await git.clone(cloneOptions);

      const headSha = await git.resolveRef({ fs, dir, ref: "HEAD" });
      const currentBranch = (await git.currentBranch({ fs, dir, fullname: false })) || branch || "main";

      const scannedFiles = this.scanDir(dir);
      let ingestedCount = 0;
      for (const relPath of scannedFiles) {
        const localPath = path.join(dir, relPath.replace(/^\//, ""));
        const content = fs.readFileSync(localPath);
        this.vfs.writeFile(workspaceId, relPath, content);
        ingestedCount += 1;
      }

      this.saveMeta(workspaceId, { headCommit: headSha, branch: currentBranch, remoteUrl: url });

      return { headCommit: headSha, filesIngested: ingestedCount, branch: currentBranch };
    } catch (err) {
      // Do not leave a broken worktree behind
      if (fs.existsSync(dir)) {
        try {
          fs.rmSync(dir, { recursive: true, force: true });
        } catch {
          /* ignore */
        }
      }
      throw err;
    }
  }

  async getStatus(workspaceId: string): Promise<{
    headCommit: string | null;
    branch: string;
    remoteUrl: string | null;
    fileCount: number;
    worktree: boolean;
  }> {
    // Self-heal: an orphaned worktree (process died between git.clone() and
    // the SQLite ingest) is re-ingested on the first status check.
    await this.repairFromWorktreeIfOrphaned(workspaceId);
    const meta = await this.getMeta(workspaceId);
    const files = this.vfs.listFiles(workspaceId);
    return {
      headCommit: meta.headCommit,
      branch: meta.branch,
      remoteUrl: meta.remoteUrl,
      fileCount: files.length,
      worktree: fs.existsSync(path.join(this.worktreePath(workspaceId), ".git")),
    };
  }

  async createBranch(options: {
    workspaceId: string;
    branch: string;
    checkout?: boolean;
    role?: GitRole;
  }): Promise<{ branch: string; headCommit: string | null }> {
    const { workspaceId, branch, checkout = true, role = "human" } = options;
    if (!branch || !branch.trim()) {
      throw new Error("Branch name cannot be empty");
    }

    const trimmed = branch.trim();
    this.assertBranchAllowed(trimmed, role);
    const meta = await this.getMeta(workspaceId);

    if (checkout) {
      const dir = await this.ensureWorktree(workspaceId);
      const branches = await git.listBranches({ fs, dir });
      if (branches.includes(trimmed)) {
        await git.checkout({ fs, dir, ref: trimmed });
      } else {
        await git.branch({ fs, dir, ref: trimmed, checkout: true });
      }
      const head = await git.resolveRef({ fs, dir, ref: "HEAD" }).catch(() => meta.headCommit);
      this.saveMeta(workspaceId, { headCommit: head, branch: trimmed, remoteUrl: meta.remoteUrl });
      return { branch: trimmed, headCommit: head };
    }

    return { branch: trimmed, headCommit: meta.headCommit };
  }

  async commit(options: GitCommitOptions): Promise<{ commitSha: string; branch: string }> {
    const {
      workspaceId,
      message,
      authorName = "AI Agent",
      authorEmail = "agent@vfs.local",
      role = "human",
    } = options;

    const meta = await this.getMeta(workspaceId);
    this.assertBranchAllowed(meta.branch, role);

    const dir = await this.ensureWorktree(workspaceId);
    const removed = await this.materializeVfsIntoWorktree(workspaceId, dir);
    for (const relPath of removed) {
      await git.remove({ fs, dir, filepath: relPath }).catch(() => undefined);
    }

    await git.add({ fs, dir, filepath: "." });

    const commitSha = await git.commit({
      fs,
      dir,
      message,
      author: { name: authorName, email: authorEmail },
    });

    this.saveMeta(workspaceId, { headCommit: commitSha, branch: meta.branch, remoteUrl: meta.remoteUrl });
    return { commitSha, branch: meta.branch };
  }

  async push(options: GitPushOptions): Promise<{ success: boolean; pushedRef: string }> {
    const { workspaceId, token, force = false, role = "human" } = options;
    const meta = await this.getMeta(workspaceId);
    const remoteUrl = options.remoteUrl || meta.remoteUrl;
    const branch = options.branch || meta.branch;

    this.assertBranchAllowed(branch, role);

    if (!remoteUrl) {
      throw new Error("No remote URL configured for this workspace.");
    }

    const dir = await this.ensureWorktree(workspaceId);
    const removed = await this.materializeVfsIntoWorktree(workspaceId, dir);
    for (const relPath of removed) {
      await git.remove({ fs, dir, filepath: relPath }).catch(() => undefined);
    }
    await git.add({ fs, dir, filepath: "." });

    const hasStagedChanges = await this.worktreeHasChanges(dir);
    if (hasStagedChanges) {
      const sha = await git.commit({
        fs,
        dir,
        message: "Update from VFS",
        author: { name: "VFS", email: "vfs@sandbox.local" },
      });
      this.saveMeta(workspaceId, { headCommit: sha });
    }

    await git.push({
      fs,
      http,
      dir,
      url: remoteUrl,
      ref: branch,
      remoteRef: branch,
      force,
      onAuth: onAuthFor(remoteUrl, token),
    });

    return { success: true, pushedRef: branch };
  }

  /**
   * Commit all dirty VFS changes to the current branch, then push to the remote.
   * The one-call "sync agent work to GitLab/GitHub" endpoint.
   */
  async sync(options: GitSyncOptions): Promise<{ commitSha: string; branch: string; pushed: boolean }> {
    const { workspaceId, message, authorName, authorEmail, remoteUrl, token, role = "human" } = options;

    const meta = await this.getMeta(workspaceId);
    this.assertBranchAllowed(meta.branch, role);

    const commitResult = await this.commit({
      workspaceId,
      message: message || `Agent update ${new Date().toISOString()}`,
      authorName: authorName || (role === "agent" ? `agent-${workspaceId}` : authorName),
      authorEmail: authorEmail || (role === "agent" ? `agent-${workspaceId}@sandbox.local` : authorEmail),
      role,
    });

    let pushed = false;
    const url = remoteUrl || meta.remoteUrl;
    if (url) {
      await this.push({ workspaceId, remoteUrl: url, token, role });
      pushed = true;
    }

    return { commitSha: commitResult.commitSha, branch: commitResult.branch, pushed };
  }

  /**
   * Fetch origin and merge origin/<base> into the current branch.
   * Human-only. On merge conflict, nothing is ingested back into VFS;
   * the caller is told to resolve via MR/remote.
   */
  async pull(options: GitPullOptions): Promise<{
    merged: boolean;
    fastForward: boolean;
    headCommit?: string;
    conflictFiles?: string[];
    ingested?: number;
  }> {
    const { workspaceId, base = "main", remoteUrl, token, role = "human" } = options;
    this.assertHuman(role, "pull from remote");

    const meta = await this.getMeta(workspaceId);
    const url = remoteUrl || meta.remoteUrl;
    if (!url) {
      throw new Error("No remote URL configured for this workspace.");
    }
    if (!meta.headCommit) {
      throw new Error("Workspace has no git history. Clone a repository first.");
    }

    const dir = await this.ensureWorktree(workspaceId);
    await git.fetch({ fs, http, dir, remote: "origin", ref: base, onAuth: onAuthFor(url, token) });

    const theirRef = `origin/${base}`;
    let fastForward = true;
    try {
      const mergeResult: any = await git.merge({
        fs,
        dir,
        ours: meta.branch,
        theirs: theirRef,
        author: { name: "VFS Pull", email: "vfs@sandbox.local" },
        message: `Merge ${theirRef} into ${meta.branch}`,
        fastForwardOnly: false,
      });
      fastForward = !!mergeResult?.fastForward;
    } catch (err: any) {
      if (err?.name === "MergeConflictError" || err?.code === "MergeConflictError") {
        const files: string[] = err?.data?.filepaths || [];
        return { merged: false, fastForward: false, conflictFiles: files };
      }
      throw err;
    }

    const headSha = await git.resolveRef({ fs, dir, ref: "HEAD" });

    // Ingest merged state back into VFS (master store)
    const scannedFiles = this.scanDir(dir);
    for (const relPath of scannedFiles) {
      const localPath = path.join(dir, relPath.replace(/^\//, ""));
      const content = fs.readFileSync(localPath);
      this.vfs.writeFile(workspaceId, relPath, content);
    }
    // Remove VFS files deleted by the merge
    const vfsFiles = this.vfs.listFiles(workspaceId);
    const worktreeSet = new Set(scannedFiles);
    for (const vf of vfsFiles) {
      if (!worktreeSet.has(vf.path)) {
        this.vfs.deleteFile(workspaceId, vf.path);
      }
    }

    this.saveMeta(workspaceId, { headCommit: headSha, branch: meta.branch, remoteUrl: url });
    return { merged: true, fastForward, headCommit: headSha, ingested: scannedFiles.length };
  }

  /** List local + remote branches (read: allowed for every role). */
  async listBranches(options: GitRefsOptions): Promise<{
    current: string | null;
    local: string[];
    remote: string[];
  }> {
    const { workspaceId, remoteUrl, token } = options;
    const meta = await this.getMeta(workspaceId);
    const url = remoteUrl || meta.remoteUrl;

    if (!fs.existsSync(path.join(this.worktreePath(workspaceId), ".git"))) {
      return { current: meta.branch, local: [], remote: [] };
    }

    const dir = this.worktreePath(workspaceId);

    if (url) {
      await this.ensureRemote(dir, url);
      await git
        .fetch({ fs, http, dir, remote: "origin", onAuth: onAuthFor(url, token) })
        .catch(() => undefined);
    }

    const local = await git.listBranches({ fs, dir });
    let remote: string[] = [];
    try {
      remote = await git.listBranches({ fs, dir, remote: "origin" });
    } catch {
      remote = [];
    }
    const current = await git.currentBranch({ fs, dir, fullname: false }).catch(() => null);
    return { current: current || meta.branch, local, remote };
  }

  /**
   * Read a file blob at any ref (branch/commit/tag) WITHOUT checkout.
   * Read operation: allowed for every role — agents can inspect other branches.
   */
  async readBlob(options: GitBlobOptions): Promise<{
    path: string;
    ref: string;
    oid: string;
    isBinary: boolean;
    encoding: "utf-8" | "base64";
    content: string;
  }> {
    const { workspaceId, ref, path: filepath, role = "human" } = options;
    if (!ref || !filepath) {
      throw new Error("Missing ref or path");
    }
    this.assertHumanReadPath(filepath, role);

    if (!fs.existsSync(path.join(this.worktreePath(workspaceId), ".git"))) {
      throw new Error("Workspace has no git worktree. Clone a repository first.");
    }
    const dir = this.worktreePath(workspaceId);

    // isomorphic-git readBlob needs an oid: resolve ref -> commit oid first
    let oid: string;
    try {
      oid = await git.resolveRef({ fs, dir, ref });
    } catch {
      oid = ref; // caller may pass a raw commit sha
    }
    const result = await git.readBlob({ fs, dir, oid, filepath: filepath.replace(/^\//, "") });

    const blob = Buffer.from(result.blob);
    const isBinary = blob.includes(0);
    return {
      path: filepath,
      ref,
      oid: result.oid,
      isBinary,
      encoding: isBinary ? "base64" : "utf-8",
      content: isBinary ? blob.toString("base64") : blob.toString("utf-8"),
    };
  }

  /**
   * Agents may not read credentials-style files from other branches as a
   * courtesy guard (best-effort: real secret policy lives in the platform).
   */
  private assertHumanReadPath(filepath: string, role: GitRole): void {
    if (role !== "agent") return;
    const base = filepath.split("/").pop() || filepath;
    if (base === ".env" || base === ".npmrc" || base === ".netrc" || base.endsWith(".pem")) {
      throw new GitPolicyError(`Role 'agent' is not allowed to read sensitive file '${base}' from git refs`);
    }
  }

  private async worktreeHasChanges(dir: string): Promise<boolean> {
    try {
      const status = await git.statusMatrix({ fs, dir });
      return status.some(([, head, workdir, stage]) => !(head === 1 && workdir === 1 && stage === 1));
    } catch {
      return true;
    }
  }
}
