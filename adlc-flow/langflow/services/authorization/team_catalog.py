"""Versioned, closed vocabulary; role labels are not an authorization hierarchy."""

from enum import Enum
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

VERSION = "0.1"


class TeamRole(str, Enum):
    ADMIN = "admin"
    DEVELOPER = "developer"
    BUSINESS_ANALYST = "business_analyst"
    TESTER = "tester"


ROLE_LABELS = {
    TeamRole.ADMIN: "Admin",
    TeamRole.DEVELOPER: "Developer",
    TeamRole.BUSINESS_ANALYST: "Business Analyst",
    TeamRole.TESTER: "Tester",
}


def role_name(role: TeamRole) -> str:
    return f"adlc.{role.value}"


def role_id(role: TeamRole):
    return uuid5(NAMESPACE_URL, f"adlc:team-role:{VERSION}:{role.value}")


class TeamAction(BaseModel):
    key: str
    label: str
    area: str
    phase: str = "H7B"


ACTION_CATALOG = (
    TeamAction(key="project:read", label="Xem project", area="Project", phase="H7A"),
    TeamAction(key="policy:read", label="Xem quyền hiệu lực của mình", area="Quản trị", phase="H7A"),
    TeamAction(key="policy:manage", label="Quản lý chính sách", area="Quản trị", phase="H7A"),
    TeamAction(key="membership:manage", label="Quản lý thành viên", area="Quản trị", phase="H7A"),
    TeamAction(key="audit:read", label="Xem nhật ký phân quyền", area="Quản trị", phase="H7A"),
    TeamAction(key="requirement:read", label="Xem yêu cầu", area="Yêu cầu & Contract"),
    TeamAction(key="requirement:write", label="Soạn yêu cầu", area="Yêu cầu & Contract"),
    TeamAction(key="contract:submit", label="Gửi contract để duyệt", area="Yêu cầu & Contract"),
    TeamAction(key="contract:approve", label="Duyệt nghiệp vụ", area="Yêu cầu & Contract"),
    TeamAction(key="flow:read", label="Xem workflow", area="Workflows"),
    TeamAction(key="flow:create", label="Tạo workflow", area="Workflows"),
    TeamAction(key="flow:write", label="Sửa workflow", area="Workflows"),
    TeamAction(key="flow:execute", label="Khởi chạy workflow", area="Workflows", phase="H7C"),
    TeamAction(key="plan:approve", label="Duyệt kế hoạch kỹ thuật", area="Workflows"),
    TeamAction(key="run:read", label="Xem run và artifact", area="Runs & Harness"),
    TeamAction(key="task:assign", label="Giao task", area="Runs & Harness", phase="H7C"),
    TeamAction(key="candidate:review", label="Review candidate", area="Source & candidate"),
    TeamAction(key="source:write", label="Sửa source trong sandbox", area="Source & candidate", phase="H7C"),
    TeamAction(key="verification:read", label="Xem bằng chứng Verify", area="Testing & Verify"),
    TeamAction(key="test_suite:write", label="Soạn suite trước khi khóa", area="Testing & Verify"),
    TeamAction(key="verification:accept", label="Nghiệm thu chất lượng", area="Testing & Verify"),
    TeamAction(key="verification:execute", label="Chạy Verify độc lập", area="Testing & Verify", phase="H7C"),
    TeamAction(key="memory:read", label="Đọc memory project", area="Memory", phase="H7C"),
    TeamAction(key="memory:propose", label="Đề xuất tri thức", area="Memory", phase="H7C"),
    TeamAction(key="integration:use", label="Dùng kết nối đã cấp", area="Integrations", phase="H7C"),
    TeamAction(key="integration:manage", label="Quản trị kết nối", area="Integrations", phase="H7C"),
    TeamAction(key="publication:approve", label="Duyệt đúng commit/target", area="Publish GitHub", phase="H7C"),
)
ACTIONS = {action.key: action for action in ACTION_CATALOG}
ADMIN_ONLY = frozenset({"policy:manage", "membership:manage", "audit:read", "integration:manage"})
ADMIN_REQUIRED = frozenset({"project:read", "policy:read", "policy:manage", "membership:manage", "audit:read"})


class RoleRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allow: list[str] = Field(default_factory=list, max_length=64)
    deny: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def closed_vocabulary(self):
        if any(key not in ACTIONS for key in self.allow + self.deny):
            msg = "TEAM_UNKNOWN_ACTION"
            raise ValueError(msg)
        if len(set(self.allow)) != len(self.allow) or len(set(self.deny)) != len(self.deny):
            msg = "TEAM_DUPLICATE_ACTION"
            raise ValueError(msg)
        if set(self.allow) & set(self.deny):
            msg = "TEAM_CONFLICTING_RULE"
            raise ValueError(msg)
        return self


class TeamPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: dict[TeamRole, RoleRule]

    @model_validator(mode="after")
    def four_roles(self):
        if set(self.roles) != set(TeamRole):
            msg = "TEAM_EXACT_FOUR_ROLES_REQUIRED"
            raise ValueError(msg)
        for role, rule in self.roles.items():
            if role != TeamRole.ADMIN and set(rule.allow) & ADMIN_ONLY:
                msg = "TEAM_ADMIN_PERMISSION_RESERVED"
                raise ValueError(msg)
        admin = self.roles[TeamRole.ADMIN]
        if not ADMIN_REQUIRED.issubset(admin.allow) or ADMIN_REQUIRED & set(admin.deny):
            msg = "TEAM_ADMIN_PROTECTION_REQUIRED"
            raise ValueError(msg)
        return self


def default_policy() -> TeamPolicy:
    read = {"project:read", "policy:read", "requirement:read", "flow:read", "run:read", "verification:read"}
    grants = {
        TeamRole.ADMIN: read | ADMIN_REQUIRED | {"integration:manage"},
        TeamRole.DEVELOPER: read
        | {
            "flow:create",
            "flow:write",
            "flow:execute",
            "plan:approve",
            "task:assign",
            "candidate:review",
            "source:write",
            "integration:use",
            "memory:read",
            "memory:propose",
        },
        TeamRole.BUSINESS_ANALYST: read
        | {"requirement:write", "contract:submit", "contract:approve", "memory:read", "memory:propose"},
        TeamRole.TESTER: read
        | {
            "test_suite:write",
            "verification:accept",
            "verification:execute",
            "integration:use",
            "memory:read",
            "memory:propose",
        },
    }
    return TeamPolicy(roles={role: RoleRule(allow=sorted(keys)) for role, keys in grants.items()})


def decide(policy: TeamPolicy, roles: set[TeamRole], action: str, *, collaboration: bool = False) -> tuple[bool, str]:
    if action not in ACTIONS:
        return False, "TEAM_UNKNOWN_ACTION"
    if not roles:
        return False, "TEAM_MEMBERSHIP_REQUIRED"
    if any(action in policy.roles[role].deny for role in roles):
        return False, "TEAM_EXPLICIT_DENY"
    if not any(action in policy.roles[role].allow for role in roles):
        return False, "TEAM_PERMISSION_DENIED"
    if ACTIONS[action].phase not in ({"H7A", "H7B"} if collaboration else {"H7A"}):
        return False, "TEAM_SHARED_EXECUTION_NOT_ENABLED"
    return True, "TEAM_PERMISSION_GRANTED"
