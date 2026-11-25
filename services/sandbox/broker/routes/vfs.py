from typing import Any, Dict, List, Optional
import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from broker.services.vfs_client import vfs_client
from broker.state import logger

router = APIRouter(prefix="/api/v1/vfs", tags=["Virtual File System"])


def _vfs_http_error(e: Exception) -> HTTPException:
    """Preserve VFS status codes (e.g. 403 git policy rejections) upstream."""
    if isinstance(e, httpx.HTTPStatusError):
        try:
            detail = e.response.json().get("error") or e.response.text
        except Exception:
            detail = str(e)
        return HTTPException(status_code=e.response.status_code, detail=detail)
    return HTTPException(status_code=500, detail=str(e))


class WriteFilePayload(BaseModel):
    workspace_id: str
    path: str
    content: str
    is_binary: bool = False
    encoding: str = "utf-8"


class EditFilePayload(BaseModel):
    workspace_id: str
    path: str
    edits: List[Dict[str, str]]


class GitClonePayload(BaseModel):
    workspace_id: str
    url: str
    branch: str = "main"
    token: Optional[str] = None
    depth: int = 1
    role: str = "human"


class GitBranchPayload(BaseModel):
    workspace_id: str
    branch: str
    checkout: bool = True
    role: str = "human"


class GitCommitPayload(BaseModel):
    workspace_id: str
    message: str
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    role: str = "human"


class GitPushPayload(BaseModel):
    workspace_id: str
    remote_url: Optional[str] = None
    token: Optional[str] = None
    branch: Optional[str] = None
    force: bool = False
    role: str = "human"


class GitSyncPayload(BaseModel):
    workspace_id: str
    message: Optional[str] = None
    author_name: Optional[str] = None
    author_email: Optional[str] = None
    remote_url: Optional[str] = None
    role: str = "human"


class GitPullPayload(BaseModel):
    workspace_id: str
    base: Optional[str] = None
    remote_url: Optional[str] = None
    role: str = "human"


@router.post("/file/write")
async def vfs_write_file(payload: WriteFilePayload):
    try:
        return await vfs_client.write_file(
            workspace_id=payload.workspace_id,
            path=payload.path,
            content=payload.content,
            is_binary=payload.is_binary,
            encoding=payload.encoding,
        )
    except Exception as e:
        logger.error(f"[VFS Route] Error writing file: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/file/read")
async def vfs_read_file(
    workspace_id: str = Query(..., alias="workspace_id"),
    path: str = Query(..., alias="path"),
):
    try:
        return await vfs_client.read_file(workspace_id=workspace_id, path=path)
    except Exception as e:
        logger.error(f"[VFS Route] Error reading file: {str(e)}")
        raise HTTPException(status_code=404 if "not found" in str(e).lower() else 400, detail=str(e))


@router.post("/file/edit")
async def vfs_edit_file(payload: EditFilePayload):
    try:
        return await vfs_client.edit_file(
            workspace_id=payload.workspace_id,
            path=payload.path,
            edits=payload.edits,
        )
    except Exception as e:
        logger.error(f"[VFS Route] Error editing file: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/file")
async def vfs_delete_file(
    workspace_id: str = Query(..., alias="workspace_id"),
    path: str = Query(..., alias="path"),
    recursive: bool = Query(False, alias="recursive"),
):
    try:
        return await vfs_client.delete_file(
            workspace_id=workspace_id, path=path, recursive=recursive
        )
    except Exception as e:
        logger.error(f"[VFS Route] Error deleting file: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/files")
async def vfs_list_files(
    workspace_id: str = Query(..., alias="workspace_id"),
    prefix: Optional[str] = Query(None, alias="prefix"),
    include_ignored: bool = Query(False, alias="include_ignored"),
):
    try:
        return await vfs_client.list_files(
            workspace_id=workspace_id, prefix=prefix, include_ignored=include_ignored
        )
    except Exception as e:
        logger.error(f"[VFS Route] Error listing files: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/manifest")
async def vfs_manifest(workspace_id: str = Query(..., alias="workspace_id")):
    try:
        return await vfs_client.get_manifest(workspace_id=workspace_id)
    except Exception as e:
        logger.error(f"[VFS Route] Error getting manifest: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/git/clone")
