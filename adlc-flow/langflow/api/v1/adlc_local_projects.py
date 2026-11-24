"""Authenticated local folder selection; never accept client-provided execution paths."""

import asyncio
import ipaddress
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from langflow.adlc.local_projects import (
    LocalFolderListing,
    LocalProjectError,
    LocalProjectRead,
    checked_folder,
    inspect_local_project,
    list_local_folders,
    prepare_project_source,
)
from langflow.api.utils import CurrentActiveUser, DbSession
from langflow.services.authorization import ProjectAction, ensure_project_permission
from langflow.services.database.models.adlc_local_project import AdlcLocalProject
from langflow.services.database.models.folder.model import Folder

router = APIRouter()


def require_local(request: Request) -> None:
    try:
        local = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = request.client is not None and request.client.host == "testclient"
    if not local:
        raise HTTPException(403, "Local folder selection is available from the computer running vAIPlatform.")


def project_error(exc: LocalProjectError) -> HTTPException:
    return HTTPException(exc.status_code, {"code": exc.code, "message": str(exc)})


class OpenLocalProject(BaseModel):
    source_path: str = Field(min_length=1, max_length=4096)
    name: str | None = Field(default=None, min_length=1, max_length=255)


@router.get("/local-folders", response_model=LocalFolderListing)
async def browse_local_folders(request: Request, current_user: CurrentActiveUser, path: str | None = None):
    require_local(request)
    await ensure_project_permission(current_user, ProjectAction.CREATE)
    try:
        return await asyncio.to_thread(list_local_folders, path)
    except LocalProjectError as exc:
        raise project_error(exc) from exc


@router.get("/local-projects", response_model=list[LocalProjectRead])
async def read_local_projects(request: Request, current_user: CurrentActiveUser, session: DbSession):
    require_local(request)
    rows = (
        await session.exec(
            select(AdlcLocalProject, Folder)
            .join(Folder, Folder.id == AdlcLocalProject.project_id)
            .where(AdlcLocalProject.owner_id == str(current_user.id), Folder.user_id == current_user.id)
        )
    ).all()
    return await asyncio.gather(
        *(
            asyncio.to_thread(inspect_local_project, row.project_id, folder.name, row.source_path)
            for row, folder in rows
        )
    )


@router.post("/local-projects", response_model=LocalProjectRead, status_code=201)
async def open_local_project(
    command: OpenLocalProject, request: Request, current_user: CurrentActiveUser, session: DbSession
):
    require_local(request)
    await ensure_project_permission(current_user, ProjectAction.CREATE)
    try:
        source = await asyncio.to_thread(checked_folder, command.source_path)
    except LocalProjectError as exc:
        raise project_error(exc) from exc
    # Capture plain values before any commit or rollback. A rollback expires
    # every ORM instance in the shared request session, so touching an
    # instance attribute afterwards (for example current_user.id) lazy-loads
    # outside the greenlet context and raises MissingGreenlet.
    owner_id = str(current_user.id)
    source_path = str(source)
    existing = (
        await session.exec(
            select(AdlcLocalProject).where(
                AdlcLocalProject.owner_id == owner_id, AdlcLocalProject.source_path == source_path
            )
        )
    ).first()
    if existing:
        folder = await session.get(Folder, existing.project_id)
        if folder is not None and str(folder.user_id) == owner_id:
            return await asyncio.to_thread(inspect_local_project, folder.id, folder.name, existing.source_path)
        # The registration row is orphaned: its project folder no longer
        # exists (foreign keys are not enforced on SQLite). Drop the row and
        # open the folder as a fresh project below.
        await session.delete(existing)
        await session.flush()
    name = (command.name or source.name or "Local project").strip() or "Local project"
    names = set((await session.exec(select(Folder.name).where(Folder.user_id == current_user.id))).all())
    candidate, suffix = name, 2
    while candidate in names:
        candidate = f"{name} ({suffix})"
        suffix += 1
    folder = Folder(id=uuid4(), name=candidate, description="Local development project", user_id=current_user.id)
    folder_id, folder_name = folder.id, candidate
    session.add(folder)
    await session.flush()
    session.add(AdlcLocalProject(project_id=folder_id, owner_id=owner_id, source_path=source_path))
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        # Only plain values are safe here: the rollback expired every loaded
        # instance, including current_user. A concurrent open or a previously
        # orphaned registration row may own the same source path.
        winner = (
            await session.exec(
                select(AdlcLocalProject).where(
                    AdlcLocalProject.owner_id == owner_id, AdlcLocalProject.source_path == source_path
                )
            )
        ).first()
        if winner:
            saved = await session.get(Folder, winner.project_id)
            if saved is not None and str(saved.user_id) == owner_id:
                saved_id, saved_name, saved_source = saved.id, saved.name, winner.source_path
                return await asyncio.to_thread(inspect_local_project, saved_id, saved_name, saved_source)
            await session.delete(winner)
            await session.flush()
        raise HTTPException(409, "The project changed while opening it. Try again.") from exc
    return await asyncio.to_thread(inspect_local_project, folder_id, folder_name, source_path)


async def project_context(flow, current_user, session) -> dict | None:
    if session is None or getattr(flow, "folder_id", None) is None:
        return None
    row = await session.get(AdlcLocalProject, flow.folder_id)
    if not isinstance(row, AdlcLocalProject):
        return None
    folder = await session.get(Folder, row.project_id)
    if row.owner_id != str(current_user.id) or folder is None or folder.user_id != current_user.id:
        raise HTTPException(404, "The local project is unavailable.")
    try:
        return await asyncio.to_thread(prepare_project_source, row.project_id, folder.name, row.source_path)
    except LocalProjectError as exc:
        raise project_error(exc) from exc
