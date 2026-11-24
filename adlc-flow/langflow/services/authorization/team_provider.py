"""Enforced project boundary on the existing authorization service port."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import update
from sqlmodel import select

from langflow.services.authorization.service import LangflowAuthorizationService
from langflow.services.authorization.team_access import (
    TeamAccessError,
    add_audit,
    ensure_administrable,
    load_policy,
    member_roles,
    policy_from,
    resource_project,
    validate_presets,
)
from langflow.services.authorization.team_catalog import VERSION, decide
from langflow.services.database.models.auth import AuthzRoleAssignment
from langflow.services.database.models.auth.collaboration import AdlcProjectResource
from langflow.services.database.models.auth.team_access import AdlcProjectAccess
from langflow.services.database.models.folder.model import Folder
from langflow.services.database.models.user.model import User
from langflow.services.deps import session_scope
from lfx.services.authorization import AuthorizationMutationKind, AuthorizationMutationRejected

# Set only by verified host startup; never derived from a client/header/env flag.
_provider_required = False


@dataclass(frozen=True)
class TeamDecision:
    allowed: bool
    reason: str
    revision: int


class TeamAuthorizationService(LangflowAuthorizationService):
    """Legacy private behavior outside managed projects; mandatory policy inside."""

    TEAM_POLICY_VERSION = VERSION
    COLLABORATION_PROTOCOL_VERSION = "0.1"
    # Shared content is fetched through the actor-aware collaboration API;
    # the legacy global cross-user capability remains disabled.
    SUPPORTS_CROSS_USER_FETCH = False

    async def _managed_scope(self, session, project_id):
        visited = set()
        while project_id is not None:
            max_scope_depth = 64
            if project_id in visited or len(visited) >= max_scope_depth:
                code = "TEAM_RESOURCE_SCOPE_INVALID"
                raise TeamAccessError(code)
            visited.add(project_id)
            policy = await session.get(AdlcProjectAccess, project_id)
            if policy is not None:
                return project_id
            project = await session.get(Folder, project_id)
            project_id = project.parent_id if project else None
        return None

    async def _affected_projects(self, session, user_ids):
        return (
            await session.exec(
                select(AdlcProjectAccess.project_id)
                .join(
                    AuthzRoleAssignment,
                    AuthzRoleAssignment.domain_id == AdlcProjectAccess.project_id,
                )
                .where(AuthzRoleAssignment.domain_type == "project", AuthzRoleAssignment.user_id.in_(user_ids))
                .distinct()
                .order_by(AdlcProjectAccess.project_id)
            )
        ).all()

    async def acquire_identity_mutation_lock(self, *, session, kind, affected_user_ids=(), **_kwargs):
        if kind in {AuthorizationMutationKind.USER_DISABLED, AuthorizationMutationKind.USER_DELETED}:
            for project_id in await self._affected_projects(session, affected_user_ids):
                await session.exec(
                    update(AdlcProjectAccess)
                    .where(AdlcProjectAccess.project_id == project_id)
                    .values(revision=AdlcProjectAccess.revision)
                )

    async def validate_identity_mutation(self, *, session, mutation):
        if mutation.kind not in {AuthorizationMutationKind.USER_DISABLED, AuthorizationMutationKind.USER_DELETED}:
            return
        projects = await self._affected_projects(session, mutation.affected_user_ids)
        # Deleting a user may cascade the assignments before the staging hook.
        # Keep only transaction-local scope, never cached authorization decisions.
        key = (mutation.kind.value, tuple(sorted(str(value) for value in mutation.affected_user_ids)))
        session.info.setdefault("team_identity_projects", {})[key] = projects
        for project_id in projects:
            row = await load_policy(session, project_id)
            try:
                await ensure_administrable(session, row, mutation.affected_user_ids)
            except TeamAccessError as exc:
                raise AuthorizationMutationRejected(exc.code) from None

    async def stage_identity_mutation(self, *, session, event):
        if event.kind not in {AuthorizationMutationKind.USER_DISABLED, AuthorizationMutationKind.USER_DELETED}:
            return
        key = (event.kind.value, tuple(sorted(str(value) for value in event.affected_user_ids)))
        projects = set(session.info.get("team_identity_projects", {}).pop(key, ()))
        projects.update(await self._affected_projects(session, event.affected_user_ids))
        for project_id in sorted(projects):
            await session.exec(
                update(AdlcProjectAccess)
                .where(AdlcProjectAccess.project_id == project_id)
                .values(revision=AdlcProjectAccess.revision + 1)
            )
            row = await load_policy(session, project_id)
            add_audit(
                session,
                event.actor_user_id,
                project_id,
                row.revision,
                "identity_revoked",
                {"subjects": [str(value) for value in event.affected_user_ids], "kind": event.kind.value},
            )

    async def enforce_team(self, *, user_id, domain, obj, act, context=None):
        async with session_scope() as session:
            project_id = await resource_project(session, obj, domain, context)
            project_id = await self._managed_scope(session, project_id)
            if project_id is None:
                return None
            row = await load_policy(session, project_id)
            user = await session.get(User, user_id)
            if user is None or not user.is_active:
                return TeamDecision(allowed=False, reason="TEAM_ACTIVE_USER_REQUIRED", revision=row.revision)
            if (context or {}).get("auth_method") != "jwt":
                return TeamDecision(allowed=False, reason="TEAM_EXPLICIT_LOGIN_REQUIRED", revision=row.revision)
            if row.mode == "COLLABORATION" and obj.startswith("flow:") and act != "read":
                # Legacy write/materialize routes have no revision/delegation contract.
                return TeamDecision(allowed=False, reason="TEAM_USE_COLLABORATION_API", revision=row.revision)
            roles = await member_roles(session, project_id, user_id)
            policy = policy_from(row)
            project_allowed, reason = decide(policy, roles, "project:read")
            allowed, reason = (
                decide(policy, roles, f"{obj.split(':', 1)[0]}:{act}", collaboration=row.mode == "COLLABORATION")
                if project_allowed
                else (False, reason)
            )
            if allowed and row.mode == "COLLABORATION" and obj.startswith("flow:"):
                # The graph embeds contract content. Legacy read routes and list
                # filters must respect the same dependency closure as the team API.
                from langflow.adlc.collaboration import readable

                try:
                    identity = UUID(obj.split(":", 1)[1])
                except ValueError:
                    return TeamDecision(allowed=False, reason="TEAM_USE_COLLABORATION_API", revision=row.revision)
                binding = await session.get(AdlcProjectResource, identity)
                if binding is None or binding.project_id != project_id or binding.kind != "WORKFLOW":
                    return TeamDecision(allowed=False, reason="TEAM_RESOURCE_SCOPE_INVALID", revision=row.revision)
                try:
                    await readable(session, binding, row, user_id)
                except TeamAccessError as exc:
                    if exc.status not in {403, 404}:
                        raise
                    return TeamDecision(allowed=False, reason=exc.code, revision=row.revision)
            return TeamDecision(allowed, reason, row.revision)

    async def enforce(self, **request):
        decision = await self.enforce_team(**request)
        return decision.allowed if decision is not None else await super().enforce(**request)

    async def batch_enforce(self, *, requests, **request):
        return [await self.enforce(obj=obj, act=act, **request) for obj, act in requests]

    async def is_team_resource(self, *, obj, domain="*", context=None):
        async with session_scope() as session:
            project_id = await resource_project(session, obj, domain, context)
            return await self._managed_scope(session, project_id) is not None


async def assert_team_access_ready(provider=None):
    """Run after migrations and plugin registration, before accepting requests."""
    global _provider_required  # noqa: PLW0603 - process startup invariant, not a client-controlled flag.

    from langflow.services.deps import get_authorization_service

    provider = provider if provider is not None else get_authorization_service()
    async with session_scope() as session:
        has_projects = (await session.exec(select(AdlcProjectAccess.project_id).limit(1))).first() is not None
        has_collaboration = (
            await session.exec(
                select(AdlcProjectAccess.project_id).where(AdlcProjectAccess.mode == "COLLABORATION").limit(1)
            )
        ).first() is not None
        ready = getattr(provider, "TEAM_POLICY_VERSION", None) == VERSION
        if has_projects and not ready:
            msg = "TEAM_ENFORCEMENT_PROVIDER_REQUIRED"
            raise TeamAccessError(msg, 503)
        if has_collaboration and getattr(provider, "COLLABORATION_PROTOCOL_VERSION", None) != "0.1":
            msg = "TEAM_COLLABORATION_PROVIDER_REQUIRED"
            raise TeamAccessError(msg, 503)
        if ready:
            await validate_presets(session)
        _provider_required = ready or has_projects


def team_listing_requires_filter(provider):
    """Legacy owner-unioned SQL scopes cannot represent mandatory project denies."""
    return _provider_required or getattr(provider, "TEAM_POLICY_VERSION", None) == VERSION


async def guard_team(user, *, domain, obj, act, context, provider=None):
    """A mandatory decision precedes AUTHZ_ENABLED and owner overrides."""
    from langflow.services.deps import get_authorization_service

    provider = provider if provider is not None else get_authorization_service()
    if getattr(provider, "TEAM_POLICY_VERSION", None) != VERSION:
        if _provider_required:
            msg = "TEAM_ENFORCEMENT_PROVIDER_REQUIRED"
            raise TeamAccessError(msg, 503)
        return None
    try:
        return await provider.enforce_team(user_id=user.id, domain=domain, obj=obj, act=act, context=context)
    except TeamAccessError:
        raise
    except Exception as exc:
        msg = "TEAM_POLICY_STORE_UNAVAILABLE"
        raise TeamAccessError(msg, 503) from exc
