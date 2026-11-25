import express, { Request, Response } from "express";
import cors from "cors";
import { VfsService } from "./vfs";
import { GitService, GitRole } from "./git";
import { normalizeTextEditArguments } from "./text-edit";

const app = express();
const port = parseInt(process.env.VFS_PORT || "8001", 10);

app.use(cors());
app.use(express.json({ limit: "50mb" }));
app.use(express.urlencoded({ extended: true, limit: "50mb" }));

const vfs = new VfsService();
const git = new GitService();

// Health check
app.get("/health", (_req: Request, res: Response) => {
  res.json({
    status: "ok",
    service: "vfs-service",
    version: "1.0.0",
    uptime: process.uptime(),
  });
});

// Write file
app.post("/api/vfs/file/write", (req: Request, res: Response) => {
  try {
    const { workspaceId, path, content, isBinary, encoding } = req.body;
    if (!workspaceId || !path || content === undefined) {
      return res.status(400).json({ error: "Missing workspaceId, path, or content" });
    }

    const result = vfs.writeFile(workspaceId, path, content, { isBinary, encoding });
    return res.json({ success: true, ...result });
  } catch (err: any) {
    return res.status(400).json({ success: false, error: err.message });
  }
});

// Read file
app.get("/api/vfs/file/read", (req: Request, res: Response) => {
  try {
    const workspaceId = req.query.workspaceId as string;
    const filePath = req.query.path as string;
    if (!workspaceId || !filePath) {
      return res.status(400).json({ error: "Missing workspaceId or path query parameter" });
    }

    const result = vfs.readFile(workspaceId, filePath);
    return res.json({ success: true, ...result });
  } catch (err: any) {
    const status = err.message.includes("not found") ? 404 : 400;
    return res.status(status).json({ success: false, error: err.message });
  }
});

// Edit file with fuzzy diff matching
app.post("/api/vfs/file/edit", (req: Request, res: Response) => {
  try {
    const { workspaceId, path } = req.body;
    if (!workspaceId || !path) {
      return res.status(400).json({ error: "Missing workspaceId or path" });
    }

    const edits = normalizeTextEditArguments(req.body);
    const result = vfs.editFile(workspaceId, path, edits);
    return res.json({ success: true, ...result });
  } catch (err: any) {
    return res.status(400).json({ success: false, error: err.message });
  }
});

// Delete file or directory
app.delete("/api/vfs/file", (req: Request, res: Response) => {
  try {
    const workspaceId = (req.query.workspaceId || req.body.workspaceId) as string;
    const filePath = (req.query.path || req.body.path) as string;
    const recursive = req.query.recursive === "true" || req.body.recursive === true;

    if (!workspaceId || !filePath) {
      return res.status(400).json({ error: "Missing workspaceId or path" });
    }

    const result = vfs.deleteFile(workspaceId, filePath, recursive);
    return res.json({ success: true, ...result });
  } catch (err: any) {
    return res.status(400).json({ success: false, error: err.message });
  }
});

// List files
app.get("/api/vfs/files", (req: Request, res: Response) => {
  try {
    const workspaceId = req.query.workspaceId as string;
    const prefix = req.query.prefix as string | undefined;
    const includeIgnored = req.query.includeIgnored === "true";

    if (!workspaceId) {
      return res.status(400).json({ error: "Missing workspaceId parameter" });
    }

    const files = vfs.listFiles(workspaceId, { prefix, includeIgnored });
    return res.json({ success: true, files });
  } catch (err: any) {
    return res.status(400).json({ success: false, error: err.message });
  }
});

// Get manifest for delta sync
app.get("/api/vfs/manifest", (req: Request, res: Response) => {
  try {
    const workspaceId = req.query.workspaceId as string;
    if (!workspaceId) {
      return res.status(400).json({ error: "Missing workspaceId parameter" });
    }

    const manifest = vfs.getManifest(workspaceId);
    return res.json({ success: true, manifest });
  } catch (err: any) {
    return res.status(400).json({ success: false, error: err.message });
  }
});

