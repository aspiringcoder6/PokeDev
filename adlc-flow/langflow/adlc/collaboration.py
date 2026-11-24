"""Project collaboration on canonical ADLC documents, plans and run snapshots.

All writes serialize with policy changes and append audit in the same transaction.
No scheduler, shell, model, Verify worker or publisher is called by this module.
"""

from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import ValidationError
from sqlalchemy import update
from sqlmodel import select

from langflow.adlc.blueprints.canonicalization import canonical_json_bytes, sha256_digest
from langflow.adlc.blueprints.models import ExecutionPlan, PlanStatus, PlanValidationStatus, WorkflowDefinition
from langflow.adlc.contract_models import (
    TOOL_ARGUMENT_MODELS,
    InitArguments,
    SkilltreeDocument,
    StatusArguments,
    ValidateArguments,
)
from langflow.adlc.contract_repository import ContractError, ContractRepository
from langflow.adlc.contract_validation import structural_issues, validate_document
from langflow.adlc.models import (
    Actor,
    RunEvent,
    TaskRun,
    TaskRunStatus,
    WorkflowExecutionMode,
    WorkflowRun,
    WorkflowRunStatus,
)
from langflow.adlc.planning.materializer import materialize_task_definitions
from langflow.services.authorization import team_access as access
from langflow.services.authorization.team_catalog import decide
from langflow.services.database.models.adlc_execution_plan import AdlcExecutionPlan
from langflow.services.database.models.adlc_workflow_run import AdlcWorkflowRun
from langflow.services.database.models.auth.collaboration import (
    AdlcProjectCommand,
    AdlcProjectDecision,
    AdlcProjectResource,
    AdlcProjectRevision,
)
from langflow.services.database.models.auth.team_access import AdlcProjectAccess
from langflow.services.database.models.flow.model import Flow
from langflow.services.database.models.folder.model import Folder

READ_ACTION = {
    "CONTRACT": "requirement:read",
    "WORKFLOW": "flow:read",
    "PLAN": "flow:read",
    "RUN": "run:read",
    "ARTIFACT": "run:read",
    "CANDIDATE": "run:read",
    "VERIFICATION": "verification:read",
    "TEST_SUITE": "verification:read",
}
GATE_ACTION = {
    "CONTRACT": "contract:approve",
    "PLAN": "plan:approve",
    "CANDIDATE": "candidate:review",
    "VERIFICATION": "verification:accept",
}
WRITE_ACTION = {"CONTRACT": "requirement:write", "WORKFLOW": "flow:write", "TEST_SUITE": "test_suite:write"}
MAX_PAYLOAD_BYTES = 1024 * 1024
MAX_PROJECT_RESOURCES = 1000
MAX_REVISIONS = 512
MAX_DEPENDENCY_DEPTH = 64
FORBIDDEN = 403


def now():
    return datetime.now(timezone.utc)


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def fail(code, status=409):
    raise access.TeamAccessError(code, status)


def reference(resource):
    return {"resource_id": str(resource.id), "revision": resource.revision, "content_digest": resource.content_digest}


async def policy(session, project_id, actor, action, *, expected=None, lock=False):
    row = await access.require_permission(session, project_id, actor, action)
    if expected is not None and row.revision != expected:
        fail("TEAM_POLICY_REVISION_CONFLICT")
    if lock:
        result = await session.exec(
            update(AdlcProjectAccess)
            .where(
                AdlcProjectAccess.project_id == project_id,
                AdlcProjectAccess.revision == expected,
            )
            .values(revision=AdlcProjectAccess.revision)
        )
        if result.rowcount != 1:
            fail("TEAM_POLICY_REVISION_CONFLICT")
        row = await access.require_permission(session, project_id, actor, action)
    if row.mode != "COLLABORATION":
        fail("TEAM_COLLABORATION_NOT_ENABLED", 403)
    companion = {
        "requirement:write": "requirement:read",
        "contract:submit": "requirement:read",
        "flow:create": "flow:read",
        "flow:write": "flow:read",
        "plan:approve": "flow:read",
        "test_suite:write": "verification:read",
        "verification:accept": "verification:read",
        "candidate:review": "run:read",
    }.get(action)
    if companion:
        await access.require_permission(session, project_id, actor, companion)
    return row


async def enable(session, project_id, actor, command):
    row = await access.lock_revision(session, project_id, actor, command.policy_revision, "policy:manage")
    if row.mode != "CONFIGURATION_ONLY":
        fail("TEAM_COLLABORATION_ALREADY_ENABLED")
    for model in (AdlcProjectResource, AdlcProjectRevision, AdlcProjectDecision, AdlcProjectCommand):
        await session.exec(select(model).limit(1))  # Refuse activation before the complete migration.
    # Old folders/data must never become shared merely by toggling a setting.
    if (await session.exec(select(Flow.id).where(Flow.folder_id == project_id).limit(1))).first() or (
        await session.exec(select(Folder.id).where(Folder.parent_id == project_id).limit(1))
    ).first():
        fail("TEAM_COLLABORATION_REQUIRES_EMPTY_PROJECT")
    row.mode = "COLLABORATION"
    session.add(row)
    access.add_audit(session, actor.id, project_id, row.revision, "collaboration_enabled", {})
    return {"mode": row.mode, "revision": row.revision}


