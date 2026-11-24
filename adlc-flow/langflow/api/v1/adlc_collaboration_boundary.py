"""Legacy owner routes cannot serve or mutate project-bound snapshots."""

from uuid import UUID

from fastapi import HTTPException, Request
from sqlmodel import col, select

from langflow.api.utils import DbSession
from langflow.services.database.models.auth.collaboration import AdlcProjectResource


async def legacy_collaboration_boundary(request: Request, session: DbSession):
    path = request.url.path
    if "/adlc/" not in path or "/adlc/collaboration/" in path:
        return
    identities = []
    for value in request.path_params.values():
        try:
            identities.append(UUID(str(value)))
        except (ValueError, TypeError):
            continue
    if not identities:
        return
    bound = (
        await session.exec(select(AdlcProjectResource.id).where(col(AdlcProjectResource.id).in_(identities)).limit(1))
    ).first()
    if bound is not None:
        # No hint about another project's existence or original owner.
        raise HTTPException(status_code=404, detail="Not found")
