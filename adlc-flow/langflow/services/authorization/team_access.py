"""H7A durable policy evaluation and transactional administration.

No policy cache: every decision reads committed project rules and canonical
assignments. Revocation is therefore visible across workers without pub/sub.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from langflow.services.authorization.team_catalog import (
    ACTION_CATALOG,
    ADMIN_REQUIRED,
    ROLE_LABELS,
    VERSION,
    TeamPolicy,
    TeamRole,
    decide,
    default_policy,
    role_id,
    role_name,
)
from langflow.services.database.models.auth import (
    AuthzAuditLog,
    AuthzRole,
    AuthzRoleAssignment,
    AuthzRoleAssignmentGrant,
)
from langflow.services.database.models.auth.team_access import AdlcProjectAccess
from langflow.services.database.models.flow.model import Flow
from langflow.services.database.models.folder.model import Folder
from langflow.services.database.models.user.model import User


class TeamAccessError(Exception):
    def __init__(self, code: str, status: int = 403):
        super().__init__(code)
        self.code, self.status = code, status


class RevisionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class PolicyCommand(RevisionCommand):
    policy: TeamPolicy


class MemberCommand(RevisionCommand):
    username: str = Field(min_length=1, max_length=128)
    roles: list[TeamRole] = Field(min_length=1, max_length=4)


async def validate_presets(session: AsyncSession) -> None:
    rows = (
        await session.exec(select(AuthzRole).where(col(AuthzRole.id).in_([role_id(role) for role in TeamRole])))
    ).all()
    expected = {role_id(role): role for role in TeamRole}
    if len(rows) != len(TeamRole) or any(
        row.name != role_name(expected[row.id]) or not row.is_system or row.parent_role_id is not None for row in rows
    ):
        msg = "TEAM_PRESETS_NOT_READY"
        raise TeamAccessError(msg, 503)


def policy_from(row: AdlcProjectAccess) -> TeamPolicy:
    try:
        if row.schema_version != VERSION or row.mode not in {"CONFIGURATION_ONLY", "COLLABORATION"}:
            msg = "Unknown policy format"
            raise ValueError(msg)
        return TeamPolicy.model_validate(row.role_rules)
    except (TypeError, ValueError) as exc:
        msg = "TEAM_POLICY_STORE_INVALID"
        raise TeamAccessError(msg, 503) from exc


async def member_rows(session: AsyncSession, project_id: UUID):
    return (
        await session.exec(
            select(AuthzRoleAssignment, User.username, User.is_active)
            .join(User, User.id == AuthzRoleAssignment.user_id)
            .join(AuthzRoleAssignmentGrant, AuthzRoleAssignmentGrant.assignment_id == AuthzRoleAssignment.id)
            .where(
                AuthzRoleAssignment.domain_type == "project",
                AuthzRoleAssignment.domain_id == project_id,
                col(AuthzRoleAssignment.role_id).in_([role_id(role) for role in TeamRole]),
                AuthzRoleAssignmentGrant.source_kind == "manual",
            )
            .order_by(User.username, AuthzRoleAssignment.role_id)
        )
    ).all()


async def member_roles(session: AsyncSession, project_id: UUID, user_id: UUID) -> set[TeamRole]:
    lookup = {role_id(role): role for role in TeamRole}
    return {
        lookup[assignment.role_id]
        for assignment, _, active in await member_rows(session, project_id)
        if assignment.user_id == user_id and active
    }


async def load_policy(session: AsyncSession, project_id: UUID) -> AdlcProjectAccess:
    row = await session.get(AdlcProjectAccess, project_id, populate_existing=True)
    if row is None:
        msg = "TEAM_PROJECT_NOT_FOUND"
        raise TeamAccessError(msg, 404)
    policy_from(row)
    return row


async def require_permission(session: AsyncSession, project_id: UUID, user: User, action: str) -> AdlcProjectAccess:
    row = await load_policy(session, project_id)
    roles = await member_roles(session, project_id, user.id)
    policy = policy_from(row)
    project_allowed, project_code = decide(policy, roles, "project:read")
    allowed, code = (
        decide(policy, roles, action, collaboration=row.mode == "COLLABORATION")
        if project_allowed
        else (False, project_code)
    )
    if not allowed:
        raise TeamAccessError(code, 404 if not roles else 403)
    return row


def add_audit(session, user_id, project_id, revision, event, details):
    # Same transaction as the protected mutation, never optional/best-effort.
    session.add(
        AuthzAuditLog(
            user_id=user_id,
            actor_type="USER",
            actor_id=user_id,
            action=f"team_access:{event}",
            resource_type="project",
            resource_id=project_id,
            result="allow",
            details={"policy_revision": revision, **details},
        )
    )


async def lock_revision(session, project_id, user, expected_revision, permission):
    await require_permission(session, project_id, user, permission)
    result = await session.exec(
        update(AdlcProjectAccess)
        .where(
            AdlcProjectAccess.project_id == project_id,
            AdlcProjectAccess.revision == expected_revision,
        )
        .values(revision=expected_revision + 1, updated_at=datetime.now(timezone.utc))
    )
    if result.rowcount != 1:
        msg = "TEAM_POLICY_REVISION_CONFLICT"
        raise TeamAccessError(msg, 409)
    # Re-evaluate under the write lock. This also serializes last-admin checks.
    return await require_permission(session, project_id, user, permission)


async def create_project(session: AsyncSession, user: User, name: str) -> UUID:
    user = await session.get(User, user.id, populate_existing=True, with_for_update=True)
    if user is None:
        code = "TEAM_BOOTSTRAP_OPERATOR_REQUIRED"
        raise TeamAccessError(code)
    if not user.is_active or not user.is_superuser:
        msg = "TEAM_BOOTSTRAP_OPERATOR_REQUIRED"
        raise TeamAccessError(msg)
    name = name.strip()
    min_name_length, max_name_length = 2, 80
    if not min_name_length <= len(name) <= max_name_length:
        msg = "TEAM_PROJECT_NAME_INVALID"
        raise TeamAccessError(msg, 422)
    await validate_presets(session)
    project_id = uuid4()
    session.add(Folder(id=project_id, name=name, user_id=user.id))
    await session.flush()
    session.add(
        AdlcProjectAccess(
            project_id=project_id, created_by=user.id, role_rules=default_policy().model_dump(mode="json")
        )
    )
    assignment = AuthzRoleAssignment(
        user_id=user.id,
        role_id=role_id(TeamRole.ADMIN),
        domain_type="project",
        domain_id=project_id,
        assigned_by=user.id,
    )
    session.add(assignment)
    await session.flush()
    session.add(
        AuthzRoleAssignmentGrant(assignment_id=assignment.id, source_kind="manual", administrative_actor=user.id)
    )
    add_audit(
        session,
        user.id,
        project_id,
        1,
        "project_created",
        {"mode": "CONFIGURATION_ONLY", "bootstrap_user_id": str(user.id)},
    )
    return project_id


async def visible_projects(session, user):
    assignments = select(AuthzRoleAssignment.domain_id).where(
        AuthzRoleAssignment.user_id == user.id,
        AuthzRoleAssignment.domain_type == "project",
        col(AuthzRoleAssignment.role_id).in_([role_id(role) for role in TeamRole]),
    )
    rows = (
        await session.exec(
            select(AdlcProjectAccess, Folder.name)
            .join(Folder, Folder.id == AdlcProjectAccess.project_id)
            .where(col(AdlcProjectAccess.project_id).in_(assignments))
            .order_by(Folder.name, AdlcProjectAccess.project_id)
        )
    ).all()
    result = []
    for row, name in rows:
        roles = await member_roles(session, row.project_id, user.id)
        if decide(policy_from(row), roles, "project:read")[0]:
            result.append(
                {
                    "project_id": row.project_id,
                    "name": name,
                    "revision": row.revision,
                    "roles": sorted(role.value for role in roles),
                    "mode": row.mode,
                }
            )
    return result


async def effective(session, row, subject_id):
    roles = await member_roles(session, row.project_id, subject_id)
    if not roles:
        msg = "TEAM_MEMBER_NOT_FOUND"
        raise TeamAccessError(msg, 404)
    policy = policy_from(row)
    project_allowed, project_reason = decide(policy, roles, "project:read")
    return {
        "user_id": subject_id,
        "roles": sorted(role.value for role in roles),
        "revision": row.revision,
        "permissions": {
            action.key: {
                "allowed": project_allowed
                and decide(policy, roles, action.key, collaboration=row.mode == "COLLABORATION")[0],
                "reason": decide(policy, roles, action.key, collaboration=row.mode == "COLLABORATION")[1]
                if project_allowed
                else project_reason,
                "granted": any(action.key in policy.roles[role].allow for role in roles),
                "phase": action.phase,
            }
            for action in ACTION_CATALOG
        },
    }


async def project_view(session, project_id, user):
    row = await require_permission(session, project_id, user, "policy:read")
    own = await effective(session, row, user.id)
    manage = own["permissions"]["policy:manage"]["allowed"]
    members = {}
    if manage:
        lookup = {role_id(role): role for role in TeamRole}
        for assignment, username, active in await member_rows(session, project_id):
            member = members.setdefault(
                str(assignment.user_id),
                {"user_id": assignment.user_id, "username": username, "is_active": active, "roles": []},
            )
            member["roles"].append(lookup[assignment.role_id].value)
    folder = await session.get(Folder, project_id)
    return {
        "project_id": project_id,
        "name": folder.name,
        "revision": row.revision,
        "mode": row.mode,
        "can_manage": manage,
        "effective": own,
        "policy": row.role_rules if manage else None,
        "members": list(members.values()),
        "catalog": [action.model_dump() for action in ACTION_CATALOG],
        "roles": [{"id": role.value, "name": label} for role, label in ROLE_LABELS.items()],
    }


async def update_policy(session, project_id, user, command: PolicyCommand):
    row = await lock_revision(session, project_id, user, command.expected_revision, "policy:manage")
    previous = row.role_rules
    row.role_rules = command.policy.model_dump(mode="json")
    session.add(row)
    await ensure_administrable(session, row)
    add_audit(
        session, user.id, project_id, row.revision, "policy_updated", {"before": previous, "after": row.role_rules}
    )


async def set_member(session, project_id, user, command: MemberCommand):
    row = await lock_revision(session, project_id, user, command.expected_revision, "membership:manage")
    target = (await session.exec(select(User).where(User.username == command.username))).first()
    if target is None or not target.is_active:
        msg = "TEAM_ACTIVE_USER_NOT_FOUND"
        raise TeamAccessError(msg, 404)
    await replace_roles(session, row, user, target.id, set(command.roles))


async def replace_roles(session, row, user, subject_id, new_roles):
    entries = await member_rows(session, row.project_id)
    current = [assignment for assignment, _, _ in entries if assignment.user_id == subject_id]
    before = {role for role in TeamRole if any(assignment.role_id == role_id(role) for assignment in current)}
    if TeamRole.ADMIN in before and TeamRole.ADMIN not in new_roles:
        other_admins = {
            assignment.user_id
            for assignment, _, active in entries
            if active and assignment.role_id == role_id(TeamRole.ADMIN) and assignment.user_id != subject_id
        }
        if not other_admins:
            msg = "TEAM_LAST_ADMIN_PROTECTED"
            raise TeamAccessError(msg, 409)
    for assignment in current:
        if assignment.role_id not in {role_id(role) for role in new_roles}:
            # ADLC roles reject external provenance, so revocation is not lossy.
            other = (
                await session.exec(
                    select(AuthzRoleAssignmentGrant).where(
                        AuthzRoleAssignmentGrant.assignment_id == assignment.id,
                        AuthzRoleAssignmentGrant.source_kind != "manual",
                    )
                )
            ).first()
            if other:
                msg = "TEAM_NON_MANUAL_GRANT_REQUIRES_RECONCILIATION"
                raise TeamAccessError(msg, 409)
            await session.delete(assignment)
    for role in new_roles - before:
        assignment = AuthzRoleAssignment(
            user_id=subject_id,
            role_id=role_id(role),
            domain_type="project",
            domain_id=row.project_id,
            assigned_by=user.id,
        )
        session.add(assignment)
        await session.flush()
        session.add(
            AuthzRoleAssignmentGrant(assignment_id=assignment.id, source_kind="manual", administrative_actor=user.id)
        )
    await session.flush()
    await ensure_administrable(session, row)
    add_audit(
        session,
        user.id,
        row.project_id,
        row.revision,
        "member_updated",
        {
            "subject_id": str(subject_id),
            "before": sorted(role.value for role in before),
            "after": sorted(role.value for role in new_roles),
        },
    )


async def remove_member(session, project_id, user, subject_id, command: RevisionCommand):
    row = await lock_revision(session, project_id, user, command.expected_revision, "membership:manage")
    if not any(assignment.user_id == subject_id for assignment, _, _ in await member_rows(session, project_id)):
        msg = "TEAM_MEMBER_NOT_FOUND"
        raise TeamAccessError(msg, 404)
    await replace_roles(session, row, user, subject_id, set())


async def ensure_administrable(session, row, exclude_users=()):
    active_roles = {}
    lookup = {role_id(role): role for role in TeamRole}
    for assignment, _, active in await member_rows(session, row.project_id):
        if active and assignment.user_id not in exclude_users:
            active_roles.setdefault(assignment.user_id, set()).add(lookup[assignment.role_id])
    policy = policy_from(row)
    if not any(
        TeamRole.ADMIN in roles and all(decide(policy, roles, key)[0] for key in ADMIN_REQUIRED)
        for roles in active_roles.values()
    ):
        code = "TEAM_LAST_ADMIN_PROTECTED"
        raise TeamAccessError(code, 409)


async def commit(session):
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        msg = "TEAM_WRITE_CONFLICT"
        raise TeamAccessError(msg, 409) from exc


async def resource_project(session, obj: str, domain: str, context: dict | None):
    kind, _, identity = obj.partition(":")
    try:
        if kind == "project" and identity != "*":
            return UUID(identity)
        if kind == "flow" and identity != "*":
            flow = await session.get(Flow, UUID(identity))
            if flow is not None:
                return flow.folder_id
        # CREATE has no object id; route guards supply the fetched parent scope.
        if kind in {"flow", "deployment", "knowledge_base", "project"}:
            scope = (context or {}).get("folder_id") or (context or {}).get("project_id")
            if scope:
                return UUID(str(scope))
            if domain.startswith("project:"):
                return UUID(domain[8:])
    except (TypeError, ValueError) as exc:
        msg = "TEAM_RESOURCE_SCOPE_INVALID"
        raise TeamAccessError(msg) from exc
    return None