async def resource(session, project_id, resource_id, *, kind=None):
    resource_id = UUID(str(resource_id))
    row = await session.get(AdlcProjectResource, resource_id, populate_existing=True)
    if row is None or row.project_id != project_id or (kind is not None and row.kind != kind):
        fail("TEAM_RESOURCE_NOT_FOUND", 404)
    if row.kind not in READ_ACTION:
        fail("TEAM_RESOURCE_STORE_INVALID", 503)
    return row


def exact(row, command):
    if row.revision != command.expected_revision or row.content_digest != command.content_digest:
        fail("TEAM_RESOURCE_REVISION_CONFLICT")


async def snapshot(session, row, revision=None):
    revision = revision or row.revision
    stored = await session.get(AdlcProjectRevision, (row.id, revision))
    if stored is None or sha256_digest(stored.payload) != stored.content_digest:
        fail("TEAM_RESOURCE_STORE_INVALID", 503)
    if revision == row.revision and stored.content_digest != row.content_digest:
        fail("TEAM_RESOURCE_STORE_INVALID", 503)
    return stored.payload


def bounded(payload):
    if len(canonical_json_bytes(payload)) > MAX_PAYLOAD_BYTES:
        fail("TEAM_RESOURCE_TOO_LARGE", 413)
    return sha256_digest(payload)


async def append_revision(session, row, actor, payload, *, initial=False):
    digest = bounded(payload)
    if not initial:
        row.revision += 1
    if row.revision > MAX_REVISIONS:
        fail("TEAM_RESOURCE_REVISION_LIMIT", 413)
    row.content_digest, row.updated_at = digest, now()
    row.responsible_ids = sorted(set(row.responsible_ids) | {str(actor.id)})
    session.add(row)
    await session.flush()
    session.add(
        AdlcProjectRevision(
            resource_id=row.id, revision=row.revision, content_digest=digest, payload=payload, authored_by=actor.id
        )
    )
    await session.flush()


async def create_resource(
    session,
    project_id,
    actor,
    kind,
    title,
    payload,
    *,
    identity=None,
    parent=None,
    dependencies=None,
    responsible=None,
    origin=None,
    status="DRAFT",
    initial_revision=1,
):
    count = len(
        (
            await session.exec(
                select(AdlcProjectResource.id)
                .where(AdlcProjectResource.project_id == project_id)
                .limit(MAX_PROJECT_RESOURCES)
            )
        ).all()
    )
    if count >= MAX_PROJECT_RESOURCES:
        fail("TEAM_PROJECT_RESOURCE_LIMIT", 413)
    row = AdlcProjectResource(
        id=identity or uuid4(),
        project_id=project_id,
        kind=kind,
        title=title,
        parent_id=parent,
        created_by=actor.id,
        origin_owner_id=origin or str(actor.id),
        responsible_ids=responsible or [str(actor.id)],
        revision=initial_revision,
        content_digest="",
        status=status,
        dependencies=dependencies or {},
    )
    await append_revision(session, row, actor, payload, initial=True)
    return row


def audit(session, actor, row, policy_revision, event):
    access.add_audit(
        session,
        actor.id,
        row.project_id,
        policy_revision,
        f"collaboration_{event}",
        {
            "resource_id": str(row.id),
            "kind": row.kind,
            "resource_revision": row.revision,
            "content_digest": row.content_digest,
        },
    )


async def approval(session, row, policy_row):
    record = (
        await session.exec(
            select(AdlcProjectDecision).where(
                AdlcProjectDecision.resource_id == row.id,
                AdlcProjectDecision.resource_revision == row.revision,
            )
        )
    ).first()
    if (
        row.status != "APPROVED"
        or record is None
        or record.decision != "APPROVE"
        or record.content_digest != row.content_digest
        or record.policy_revision != policy_row.revision
        or aware(record.expires_at) <= now()
        or record.dependencies != row.dependencies
    ):
        fail("TEAM_CURRENT_APPROVAL_REQUIRED")
    # A previously valid signature does not retain a revoked grant.
    roles = await access.member_roles(session, row.project_id, record.decided_by)
    rules = access.policy_from(policy_row)
    if (
        str(record.decided_by) in row.responsible_ids
        or not decide(rules, roles, "project:read")[0]
        or not decide(rules, roles, record.action, collaboration=True)[0]
    ):
        fail("TEAM_CURRENT_APPROVAL_REQUIRED")
    return record


async def dependencies_current(session, row, policy_row):
    for value in row.dependencies.values():
        other = await resource(session, row.project_id, UUID(value["resource_id"]))
        if reference(other) != value:
            fail("TEAM_DEPENDENCY_CHANGED")
        if other.kind == "CONTRACT":
            await approval(session, other, policy_row)


async def dependency_actions(session, row, visited=None):
    visited = set() if visited is None else visited
    if row.id in visited:
        return set()
    if len(visited) >= MAX_DEPENDENCY_DEPTH:
        fail("TEAM_RESOURCE_SCOPE_INVALID", 503)
    visited.add(row.id)
    actions = {READ_ACTION[row.kind]}
    for value in row.dependencies.values():
        source = await resource(session, row.project_id, UUID(value["resource_id"]))
        actions.update(await dependency_actions(session, source, visited))
    return actions


async def readable(session, row, policy_row, actor_id):
    roles = await access.member_roles(session, row.project_id, actor_id)
    rules = access.policy_from(policy_row)
    if not all(
        decide(rules, roles, action, collaboration=True)[0] for action in await dependency_actions(session, row)
    ):
        fail("TEAM_PERMISSION_DENIED", 403)