// Get revisions (undo history)
app.get("/api/vfs/revisions", (req: Request, res: Response) => {
  try {
    const workspaceId = req.query.workspaceId as string;
    const filePath = req.query.path as string;
    if (!workspaceId || !filePath) {
      return res.status(400).json({ error: "Missing workspaceId or path" });
    }

    const revisions = vfs.getRevisions(workspaceId, filePath);
    return res.json({ success: true, revisions });
  } catch (err: any) {
    return res.status(400).json({ success: false, error: err.message });
  }
});

// List all active workspace SQLite databases
app.get("/api/vfs/workspaces", (_req: Request, res: Response) => {
  try {
    const workspaces = vfs.listAllWorkspaces();
    return res.json({ success: true, workspaces });
  } catch (err: any) {
    return res.status(500).json({ success: false, error: err.message });
  }
});

// Delete entire workspace SQLite database
app.delete("/api/vfs/workspace", (req: Request, res: Response) => {
  try {
    const workspaceId = (req.query.workspaceId || req.body.workspaceId) as string;
    if (!workspaceId) {
      return res.status(400).json({ error: "Missing workspaceId" });
    }

    const deleted = vfs.deleteWorkspace(workspaceId);
    return res.json({ success: true, deleted, workspaceId });
  } catch (err: any) {
    return res.status(500).json({ success: false, error: err.message });
  }
});

// --- Git Endpoints ---

// Role comes from an explicit body field or X-VFS-Role header.
// "agent" roles are restricted to agent-* branches by GitService.
function resolveRole(bodyRole?: string, headerRole?: string): GitRole {
  const role = (bodyRole || headerRole || "human").toLowerCase();
  return role === "agent" ? "agent" : "human";
}

function resolveGitToken(token?: string): string | undefined {
  return token || process.env.VFS_GIT_TOKEN || process.env.GIT_TOKEN || undefined;
}

// Clone repository shallowly
app.post("/api/vfs/git/clone", async (req: Request, res: Response) => {
  try {
    const { workspaceId, url, branch, token, depth, role } = req.body;
    if (!workspaceId || !url) {
      return res.status(400).json({ error: "Missing workspaceId or url" });
    }

    const result = await git.clone({
      workspaceId,
      url,
      branch,
      token: resolveGitToken(token),
      depth,
      role: resolveRole(role, req.headers["x-vfs-role"] as string),
    });
    return res.json({ success: true, ...result });
  } catch (err: any) {
    return res.status(500).json({ success: false, error: err.message });
  }
});

// Git status
app.get("/api/vfs/git/status", async (req: Request, res: Response) => {
  try {
    const workspaceId = req.query.workspaceId as string;
    if (!workspaceId) {
      return res.status(400).json({ error: "Missing workspaceId" });
    }

    const status = await git.getStatus(workspaceId);
    return res.json({ success: true, ...status });
  } catch (err: any) {
    return res.status(500).json({ success: false, error: err.message });
  }
});

// Git branch (create or switch)
app.post("/api/vfs/git/branch", async (req: Request, res: Response) => {
  try {
    const { workspaceId, branch, checkout, role } = req.body;
    if (!workspaceId || !branch) {
      return res.status(400).json({ error: "Missing workspaceId or branch" });
    }

    const result = await git.createBranch({
      workspaceId,
      branch,
      checkout,
      role: resolveRole(role, req.headers["x-vfs-role"] as string),
    });
    return res.json({ success: true, ...result });
  } catch (err: any) {
    if (err?.name === "GitPolicyError") return res.status(403).json({ success: false, error: err.message, policy: true });
    return res.status(500).json({ success: false, error: err.message });
  }
});

// Git commit
app.post("/api/vfs/git/commit", async (req: Request, res: Response) => {
  try {
    const { workspaceId, message, authorName, authorEmail, role } = req.body;
    if (!workspaceId || !message) {
      return res.status(400).json({ error: "Missing workspaceId or message" });
    }

    const result = await git.commit({
      workspaceId,
      message,
      authorName,
      authorEmail,
      role: resolveRole(role, req.headers["x-vfs-role"] as string),
    });
    return res.json({ success: true, ...result });
  } catch (err: any) {
    if (err?.name === "GitPolicyError") return res.status(403).json({ success: false, error: err.message, policy: true });
    return res.status(500).json({ success: false, error: err.message });
  }
});