async def vfs_git_clone(payload: GitClonePayload):
    try:
        return await vfs_client.clone_repo(
            workspace_id=payload.workspace_id,
            url=payload.url,
            branch=payload.branch,
            token=payload.token,
            depth=payload.depth,
            role=payload.role,
        )
    except Exception as e:
        logger.error(f"[VFS Route] Error cloning repo: {str(e)}")
        raise _vfs_http_error(e)


@router.get("/git/status")
async def vfs_git_status(workspace_id: str = Query(..., alias="workspace_id")):
    try:
        return await vfs_client.git_status(workspace_id=workspace_id)
    except Exception as e:
        logger.error(f"[VFS Route] Error getting git status: {str(e)}")
        raise _vfs_http_error(e)


@router.get("/workspaces")
async def vfs_workspaces():
    """List configured projects (VFS workspaces)."""
    try:
        return await vfs_client.list_workspaces()
    except Exception as e:
        logger.error(f"[VFS Route] Error listing workspaces: {str(e)}")
        raise _vfs_http_error(e)


@router.post("/git/branch")
async def vfs_git_branch(payload: GitBranchPayload):
    try:
        return await vfs_client.create_branch(
            workspace_id=payload.workspace_id,
            branch=payload.branch,
            checkout=payload.checkout,
            role=payload.role,
        )
    except Exception as e:
        logger.error(f"[VFS Route] Error creating branch: {str(e)}")
        raise _vfs_http_error(e)


@router.post("/git/commit")
async def vfs_git_commit(payload: GitCommitPayload):
    try:
        return await vfs_client.git_commit(
            workspace_id=payload.workspace_id,
            message=payload.message,
            author_name=payload.author_name,
            author_email=payload.author_email,
            role=payload.role,
        )
    except Exception as e:
        logger.error(f"[VFS Route] Error committing git: {str(e)}")
        raise _vfs_http_error(e)


@router.post("/git/push")
async def vfs_git_push(payload: GitPushPayload):
    try:
        return await vfs_client.git_push(
            workspace_id=payload.workspace_id,
            remote_url=payload.remote_url,
            token=payload.token,
            branch=payload.branch,
            role=payload.role,
        )
    except Exception as e:
        logger.error(f"[VFS Route] Error pushing git: {str(e)}")
        raise _vfs_http_error(e)


@router.post("/git/sync")
async def vfs_git_sync(payload: GitSyncPayload):
    """Explicit commit + push to remote. Never automatic â€” agent or human decides when."""
    try:
        return await vfs_client.git_sync(
            workspace_id=payload.workspace_id,
            message=payload.message,
            author_name=payload.author_name,
            author_email=payload.author_email,
            remote_url=payload.remote_url,
            role=payload.role,
        )
    except Exception as e:
        logger.error(f"[VFS Route] Error syncing git: {str(e)}")
        raise _vfs_http_error(e)


@router.post("/git/pull")
async def vfs_git_pull(payload: GitPullPayload):
    """Fetch origin + merge origin/<base> into current branch (human only)."""
    try:
        return await vfs_client.git_pull(
            workspace_id=payload.workspace_id,
            base=payload.base,
            remote_url=payload.remote_url,
            role=payload.role,
        )
    except Exception as e:
        logger.error(f"[VFS Route] Error pulling git: {str(e)}")
        raise _vfs_http_error(e)


@router.get("/git/refs")
async def vfs_git_refs(
    workspace_id: str = Query(..., alias="workspace_id"),
    role: str = Query("human", alias="role"),
):
    """List local + remote branches (read: every role)."""
    try:
        return await vfs_client.git_refs(workspace_id=workspace_id, role=role)
    except Exception as e:
        logger.error(f"[VFS Route] Error listing git refs: {str(e)}")
        raise _vfs_http_error(e)


@router.get("/git/blob")
async def vfs_git_blob(
    workspace_id: str = Query(..., alias="workspace_id"),
    ref: str = Query(..., alias="ref"),
    path: str = Query(..., alias="path"),
    role: str = Query("human", alias="role"),
):
    """Read a file at any git ref without checkout (read: every role)."""
    try:
        return await vfs_client.git_blob(
            workspace_id=workspace_id, ref=ref, path=path, role=role
        )
    except Exception as e:
        logger.error(f"[VFS Route] Error reading git blob: {str(e)}")
        raise _vfs_http_error(e)