async def reviewers(session, row, policy_row):
    action = GATE_ACTION.get(row.kind)
    if action is None:
        return []
    members = {}
    for assignment, username, active in await access.member_rows(session, row.project_id):
        if active and str(assignment.user_id) not in row.responsible_ids:
            members[assignment.user_id] = username
    rules = access.policy_from(policy_row)
    read_actions = await dependency_actions(session, row)
    result = []
    for user_id, username in members.items():
        roles = await access.member_roles(session, row.project_id, user_id)
        if (
            decide(rules, roles, "project:read")[0]
            and decide(rules, roles, action, collaboration=True)[0]
            and all(decide(rules, roles, key, collaboration=True)[0] for key in read_actions)
        ):
            result.append({"user_id": str(user_id), "username": username})
    return result


async def view(session, project_id, resource_id, actor, *, revision=None):
    await policy(session, project_id, actor, "project:read")
    row = await resource(session, project_id, resource_id)
    p = await policy(session, project_id, actor, READ_ACTION[row.kind])
    await readable(session, row, p, actor.id)
    body = await snapshot(session, row, revision)
    selected_revision = revision or row.revision
    if row.kind == "RUN":
        run = WorkflowRun.model_validate(body)
        if run.id != row.id or run.project_id != project_id:
            fail("TEAM_RESOURCE_STORE_INVALID", 503)
    elif row.kind == "CONTRACT":
        document = SkilltreeDocument.model_validate(body)
        if document.contract_id != row.id or document.revision != selected_revision:
            fail("TEAM_RESOURCE_STORE_INVALID", 503)
    elif row.kind == "WORKFLOW":
        workflow = WorkflowDefinition.model_validate(body)
        if (
            workflow.workflow_definition_id != row.id
            or workflow.project_id != project_id
            or workflow.version != selected_revision
        ):
            fail("TEAM_RESOURCE_STORE_INVALID", 503)
    elif row.kind == "PLAN" and ExecutionPlan.model_validate(body).execution_plan_id != row.id:
        fail("TEAM_RESOURCE_STORE_INVALID", 503)
    stale = False
    try:
        await dependencies_current(session, row, p)
    except access.TeamAccessError:
        stale = True
    eligible = await reviewers(session, row, p)
    records = (
        await session.exec(
            select(AdlcProjectDecision)
            .where(AdlcProjectDecision.resource_id == row.id)
            .order_by(AdlcProjectDecision.created_at)
        )
    ).all()
    return {
        **row.model_dump(mode="json"),
        "payload": body,
        "selected_revision": revision or row.revision,
        "policy_revision": p.revision,
        "stale_dependencies": stale,
        "reviewers": eligible,
        "can_decide": row.status == "SUBMITTED"
        and not stale
        and revision in {None, row.revision}
        and any(item["user_id"] == str(actor.id) for item in eligible),
        "required_action": GATE_ACTION.get(row.kind),
        "decisions": [record.model_dump(mode="json") for record in records],
    }


async def overview(session, project_id, actor, *, limit=50, offset=0):
    p = await policy(session, project_id, actor, "project:read")
    own = await access.effective(session, p, actor.id)
    # Permission filter before pagination, including totals and pending inbox.
    stmt = select(AdlcProjectResource).where(AdlcProjectResource.project_id == project_id)
    all_rows = (await session.exec(stmt.order_by(AdlcProjectResource.updated_at.desc(), AdlcProjectResource.id))).all()
    rows = []
    for row in all_rows:
        try:
            await readable(session, row, p, actor.id)
        except access.TeamAccessError as exc:
            if exc.status == FORBIDDEN:
                continue
            raise
        rows.append(row)
    inbox = []
    for row in rows:
        if (
            row.status == "SUBMITTED"
            and GATE_ACTION.get(row.kind)
            and any(item["user_id"] == str(actor.id) for item in await reviewers(session, row, p))
        ):
            try:
                await dependencies_current(session, row, p)
            except access.TeamAccessError:
                continue
            inbox.append(reference(row) | {"title": row.title, "kind": row.kind})
    name = (await session.get(Folder, project_id)).name
    return {
        "project_id": project_id,
        "name": name,
        "mode": p.mode,
        "policy_revision": p.revision,
        "effective": own,
        "resources": [row.model_dump(mode="json") for row in rows[offset : offset + limit]],
        "total": len(rows),
        "limit": limit,
        "offset": offset,
        "inbox": inbox,
        "execution_enabled": False,
    }