// Git push
app.post("/api/vfs/git/push", async (req: Request, res: Response) => {
  try {
    const { workspaceId, remoteUrl, token, branch, force, role } = req.body;
    if (!workspaceId) {
      return res.status(400).json({ error: "Missing workspaceId" });
    }

    const result = await git.push({
      workspaceId,
      remoteUrl,
      token: resolveGitToken(token),
      branch,
      force,
      role: resolveRole(role, req.headers["x-vfs-role"] as string),
    });
    return res.json({ success: true, ...result });
  } catch (err: any) {
    if (err?.name === "GitPolicyError") return res.status(403).json({ success: false, error: err.message, policy: true });
    return res.status(500).json({ success: false, error: err.message });
  }
});

// Git sync: commit dirty workspace + push (agent workflow entrypoint)
app.post("/api/vfs/git/sync", async (req: Request, res: Response) => {
  try {
    const { workspaceId, message, authorName, authorEmail, remoteUrl, token, role } = req.body;
    if (!workspaceId) {
      return res.status(400).json({ error: "Missing workspaceId" });
    }

    const result = await git.sync({
      workspaceId,
      message,
      authorName,
      authorEmail,
      remoteUrl,
      token: resolveGitToken(token),
      role: resolveRole(role, req.headers["x-vfs-role"] as string),
    });
    return res.json({ success: true, ...result });
  } catch (err: any) {
    if (err?.name === "GitPolicyError") return res.status(403).json({ success: false, error: err.message, policy: true });
    return res.status(500).json({ success: false, error: err.message });
  }
});

// Git pull: fetch origin + merge origin/<base> into current branch (human only)
app.post("/api/vfs/git/pull", async (req: Request, res: Response) => {
  try {
    const { workspaceId, base, remoteUrl, token, role } = req.body;
    if (!workspaceId) {
      return res.status(400).json({ error: "Missing workspaceId" });
    }

    const result = await git.pull({
      workspaceId,
      base,
      remoteUrl,
      token: resolveGitToken(token),
      role: resolveRole(role, req.headers["x-vfs-role"] as string),
    });
    return res.json({ success: true, ...result });
  } catch (err: any) {
    if (err?.name === "GitPolicyError") return res.status(403).json({ success: false, error: err.message, policy: true });
    return res.status(500).json({ success: false, error: err.message });
  }
});

// Git refs: list local + remote branches (read: every role)
app.get("/api/vfs/git/refs", async (req: Request, res: Response) => {
  try {
    const workspaceId = req.query.workspaceId as string;
    const role = resolveRole(undefined, req.headers["x-vfs-role"] as string);
    if (!workspaceId) {
      return res.status(400).json({ error: "Missing workspaceId" });
    }

    const result = await git.listBranches({ workspaceId, token: resolveGitToken() });
    void role;
    return res.json({ success: true, ...result });
  } catch (err: any) {
    return res.status(500).json({ success: false, error: err.message });
  }
});

// Git blob: read a file at any ref without checkout (read: every role)
app.get("/api/vfs/git/blob", async (req: Request, res: Response) => {
  try {
    const workspaceId = req.query.workspaceId as string;
    const ref = req.query.ref as string;
    const path = req.query.path as string;
    if (!workspaceId || !ref || !path) {
      return res.status(400).json({ error: "Missing workspaceId, ref or path" });
    }

    const result = await git.readBlob({
      workspaceId,
      ref,
      path,
      role: resolveRole(undefined, req.headers["x-vfs-role"] as string),
    });
    return res.json({ success: true, ...result });
  } catch (err: any) {
    if (err?.name === "GitPolicyError") return res.status(403).json({ success: false, error: err.message, policy: true });
    return res.status(500).json({ success: false, error: err.message });
  }
});

// Start listening if not imported as module
if (process.env.NODE_ENV !== "test") {
  app.listen(port, "0.0.0.0", () => {
    console.log(`[VFS Service] Running on http://localhost:${port}`);
  });
}

export default app;
