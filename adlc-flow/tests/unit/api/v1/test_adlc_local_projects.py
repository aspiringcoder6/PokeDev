# ruff: noqa: S101
"""Reopening a local folder whose registration row is orphaned must heal, not crash."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from langflow.adlc.local_projects import git_at
from langflow.api.v1 import adlc_local_projects as local_projects_api
from langflow.services.auth.utils import get_current_active_user
from langflow.services.database.models.adlc_local_project.model import AdlcLocalProject
from langflow.services.database.models.folder.model import Folder
from lfx.services.deps import injectable_session_scope

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from sqlalchemy.ext.asyncio import AsyncEngine


async def _engine(tmp_path: Path) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'local-projects.sqlite3'}")
    tables = [SQLModel.metadata.tables["folder"], SQLModel.metadata.tables["adlc_local_project"]]
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all, tables=tables)
    return engine


def _committed_repository(root: Path) -> Path:
    source = root / "source"
    source.mkdir()
    git_at(source, "init", "-q")
    (source / "README.md").write_text("committed\n", encoding="utf-8")
    git_at(source, "add", ".")
    git_at(source, "-c", "user.name=Check", "-c", "user.email=check@example.invalid", "commit", "-qm", "base")
    return source


def _app(engine: AsyncEngine, owner_id: UUID, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    user = type("User", (), {})()
    user.id = owner_id
    user.username = "owner"

    async def allow_create(*_args, **_kwargs):
        return None

    monkeypatch.setattr(local_projects_api, "ensure_project_permission", allow_create)
    app = FastAPI()
    app.include_router(local_projects_api.router, prefix="/api/v1/adlc")
    app.dependency_overrides[get_current_active_user] = lambda: user
    # Match the production session maker, which disables expire-on-commit.
    app.dependency_overrides[injectable_session_scope] = lambda: AsyncSession(engine, expire_on_commit=False)
    return app


async def test_reopening_folder_with_orphan_registration_heals_and_reopens(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ADLC_LOCAL_PROJECT_ROOTS", str(tmp_path))
    engine = await _engine(tmp_path)
    owner_id = uuid4()
    source = _committed_repository(tmp_path)
    # A deleted project folder left its registration row behind: the folder
    # table has no row for this project_id (SQLite does not enforce the
    # foreign-key CASCADE), so the unique (owner_id, source_path) row is
    # orphaned and reopening the same folder used to fail.
    async with AsyncSession(engine) as session:
        session.add(AdlcLocalProject(project_id=uuid4(), owner_id=str(owner_id), source_path=str(source)))
        await session.commit()

    app = _app(engine, owner_id, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            created = await client.post("/api/v1/adlc/local-projects", json={"source_path": str(source)})
            assert created.status_code == status.HTTP_201_CREATED
            body = created.json()
            assert body["ready"] is True
            assert body["base_commit"] is not None

            reopened = await client.post("/api/v1/adlc/local-projects", json={"source_path": str(source)})
            assert reopened.status_code == status.HTTP_201_CREATED
            assert reopened.json()["project_id"] == body["project_id"]
    finally:
        await engine.dispose()

    async with AsyncSession(engine) as session:
        registrations = (await session.exec(select(AdlcLocalProject))).all()
        folders = (await session.exec(select(Folder))).all()
    assert len(registrations) == 1
    assert UUID(body["project_id"]) == registrations[0].project_id
    assert [folder.id for folder in folders] == [registrations[0].project_id]