async def contract_tool(session, project_id, actor, command):
    model = TOOL_ARGUMENT_MODELS[command.tool]
    try:
        args = model.model_validate(command.arguments)
    except ValidationError:
        fail("CONTRACT_ARGUMENTS_INVALID", 422)
    read_only = isinstance(args, StatusArguments)
    p = await policy(
        session,
        project_id,
        actor,
        "requirement:read" if read_only else "requirement:write",
        expected=command.policy_revision,
        lock=not read_only,
    )
    if read_only:
        return await view(session, project_id, args.contract_id, actor, revision=args.revision)
    request_digest = sha256_digest({"tool": command.tool, "arguments": args.model_dump(mode="json")})
    key = (project_id, actor.id, args.idempotency_key)
    receipt = await session.get(AdlcProjectCommand, key)
    if receipt:
        if receipt.request_digest != request_digest:
            fail("TEAM_COMMAND_KEY_CONFLICT")
        return await view(session, project_id, receipt.resource_id, actor, revision=receipt.resource_revision)
    if isinstance(args, InitArguments):
        doc = SkilltreeDocument(
            contract_id=uuid4(), revision=1, title=args.title, scope=args.scope, constraints=args.constraints
        )
        row = await create_resource(
            session, project_id, actor, "CONTRACT", doc.title, doc.model_dump(mode="json"), identity=doc.contract_id
        )
    else:
        row = await resource(session, project_id, args.contract_id, kind="CONTRACT")
        if row.status != "DRAFT":
            fail("TEAM_RESOURCE_LOCKED")
        if row.revision != args.expected_revision:
            fail("TEAM_RESOURCE_REVISION_CONFLICT")
        doc = SkilltreeDocument.model_validate(await snapshot(session, row))
        if isinstance(args, ValidateArguments):
            # Validation is a declaration check, not execution or an approval.
            report = validate_document(doc, now())
            if not report.passed:
                return {
                    **(await view(session, project_id, row.id, actor)),
                    "validation": report.model_dump(mode="json"),
                }
        else:
            try:
                doc, _node_id = ContractRepository.edit_document(doc, args)
            except ContractError as exc:
                fail(exc.code, exc.http_status)
            issues = structural_issues(doc)
            if issues:
                fail(issues[0])
            await append_revision(session, row, actor, doc.model_dump(mode="json"))
    session.add(
        AdlcProjectCommand(
            project_id=project_id,
            actor_id=actor.id,
            command_key=args.idempotency_key,
            request_digest=request_digest,
            resource_id=row.id,
            resource_revision=row.revision,
        )
    )
    audit(session, actor, row, p.revision, "contract_tool")
    await session.flush()
    return await view(session, project_id, row.id, actor)


async def submit(session, project_id, resource_id, actor, command):
    await policy(session, project_id, actor, "project:read")
    row = await resource(session, project_id, resource_id)
    action = "contract:submit" if row.kind == "CONTRACT" else "test_suite:write"
    if row.kind not in {"CONTRACT", "TEST_SUITE"}:
        fail("TEAM_OPERATION_NOT_SUPPORTED", 403)
    p = await policy(session, project_id, actor, action, expected=command.policy_revision, lock=True)
    row = await resource(session, project_id, resource_id)
    exact(row, command)
    if row.status != "DRAFT":
        fail("TEAM_RESOURCE_LOCKED")
    await dependencies_current(session, row, p)
    if row.kind == "TEST_SUITE" and "contract" not in row.dependencies:
        fail("TEAM_CURRENT_APPROVAL_REQUIRED")
    if row.kind == "CONTRACT":
        report = validate_document(SkilltreeDocument.model_validate(await snapshot(session, row)), now())
        if not report.passed:
            fail("CONTRACT_VALIDATION_REQUIRED")
        if not await reviewers(session, row, p):
            fail("TEAM_INDEPENDENT_REVIEWER_REQUIRED")
    row.status = "SUBMITTED" if row.kind == "CONTRACT" else "FROZEN"
    row.updated_at = now()
    session.add(row)
    audit(session, actor, row, p.revision, "submitted")


async def decide_resource(session, project_id, resource_id, actor, command):
    await policy(session, project_id, actor, "project:read")
    row = await resource(session, project_id, resource_id)
    action = GATE_ACTION.get(row.kind)
    if action is None:
        fail("TEAM_OPERATION_NOT_SUPPORTED", 403)
    p = await policy(session, project_id, actor, action, expected=command.policy_revision, lock=True)
    row = await resource(session, project_id, resource_id)
    exact(row, command)
    if row.status != "SUBMITTED":
        fail("TEAM_DECISION_ALREADY_RESOLVED")
    await readable(session, row, p, actor.id)
    if str(actor.id) in row.responsible_ids:
        fail("TEAM_INDEPENDENT_REVIEWER_REQUIRED", 403)
    await dependencies_current(session, row, p)
    if row.kind == "VERIFICATION":
        report = verified_evidence(await snapshot(session, row))
        if command.decision == "APPROVE" and report.verdict != "PASS":
            fail("TEAM_VERIFIED_PASS_REQUIRED")
    row.status = "APPROVED" if command.decision == "APPROVE" else "CHANGES_REQUESTED"
    row.updated_at = now()
    session.add(row)
    record = AdlcProjectDecision(
        project_id=project_id,
        resource_id=row.id,
        resource_revision=row.revision,
        content_digest=row.content_digest,
        policy_revision=p.revision,
        action=action,
        decision=command.decision,
        decided_by=actor.id,
        comment=command.comment,
        dependencies=row.dependencies,
        expires_at=now() + timedelta(hours=24),
    )
    session.add(record)
    if row.kind == "PLAN" and command.decision == "APPROVE":
        plan = ExecutionPlan.model_validate(await snapshot(session, row)).model_copy(
            update={"status": PlanStatus.APPROVED, "approved_by": str(actor.id), "approved_at": now()}
        )
        archived = await session.get(AdlcExecutionPlan, row.id)
        archived.status, archived.plan_payload = plan.status.value, plan.model_dump(mode="json")
        session.add(archived)
    audit(session, actor, row, p.revision, "decision")
    await session.flush()
    return record.model_dump(mode="json")


