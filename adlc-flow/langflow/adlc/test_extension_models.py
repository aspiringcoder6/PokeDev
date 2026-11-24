"""H6D sidecars: proposals and supplementary images, never execution authority.

Published H6A/B receipts and runner locks remain unchanged. Exploration/performance
are proposals only until a separately reviewed execution profile exists.
"""

# ruff: noqa: EM101, TRY003 - fixed, non-sensitive validation messages.
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt, model_validator

from langflow.adlc.contract_models import ContractReference, Digest
from langflow.adlc.replay_models import ReplayCase
from langflow.adlc.verification_models import CaseId, Closed

PROFILE = "test-extension-profile:proposals/0.1.0"
DOMAIN = b"adlc-test-proposals-v1\n"
MAX_COMMAND_BYTES = 24 * 1024
MAX_PNG_BYTES = 256 * 1024
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 4_000_000
MAX_SCREENSHOTS_PER_PLAN = 4
MAX_INPUT_DEPTH = 20
SURROGATE_START, SURROGATE_END, CONTROL_LIMIT = 0xD800, 0xDFFF, 32
Key = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
Session = Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,255}$")]
ProposalKind = Literal["suite-revision", "exploration", "performance"]


class ExtensionClosed(Closed):
    @model_validator(mode="before")
    @classmethod
    def bounded_text(cls, value):
        def check(item, depth=0):
            if depth > MAX_INPUT_DEPTH:
                raise ValueError("Extension input is too deeply nested.")
            if isinstance(item, str) and any(
                SURROGATE_START <= ord(c) <= SURROGATE_END or (ord(c) < CONTROL_LIMIT and c not in "\n\t\r")
                for c in item
            ):
                raise ValueError("Extension text contains unsupported characters.")
            if isinstance(item, (dict, list)):
                for part in item.values() if isinstance(item, dict) else item:
                    check(part, depth + 1)

        check(value)
        return value


class ProposalReference(ExtensionClosed):
    proposal_id: UUID
    revision: Annotated[StrictInt, Field(ge=1, le=100)]
    document_digest: Digest


class ReplaySource(ExtensionClosed):
    workflow_run_id: UUID
    plan_id: UUID
    plan_digest: Digest
    suite_digest: Digest
    candidate_digest: Digest
    project_id: UUID
    source_session_id: Session
    contract_reference: ContractReference


class TestPermissions(ExtensionClosed):
    """The only reviewed target/data envelope today; not a broker permission grant."""

    target_profile_ref: Literal["target-profile:disposable-http-json/0.1.0"]
    credential_ref: Literal["credential-profile:ephemeral-fixture/0.1.0"]
    environment: Literal["non-production"]
    data_scope: Literal["synthetic-run-owned-only"]
    allowed_methods: list[Literal["GET"]] = Field(min_length=1, max_length=1)
    allowed_paths: list[Literal["/fixture"]] = Field(min_length=1, max_length=1)
    network_scope: Literal["allocated-loopback-target-only"]
    cleanup: Literal["release-owned-target"]
    cancellation: Literal["confirmed-worker-cancel"]
    max_duration_seconds: Annotated[StrictInt, Field(ge=1, le=60)]


class PerformanceBudget(ExtensionClosed):
    """Bounded planning inputs only. No performance runner is registered."""

    virtual_users: Annotated[StrictInt, Field(ge=1, le=5)]
    duration_seconds: Annotated[StrictInt, Field(ge=1, le=30)]
    requests_per_second: Annotated[StrictInt, Field(ge=1, le=5)]
    max_requests: Annotated[StrictInt, Field(ge=1, le=100)]
    p95_latency_ms_max: Annotated[StrictInt, Field(ge=1, le=10000)]
    failed_requests_max: Annotated[StrictInt, Field(ge=0, le=10)]

    @model_validator(mode="after")
    def bounded_workload(self):
        if self.duration_seconds * self.requests_per_second > self.max_requests:
            raise ValueError("Planned request count exceeds the explicit cap.")
        return self


class TestProposal(ExtensionClosed):
    schema_version: Literal["0.1"] = "0.1"
    profile_ref: Literal["test-extension-profile:proposals/0.1.0"] = PROFILE
    proposal_id: UUID
    revision: Annotated[StrictInt, Field(ge=1, le=100)] = 1
    parent_reference: ProposalReference | None = None
    source: ReplaySource
    authoring_session_id: Session | None = None
    kind: ProposalKind
    title: Annotated[str, Field(min_length=1, max_length=120)]
    rationale: Annotated[str, Field(min_length=1, max_length=2000)]
    cases: list[ReplayCase] = Field(max_length=16)
    permissions: TestPermissions | None = None
    performance: PerformanceBudget | None = None
    heal: Literal[False] = False
    models_used: Literal[False] = False
    executable: Literal[False] = False
    verification_evidence: Literal[False] = False

    @model_validator(mode="after")
    def structure(self):
        if len({c.case_id for c in self.cases}) != len(self.cases) or len(
            {(c.criterion_node_id, c.criterion_index) for c in self.cases}
        ) != len(self.cases):
            raise ValueError("Cases and criterion mappings must be unique.")
        if (self.revision == 1) != (self.parent_reference is None):
            raise ValueError("Successors require an exact parent reference.")
        if self.parent_reference and self.revision != self.parent_reference.revision + 1:
            raise ValueError("Successor revision must follow its parent.")
        if self.kind != "performance" and self.performance is not None:
            raise ValueError("Performance budgets belong to performance proposals only.")
        if (
            self.performance
            and self.permissions
            and self.performance.duration_seconds > self.permissions.max_duration_seconds
        ):
            raise ValueError("Workload exceeds the permission duration.")
        return self


