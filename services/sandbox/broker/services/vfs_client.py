import os
from typing import Any, Dict, List, Optional
import httpx
from broker.state import logger

VFS_SERVICE_URL = os.environ.get("VFS_SERVICE_URL", "http://127.0.0.1:8001")

# Default per-request timeouts
T_FAST = 30.0
T_SLOW = 60.0
T_ASYNC = 120.0


def is_scratch_path(path: str) -> bool:
    """
    Check if path is intended for scratch/ephemeral execution.
    Scratch paths live exclusively in sandbox RAM (tmpfs) and never touch VFS/SQLite or Git.
    """
    normalized = path.replace("\\", "/")
    return (
        normalized.startswith("/scratch/")
        or normalized == "/scratch"
        or normalized.startswith("/tmp/")
        or normalized == "/tmp"
    )


class VfsClient:
    def __init__(self, base_url: str = VFS_SERVICE_URL):
        self.base_url = base_url.rstrip("/")
        # Shared keep-alive client: reusing one connection pool avoids the
        # ~0.6-2.7s TCP/connection setup cost of a new AsyncClient per call.
        self._client: Optional[httpx.AsyncClient] = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=T_FAST)
        return self._client

    async def write_file(
        self,
        workspace_id: str,
        path: str,
        content: str,
        is_binary: bool = False,
        encoding: str = "utf-8",
    ) -> Dict[str, Any]:
        resp = await self._http().post(
            f"{self.base_url}/api/vfs/file/write",
            json={
                "workspaceId": workspace_id,
                "path": path,
                "content": content,
                "isBinary": is_binary,
                "encoding": encoding,
            },
            timeout=T_FAST,
        )
        resp.raise_for_status()
        return resp.json()

    async def read_file(self, workspace_id: str, path: str) -> Dict[str, Any]:
        resp = await self._http().get(
            f"{self.base_url}/api/vfs/file/read",
            params={"workspaceId": workspace_id, "path": path},
            timeout=T_FAST,
        )
        resp.raise_for_status()
        return resp.json()

    async def edit_file(
        self, workspace_id: str, path: str, edits: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        resp = await self._http().post(
            f"{self.base_url}/api/vfs/file/edit",
            json={
                "workspaceId": workspace_id,
                "path": path,
                "edits": edits,
            },
            timeout=T_FAST,
        )
        resp.raise_for_status()
        return resp.json()

    async def delete_file(
        self, workspace_id: str, path: str, recursive: bool = False
    ) -> Dict[str, Any]:
        resp = await self._http().delete(
            f"{self.base_url}/api/vfs/file",
            params={
                "workspaceId": workspace_id,
                "path": path,
                "recursive": str(recursive).lower(),
            },
            timeout=T_FAST,
        )
        resp.raise_for_status()
        return resp.json()

    async def list_files(
        self,
        workspace_id: str,
        prefix: Optional[str] = None,
        include_ignored: bool = False,
    ) -> Dict[str, Any]:
        params = {"workspaceId": workspace_id, "includeIgnored": str(include_ignored).lower()}
        if prefix:
            params["prefix"] = prefix
        resp = await self._http().get(
            f"{self.base_url}/api/vfs/files",
            params=params,
            timeout=T_FAST,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_manifest(self, workspace_id: str) -> Dict[str, Any]:
        resp = await self._http().get(
            f"{self.base_url}/api/vfs/manifest",
            params={"workspaceId": workspace_id},
            timeout=T_FAST,
        )
        resp.raise_for_status()
        return resp.json()

    async def clone_repo(
        self,
        workspace_id: str,
        url: str,
        branch: str = "main",
        token: Optional[str] = None,
        depth: int = 1,
        role: str = "human",
    ) -> Dict[str, Any]:
        resp = await self._http().post(
            f"{self.base_url}/api/vfs/git/clone",
            json={
                "workspaceId": workspace_id,
                "url": url,
                "branch": branch,
                "token": token,
                "depth": depth,
                "role": role,
            },
            timeout=T_ASYNC,
        )
        resp.raise_for_status()
        return resp.json()

    async def git_status(self, workspace_id: str) -> Dict[str, Any]:
        resp = await self._http().get(
            f"{self.base_url}/api/vfs/git/status",
            params={"workspaceId": workspace_id},
            timeout=T_FAST,
        )
        resp.raise_for_status()
        return resp.json()

    async def list_workspaces(self) -> Dict[str, Any]:
        resp = await self._http().get(
            f"{self.base_url}/api/vfs/workspaces",
            timeout=T_FAST,
        )
        resp.raise_for_status()
        return resp.json()

    async def create_branch(
        self,
        workspace_id: str,
        branch: str,
        checkout: bool = True,
        role: str = "human",
    ) -> Dict[str, Any]:
        resp = await self._http().post(
            f"{self.base_url}/api/vfs/git/branch",
            json={
                "workspaceId": workspace_id,
                "branch": branch,
                "checkout": checkout,
                "role": role,
            },
            timeout=T_FAST,
        )
        resp.raise_for_status()
        return resp.json()

    async def git_commit(
        self,
        workspace_id: str,
        message: str,
        author_name: Optional[str] = None,
        author_email: Optional[str] = None,
        role: str = "human",
    ) -> Dict[str, Any]:
        resp = await self._http().post(
            f"{self.base_url}/api/vfs/git/commit",
            json={
                "workspaceId": workspace_id,
                "message": message,
                "authorName": author_name,
                "authorEmail": author_email,
                "role": role,
            },
            timeout=T_SLOW,
        )
        resp.raise_for_status()
        return resp.json()

    async def git_push(
        self,
        workspace_id: str,
        remote_url: Optional[str] = None,
        token: Optional[str] = None,
        branch: Optional[str] = None,
        role: str = "human",
    ) -> Dict[str, Any]:
        resp = await self._http().post(
            f"{self.base_url}/api/vfs/git/push",
            json={
                "workspaceId": workspace_id,
                "remoteUrl": remote_url,
                "token": token,
                "branch": branch,
                "role": role,
            },
            timeout=T_ASYNC,
        )
        resp.raise_for_status()
        return resp.json()

    async def git_sync(
        self,
        workspace_id: str,
        message: Optional[str] = None,
        author_name: Optional[str] = None,
        author_email: Optional[str] = None,
        remote_url: Optional[str] = None,
        role: str = "human",
    ) -> Dict[str, Any]:
        """Explicit commit-and-push of dirty VFS state (agent or human decision)."""
        resp = await self._http().post(
            f"{self.base_url}/api/vfs/git/sync",
            json={
                "workspaceId": workspace_id,
                "message": message,
                "authorName": author_name,
                "authorEmail": author_email,
                "remoteUrl": remote_url,
                "role": role,
            },
            timeout=T_ASYNC,
        )
        resp.raise_for_status()
        return resp.json()

    async def git_pull(
        self,
        workspace_id: str,
        base: Optional[str] = None,
        remote_url: Optional[str] = None,
        role: str = "human",
    ) -> Dict[str, Any]:
        """Fetch origin and merge origin/<base> into current branch (human only)."""
        resp = await self._http().post(
            f"{self.base_url}/api/vfs/git/pull",
            json={
                "workspaceId": workspace_id,
                "base": base,
                "remoteUrl": remote_url,
                "role": role,
            },
            timeout=T_ASYNC,
        )
        resp.raise_for_status()
        return resp.json()

    async def git_refs(self, workspace_id: str, role: str = "human") -> Dict[str, Any]:
        """List local + remote branches (read: every role)."""
        resp = await self._http().get(
            f"{self.base_url}/api/vfs/git/refs",
            params={"workspaceId": workspace_id},
            headers={"X-VFS-Role": role},
            timeout=T_FAST,
        )
        resp.raise_for_status()
        return resp.json()

    async def git_blob(self, workspace_id: str, ref: str, path: str, role: str = "human") -> Dict[str, Any]:
        """Read a file at any git ref without checkout (read: every role)."""
        resp = await self._http().get(
            f"{self.base_url}/api/vfs/git/blob",
            params={"workspaceId": workspace_id, "ref": ref, "path": path},
            headers={"X-VFS-Role": role},
            timeout=T_FAST,
        )
        resp.raise_for_status()
        return resp.json()


# Singleton instance
vfs_client = VfsClient()