def verified_evidence(payload):
    from langflow.adlc.verification_models import VerificationError, VerificationRead, compare, digest
    from langflow.adlc.verification_repository import RUNNER_DIGEST

    try:
        value = VerificationRead.model_validate(payload)
    except ValidationError:
        fail("TEAM_VERIFICATION_BINDING_INVALID", 503)
    if not value.receipt or not value.report or not value.evidence_digest:
        fail("TEAM_VERIFIED_EVIDENCE_REQUIRED")
    try:
        report = compare(value.plan, value.receipt, RUNNER_DIGEST)
    except VerificationError:
        fail("TEAM_VERIFICATION_BINDING_INVALID", 503)
    if (
        value.plan_digest != digest(value.plan)
        or value.report != report
        or value.evidence_digest
        != digest(
            {
                "plan": value.plan.model_dump(mode="json"),
                "receipt": value.receipt.model_dump(mode="json"),
                "report": report.model_dump(mode="json"),
            }
        )
    ):
        fail("TEAM_VERIFICATION_BINDING_INVALID", 503)
    return report


async def revise(session, project_id, resource_id, actor, command):
    await policy(session, project_id, actor, "project:read")
    row = await resource(session, project_id, resource_id)
    if row.kind not in {"CONTRACT", "TEST_SUITE"}:
        fail("TEAM_OPERATION_NOT_SUPPORTED", 403)
    if row.kind == "TEST_SUITE" and "contract" not in row.dependencies:
        fail("TEAM_CURRENT_APPROVAL_REQUIRED")
    p = await policy(session, project_id, actor, WRITE_ACTION[row.kind], expected=command.policy_revision, lock=True)
    row = await resource(session, project_id, resource_id)
    exact(row, command)
    if row.status == "DRAFT":
        fail("TEAM_RESOURCE_ALREADY_DRAFT")
    body = dict(await snapshot(session, row))
    body["revision"] = row.revision + 1
    row.status = "DRAFT"
    await append_revision(session, row, actor, body)
    audit(session, actor, row, p.revision, "revision_opened")
    return await view(session, project_id, row.id, actor)


async def locked_contract(session, project_id, command, p):
    contract = await resource(session, project_id, command.contract_id, kind="CONTRACT")
    if contract.revision != command.contract_revision or contract.content_digest != command.contract_digest:
        fail("TEAM_DEPENDENCY_CHANGED")
    await approval(session, contract, p)
    return contract


def workflow_graph(workflow):
    data = workflow.model_dump(mode="json")
    return {
        "adlc": {
            "document_type": "WORKFLOW_DEFINITION",
            "schema_version": "0.1",
            "workflow_definition_id": str(workflow.workflow_definition_id),
            "version": workflow.version,
            "status": "DRAFT",
            "default_policies": {},
            "metadata": workflow.metadata,
        },
        "nodes": [
            {
                "id": str(stage["stage_id"]),
                "type": "adlcStageNode",
                "position": stage["position"],
                "data": {"adlc": {"document_type": "WORKFLOW_STAGE", "schema_version": "0.1", **stage}},
            }
            for stage in data["stages"]
        ],
        "edges": [
            {
                "id": str(edge["edge_id"]),
                "source": edge["source_stage_id"],
                "target": edge["target_stage_id"],
                "data": {
                    "adlc": {
                        "document_type": "WORKFLOW_EDGE",
                        "schema_version": "0.1",
                        **{
                            key: value
                            for key, value in edge.items()
                            if key not in {"source_stage_id", "target_stage_id"}
                        },
                    }
                },
            }
            for edge in data["edges"]
        ],
    }


async def write_workflow(session, project_id, actor, command, *, resource_id=None):
    p = await policy(
        session,
        project_id,
        actor,
        "flow:write" if resource_id else "flow:create",
        expected=command.policy_revision,
        lock=True,
    )
    contract = await locked_contract(session, project_id, command, p)
    await readable(session, contract, p, actor.id)
    row = None
    if resource_id:
        row = await resource(session, project_id, resource_id, kind="WORKFLOW")
        exact(row, command)
    identity = row.id if row else uuid4()
    timestamp = now()
    document = SkilltreeDocument.model_validate(await snapshot(session, contract))
    stages = [stage.model_copy(deep=True) for stage in command.stages]
    for stage in stages:
        if "requirement" in stage.inputs:
            stage.inputs["requirement"] = document.model_dump_json()
        stage.metadata = {**stage.metadata, "project_contract": reference(contract)}
    workflow = WorkflowDefinition(
        schema_version="0.1",
        workflow_definition_id=identity,
        project_id=project_id,
        name=command.name,
        version=row.revision + 1 if row else 1,
        status="DRAFT",
        stages=stages,
        edges=command.edges,
        default_policies={},
        created_by=str(row.created_by if row else actor.id),
        created_at=aware(row.created_at) if row else timestamp,
        updated_at=timestamp,
        metadata={"project_contract": reference(contract), "collaboration_version": "0.1"},
    )
    deps = {"contract": reference(contract)}
    if row:
        row.dependencies, row.title = deps, command.name
        await append_revision(session, row, actor, workflow.model_dump(mode="json"))
    else:
        row = await create_resource(
            session,
            project_id,
            actor,
            "WORKFLOW",
            command.name,
            workflow.model_dump(mode="json"),
            identity=identity,
            dependencies=deps,
        )
    flow = await session.get(Flow, identity)
    if flow is None:
        flow = Flow(id=identity, name=command.name, folder_id=project_id, user_id=actor.id)
    if flow.folder_id != project_id:
        fail("TEAM_RESOURCE_STORE_INVALID", 503)
    flow.name, flow.data, flow.updated_at = command.name, workflow_graph(workflow), timestamp
    session.add(flow)
    audit(session, actor, row, p.revision, "workflow_saved")
    return await view(session, project_id, row.id, actor)