class ProposalRead(ExtensionClosed):
    document: TestProposal
    reference: ProposalReference
    state: Literal["DRAFT", "READY_FOR_REVIEW", "APPROVED", "MATERIALIZED"]
    created_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    materialized_plan_id: UUID | None = None

    @model_validator(mode="after")
    def lifecycle(self):
        approved = self.state in {"APPROVED", "MATERIALIZED"}
        if approved != (self.approved_by is not None and self.approved_at is not None):
            raise ValueError("Approval must be an authenticated stored decision.")
        if (self.state == "MATERIALIZED") != (self.materialized_plan_id is not None):
            raise ValueError("Materialization must reference the new draft suite.")
        if self.state != "DRAFT" and (not self.document.cases or not self.document.permissions):
            raise ValueError("Review requires cases and explicit permissions.")
        if self.state != "DRAFT" and self.document.kind == "performance" and not self.document.performance:
            raise ValueError("Performance review requires a bounded workload.")
        if not self.created_at.tzinfo or (self.approved_at and not self.approved_at.tzinfo):
            raise ValueError("Timestamps must be timezone-aware.")
        return self


class ProposalInit(ExtensionClosed):
    operation: Literal["init"]
    source_plan_id: UUID
    kind: ProposalKind
    title: Annotated[str, Field(min_length=1, max_length=120)]
    rationale: Annotated[str, Field(min_length=1, max_length=2000)]
    parent_reference: ProposalReference | None = None
    idempotency_key: Key


class ProposalUpsert(ExtensionClosed):
    operation: Literal["upsert_case"]
    reference: ProposalReference
    case: ReplayCase
    idempotency_key: Key


class ProposalRemove(ExtensionClosed):
    operation: Literal["remove_case"]
    reference: ProposalReference
    case_id: CaseId
    idempotency_key: Key


class ProposalPermissions(ExtensionClosed):
    operation: Literal["set_permissions"]
    reference: ProposalReference
    permissions: TestPermissions
    performance: PerformanceBudget | None = None
    idempotency_key: Key


class ProposalStatus(ExtensionClosed):
    operation: Literal["get_status"]
    proposal_id: UUID


class ProposalValidate(ExtensionClosed):
    operation: Literal["validate"]
    reference: ProposalReference
    idempotency_key: Key


ProposalCommand = Annotated[
    ProposalInit | ProposalUpsert | ProposalRemove | ProposalPermissions | ProposalStatus | ProposalValidate,
    Field(discriminator="operation"),
]


class ProposalBridgeCommand(ExtensionClosed):
    session_id: Session
    command: ProposalCommand


class ProposalDecision(ExtensionClosed):
    reference: ProposalReference


class ExtensionCapabilities(ExtensionClosed):
    schema_version: Literal["0.1"] = "0.1"
    profile_ref: Literal["test-extension-profile:proposals/0.1.0"] = PROFILE
    enabled: bool
    human_actions_configured: bool
    exploration_ready: Literal[False] = False
    performance_ready: Literal[False] = False
    screenshot_capture_ready: Literal[False] = False
    blockers: list[str] = Field(
        default_factory=lambda: [
            "REVIEWED_BACKEND_AND_TARGET_REQUIRED",
            "BROKER_IDEMPOTENCY_AND_CANCELLATION_REQUIRED",
            "RUN_OWNED_DATA_CLEANUP_REQUIRED",
            "MY_CODEX_GPT_5_6_LUNA_ROUTE_AUDIT_REQUIRED",
            "AUTHENTICATED_RUNNER_SCREENSHOT_CAPTURE_REQUIRED",
        ]
    )


class ScreenshotUpload(ExtensionClosed):
    plan_digest: Digest
    execution_id: UUID
    case_id: CaseId
    caption: Annotated[str, Field(min_length=1, max_length=240)]
    png_base64: Annotated[str, Field(min_length=1, max_length=349528)]
    input_digest: Digest
    idempotency_key: Key


class ScreenshotRead(ExtensionClosed):
    schema_version: Literal["0.1"] = "0.1"
    profile_ref: Literal["evidence-profile:supplementary-png/0.1.0"] = "evidence-profile:supplementary-png/0.1.0"
    attachment_id: UUID
    workflow_run_id: UUID
    plan_id: UUID
    plan_digest: Digest
    execution_id: UUID
    candidate_digest: Digest
    case_id: CaseId
    caption: Annotated[str, Field(min_length=1, max_length=240)]
    authority: Literal["SUPPLEMENTARY_UNTRUSTED"] = "SUPPLEMENTARY_UNTRUSTED"
    affects_verdict: Literal[False] = False
    capture_provenance_verified: Literal[False] = False
    uploaded_by: str
    uploaded_at: datetime
    input_digest: Digest
    content_digest: Digest
    media_type: Literal["image/png"] = "image/png"
    byte_size: Annotated[StrictInt, Field(ge=1, le=MAX_PNG_BYTES)]
    width: Annotated[StrictInt, Field(ge=1, le=MAX_IMAGE_DIMENSION)]
    height: Annotated[StrictInt, Field(ge=1, le=MAX_IMAGE_DIMENSION)]
    case_evidence_digest: Digest

    @model_validator(mode="after")
    def bounds(self):
        if self.width * self.height > MAX_IMAGE_PIXELS or not self.uploaded_at.tzinfo:
            raise ValueError("Image dimensions/time are outside the approved envelope.")
        return self