async def compile_plan(session, project_id, workflow_id, actor, command, compiler):
    workflow_id = UUID(str(workflow_id))
    p = await policy(session, project_id, actor, "flow:write", expected=command.policy_revision, lock=True)
    row = await resource(session, project_id, workflow_id, kind="WORKFLOW")
    await readable(session, row, p, actor.id)
    exact(row, command)
    await dependencies_current(session, row, p)
    workflow = WorkflowDefinition.model_validate(await snapshot(session, row))
    previous = (
        await session.exec(
            select(AdlcExecutionPlan)
            .where(AdlcExecutionPlan.workflow_definition_id == workflow_id)
            .order_by(AdlcExecutionPlan.plan_version.desc())
            .limit(1)
        )
    ).first()
    plan = compiler.compile(
        workflow,
        plan_version=previous.plan_version + 1 if previous else 1,
        generated_by=str(actor.id),
        authorization_subject=str(actor.id),
    )
    if plan.validation_status != PlanValidationStatus.VALID:
        return {"valid": False, "plan": plan.model_dump(mode="json")}
    # The compiler, not the human/agent JSON, is the source of executable tasks.
    plan = plan.model_copy(update={"approval_required": True, "status": PlanStatus.VALIDATED})
    planned = await create_resource(
        session,
        project_id,
        actor,
        "PLAN",
        workflow.name,
        plan.model_dump(mode="json"),
        identity=plan.execution_plan_id,
        parent=workflow_id,
        status="SUBMITTED",
        dependencies={**row.dependencies, "workflow": reference(row)},
        responsible=sorted(set(row.responsible_ids) | {str(actor.id)}),
    )
    if not await reviewers(session, planned, p):
        fail("TEAM_INDEPENDENT_REVIEWER_REQUIRED")
    session.add(
        AdlcExecutionPlan(
            id=plan.execution_plan_id,
            owner_id=str(actor.id),
            workflow_definition_id=workflow_id,
            workflow_definition_version=workflow.version,
            plan_version=plan.plan_version,
            status=plan.status.value,
            validation_status=plan.validation_status.value,
            approval_required=True,
            generated_at=plan.generated_at,
            plan_payload=plan.model_dump(mode="json"),
            workflow_payload=workflow.model_dump(mode="json"),
        )
    )
    audit(session, actor, planned, p.revision, "plan_compiled")
    return {"valid": True, "resource": await view(session, project_id, planned.id, actor)}


async def prepare_run(session, project_id, plan_id, actor, command):
    plan_id = UUID(str(plan_id))
    p = await policy(session, project_id, actor, "flow:write", expected=command.policy_revision, lock=True)
    row = await resource(session, project_id, plan_id, kind="PLAN")
    await readable(session, row, p, actor.id)
    exact(row, command)
    await dependencies_current(session, row, p)
    accepted = await approval(session, row, p)
    existing = (
        await session.exec(
            select(AdlcProjectResource).where(
                AdlcProjectResource.parent_id == plan_id, AdlcProjectResource.kind == "RUN"
            )
        )
    ).first()
    if existing:
        return await view(session, project_id, existing.id, actor)
    plan = ExecutionPlan.model_validate(await snapshot(session, row)).model_copy(
        update={
            "status": PlanStatus.APPROVED,
            "approved_by": str(accepted.decided_by),
            "approved_at": aware(accepted.created_at),
        }
    )
    definitions = materialize_task_definitions(plan)
    run_id = uuid4()
    task_ids = {definition.key: uuid4() for definition in definitions}
    tasks = [
        TaskRun(
            id=task_ids[d.key],
            workflow_run_id=run_id,
            task_definition_id=d.id,
            key=d.key,
            name=d.name,
            task_type=d.task_type,
            status=TaskRunStatus.PENDING,
            dependency_task_run_ids=[task_ids[key] for key in d.dependencies],
            executor=d.executor_target,
            plan_traceability=d.plan_traceability,
        )
        for d in definitions
    ]
    timestamp = now()
    event = RunEvent(
        event_id=uuid4(),
        event_type="workflow_run.created",
        workflow_run_id=run_id,
        aggregate_type="WORKFLOW_RUN",
        aggregate_id=run_id,
        sequence=1,
        previous_status=None,
        status="CREATED",
        actor=Actor(type="USER", id=str(actor.id)),
        occurred_at=timestamp,
        producer="adlc-project-collaboration",
        payload={"project_id": str(project_id), "execution_enabled": False, "plan_digest": row.content_digest},
    )
    run = WorkflowRun(
        id=run_id,
        project_id=project_id,
        initiated_by=str(actor.id),
        workflow_key=str(plan.workflow_definition_id),
        execution_mode=WorkflowExecutionMode.EXECUTION_PLAN,
        flow_id=plan.workflow_definition_id,
        execution_plan_id=plan_id,
        name=row.title,
        status=WorkflowRunStatus.CREATED,
        tasks=tasks,
        events=[event],
        created_at=timestamp,
    )
    session.add(
        AdlcWorkflowRun(
            id=run_id,
            owner_id=str(actor.id),
            status=run.status.value,
            execution_mode=run.execution_mode.value,
            flow_id=run.flow_id,
            execution_plan_id=plan_id,
            run_payload=run.model_dump(mode="json"),
            definitions_payload=[d.model_dump(mode="json") for d in definitions],
            created_at=timestamp,
        )
    )
    shared = await create_resource(
        session,
        project_id,
        actor,
        "RUN",
        row.title,
        run.model_dump(mode="json"),
        identity=run_id,
        parent=plan_id,
        responsible=row.responsible_ids,
        dependencies={"plan": reference(row)},
        status="RETAINED",
    )
    audit(session, actor, shared, p.revision, "run_prepared")
    return await view(session, project_id, shared.id, actor)


async def create_suite(session, project_id, actor, command, *, resource_id=None):
    p = await policy(session, project_id, actor, "test_suite:write", expected=command.policy_revision, lock=True)
    contract = await locked_contract(session, project_id, command, p)
    await readable(session, contract, p, actor.id)
    doc = SkilltreeDocument.model_validate(await snapshot(session, contract))
    criteria = {node.node_id: node.acceptance_criteria for node in doc.nodes}
    if len({case.case_id for case in command.cases}) != len(command.cases):
        fail("TEAM_SUITE_CRITERION_INVALID", 422)
    pairs = set()
    for case in command.cases:
        pair = (case.criterion_node_id, case.criterion_index)
        if (
            pair in pairs
            or case.criterion_node_id not in criteria
            or case.criterion_index >= len(criteria[case.criterion_node_id])
        ):
            fail("TEAM_SUITE_CRITERION_INVALID", 422)
        pairs.add(pair)
    row = await resource(session, project_id, resource_id, kind="TEST_SUITE") if resource_id else None
    if row:
        exact(row, command)
        if row.status != "DRAFT":
            fail("TEAM_RESOURCE_LOCKED")
    body = {
        "schema_version": "0.1",
        "revision": row.revision + 1 if row else 1,
        "profile_ref": "verification-profile:json-fixture/0.1.0",
        "cases": [case.model_dump(mode="json") for case in command.cases],
        "criteria_executed": False,
    }
    if row:
        row.dependencies, row.title = {"contract": reference(contract)}, command.name
        await append_revision(session, row, actor, body)
    else:
        row = await create_resource(
            session, project_id, actor, "TEST_SUITE", command.name, body, dependencies={"contract": reference(contract)}
        )
    audit(session, actor, row, p.revision, "suite_created")
    return await view(session, project_id, row.id, actor)


def shared_run_projection(run):
    """Do not share tool credentials, dispatch inputs, raw runtime metadata or links."""
    run = run.model_copy(deep=True)
    for task in run.tasks:
        task.request, task.pending_result = None, None
        for artifact in task.artifacts:
            artifact.uri, artifact.metadata = "", {}
        if task.result:
            task.result.metadata = {}
            for artifact in task.result.artifacts:
                artifact.uri, artifact.metadata = "", {}
            if task.result.error:
                task.result.error.details = {}
    for event in run.events:
        event.payload = {
            key: value
            for key, value in event.payload.items()
            if key
            in {"execution_mode", "reason", "task_key", "error_code", "execution_enabled", "plan_digest", "project_id"}
        }
    # Owner-bound runtime actions remain historical, not executable approvals.
    run.approval_requests = []
    return run


async def import_bundle(session, project_id, run_id, actor, *, verification_repository=None, contract_repository=None):
    run_id = UUID(str(run_id))
    p = await policy(session, project_id, actor, "policy:manage")
    await policy(session, project_id, actor, "run:read")
    source = await session.get(AdlcWorkflowRun, run_id)
    if source is None or source.owner_id != str(actor.id):
        fail("TEAM_IMPORT_ORIGINAL_OWNER_REQUIRED", 404)
    if await session.get(AdlcProjectResource, run_id):
        fail("TEAM_RESOURCE_ALREADY_BOUND")
    run = WorkflowRun.model_validate(source.run_payload)
    if (
        run.id != source.id
        or source.execution_mode != run.execution_mode.value
        or source.flow_id != run.flow_id
        or source.execution_plan_id != run.execution_plan_id
    ):
        fail("TEAM_RESOURCE_STORE_INVALID", 503)
    if (
        run.status not in {WorkflowRunStatus.SUCCEEDED, WorkflowRunStatus.FAILED, WorkflowRunStatus.CANCELLED}
        or source.status != run.status.value
        or run.completed_at is None
        or run.project_id is not None
    ):
        fail("TEAM_IMPORT_TERMINAL_RUN_REQUIRED")
    plan = await session.get(AdlcExecutionPlan, run.execution_plan_id) if run.execution_plan_id else None
    if plan is not None and plan.owner_id != str(actor.id):
        fail("TEAM_IMPORT_ORIGINAL_OWNER_REQUIRED", 404)
    contracts = (
        contract_repository.list_for_run(run.id, owner_id=str(actor.id), limit=100) if contract_repository else []
    )
    contracts = [item for item in contracts if item.status == "APPROVED"]
    verified = verification_repository.list(owner=str(actor.id), run_id=run.id) if verification_repository else []
    verified = [item for item in verified if item.receipt and item.report and item.evidence_digest]
    manifest = {
        "run": sha256_digest(source.run_payload),
        "plan": sha256_digest(plan.plan_payload) if plan else None,
        "contracts": [item.reference.model_dump(mode="json") for item in contracts],
        "verifications": [sha256_digest(item.model_dump(mode="json")) for item in verified],
    }
    preview = {
        "run_id": run.id,
        "name": run.name,
        "status": run.status.value,
        "origin_owner_id": source.owner_id,
        "content_digest": sha256_digest(manifest),
        "policy_revision": p.revision,
        "manifest": manifest,
        "task_count": len(run.tasks),
        "artifact_count": sum(len(task.artifacts) for task in run.tasks),
        "contract_count": len(contracts),
        "verification_count": len(verified),
        "plan_count": int(plan is not None),
        "warning": "Chia sẻ snapshot kết quả, không chuyển credential, runtime action hoặc quyền thực thi.",
    }
    return preview, source, run, plan, contracts, verified


async def import_preview(session, project_id, run_id, actor, **repositories):
    return (await import_bundle(session, project_id, run_id, actor, **repositories))[0]


async def import_run(
    session, project_id, actor, command, *, artifact_store, verification_repository=None, contract_repository=None
):
    p = await policy(session, project_id, actor, "policy:manage", expected=command.policy_revision, lock=True)
    preview, source, original, plan, contracts, verified = await import_bundle(
        session,
        project_id,
        command.run_id,
        actor,
        verification_repository=verification_repository,
        contract_repository=contract_repository,
    )
    if preview["content_digest"] != command.content_digest:
        fail("TEAM_RESOURCE_REVISION_CONFLICT")
    projection = shared_run_projection(original)
    projection.project_id, projection.initiated_by = project_id, original.initiated_by or source.owner_id
    row = await create_resource(
        session,
        project_id,
        actor,
        "RUN",
        projection.name,
        projection.model_dump(mode="json"),
        identity=original.id,
        status="RETAINED",
        origin=source.owner_id,
        responsible=sorted({source.owner_id, original.initiated_by or source.owner_id}),
    )
    # The original runtime snapshot is not rewritten or re-owned. Its new binding
    # blocks legacy access; the explicitly shared projection is frozen separately.
    candidates = {}
    from langflow.adlc.artifact_payload_store import ArtifactPayloadUnavailableError, SourcePatchSnapshot

    if plan is not None:
        compiled = ExecutionPlan.model_validate(plan.plan_payload)
        await create_resource(
            session,
            project_id,
            actor,
            "PLAN",
            original.name + " · kế hoạch lưu trữ",
            compiled.model_dump(mode="json"),
            identity=plan.id,
            parent=original.id,
            origin=source.owner_id,
            responsible=row.responsible_ids,
            status="RETAINED",
        )
    for item in contracts:
        # Preserve original identity/revision, not the legacy owner approval as a
        # project grant. A fresh independent human decision is still required.
        await create_resource(
            session,
            project_id,
            actor,
            "CONTRACT",
            item.document.title,
            item.document.model_dump(mode="json"),
            identity=item.document.contract_id,
            initial_revision=item.document.revision,
            parent=original.id,
            origin=source.owner_id,
            responsible=row.responsible_ids,
            status="SUBMITTED",
        )

    for task in original.tasks:
        for item in task.artifacts:
            if item.workflow_run_id != original.id or item.task_run_id != task.id:
                fail("TEAM_RESOURCE_STORE_INVALID", 503)
            body = item.model_dump(mode="json")
            body.pop("uri", None)
            body.pop("metadata", None)
            patch = None
            if item.kind == "SOURCE_PATCH":
                try:
                    patch = SourcePatchSnapshot.model_validate_json(artifact_store.read(item))
                except ArtifactPayloadUnavailableError:
                    patch = None
            if patch:
                body["source_patch"] = patch.model_dump(mode="json")
            item_row = await create_resource(
                session,
                project_id,
                actor,
                "CANDIDATE" if patch else "ARTIFACT",
                item.name,
                body,
                identity=item.artifact_id,
                parent=original.id,
                origin=source.owner_id,
                status="SUBMITTED" if patch else "RETAINED",
                responsible=row.responsible_ids,
            )
            candidates[item.artifact_id] = item_row
    if verification_repository is not None:
        # This is the authenticated ORIGINAL owner's export, not impersonation.
        for record in verified:
            candidate = candidates.get(record.plan.candidate.artifact_id)
            if candidate is None or not record.receipt or not record.report or not record.evidence_digest:
                continue
            artifact = await snapshot(session, candidate)
            if (
                record.plan.workflow_run_id != original.id
                or artifact["attempt_id"] != str(record.plan.candidate.source_attempt_id)
                or "sha256:" + artifact["checksum"]["value"].removeprefix("sha256:")
                != record.plan.candidate.artifact_digest
            ):
                fail("TEAM_VERIFICATION_BINDING_INVALID", 503)
            verified = await create_resource(
                session,
                project_id,
                actor,
                "VERIFICATION",
                "Verify · " + original.name,
                record.model_dump(mode="json"),
                identity=record.plan.plan_id,
                parent=original.id,
                origin=source.owner_id,
                status="SUBMITTED",
                responsible=row.responsible_ids,
                dependencies={"candidate": reference(candidate)},
            )
            suite_id = uuid5(NAMESPACE_URL, f"adlc:shared-suite:{record.plan.plan_id}")
            await create_resource(
                session,
                project_id,
                actor,
                "TEST_SUITE",
                "Suite · " + original.name,
                {
                    "schema_version": "0.1",
                    "revision": 1,
                    "cases": [case.model_dump(mode="json") for case in record.plan.cases],
                    "source_verification_id": str(verified.id),
                    "plan_digest": record.plan_digest,
                    "criteria_executed": False,
                },
                identity=suite_id,
                parent=original.id,
                origin=source.owner_id,
                status="FROZEN",
                responsible=row.responsible_ids,
            )
    audit(session, actor, row, p.revision, "run_imported")
    return await view(session, project_id, row.id, actor)


async def bound_run_ids():
    """Discovery only; never caches membership or an allow decision."""
    from langflow.services.deps import session_scope

    async with session_scope() as session:
        return set((await session.exec(select(AdlcProjectResource.id).where(AdlcProjectResource.kind == "RUN"))).all())
