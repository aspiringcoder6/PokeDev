"""Validated TNQD plans: detailed work, immutable context and explicit artifact dependencies."""
from __future__ import annotations
import hashlib
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

COMPONENT = "membership-list.component.ts"
TEMPLATE = "membership-list.component.html"
STYLE = "membership-list.component.scss"
OPERATIONS = (
    "fixture", "patch.pagination", "patch.race", "patch.loading",
    "test.pagination", "test.race", "test.states", "verify.merge",
    "verify.baseline", "verify.candidate", "build", "review", "deploy",
    "testforge", "documents", "memory", "handover",
)
NATIVE_OPERATIONS = {op for op in OPERATIONS if op.startswith(("patch.", "test."))} | {"review", "documents"}
WRITE_SCOPES = {
    "patch.pagination": [COMPONENT], "patch.race": [COMPONENT],
    "patch.loading": [TEMPLATE, STYLE],
    "test.pagination": ["pagination.cases.json"], "test.race": ["race.cases.json"],
    "test.states": ["states.cases.json"], "review": ["review.json"],
    "documents": ["documents.json"],
}

def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()

class DetailedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{1,39}$")
    title: str = Field(min_length=18, max_length=180)
    operation: Literal[*OPERATIONS]
    role: str = Field(min_length=2, max_length=40)
    depends_on: list[str] = Field(max_length=24)
    steps: list[str] = Field(min_length=3, max_length=9)
    inputs: list[str] = Field(min_length=1, max_length=12)
    outputs: list[str] = Field(min_length=1, max_length=8)
    acceptance: list[str] = Field(min_length=2, max_length=8)
    requirements: list[str] = Field(min_length=1, max_length=12)

class DetailedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=15, max_length=200)
    summary: str = Field(min_length=40, max_length=2000)
    tasks: list[DetailedTask] = Field(min_length=17, max_length=24)

def validate_plan(value):
    plan = DetailedPlan.model_validate(value).model_dump()
    tasks = plan["tasks"]
    by_id = {t["id"]: t for t in tasks}
    by_op = {t["operation"]: t for t in tasks}
    if len(by_id) != len(tasks) or len(by_op) != len(tasks) or set(by_op) != set(OPERATIONS):
        raise ValueError("TNQD_PLAN_OPERATIONS_REQUIRED")
    done = set()
    layers = []
    remaining = set(by_id)
    while remaining:
        ready = sorted(t for t in remaining if set(by_id[t]["depends_on"]) <= done)
        if not ready:
            raise ValueError("TNQD_PLAN_CYCLE_OR_MISSING_DEPENDENCY")
        layers.append(ready)
        remaining.difference_update(ready)
        done.update(ready)
    ancestors = {}
    for layer in layers:
        for identity in layer:
            dependencies = set(by_id[identity]["depends_on"])
            ancestors[identity] = dependencies | set().union(*(ancestors[p] for p in dependencies))
    def requires(target, *sources):
        if any(by_op[source]["id"] not in ancestors[by_op[target]["id"]] for source in sources):
            raise ValueError("TNQD_PLAN_REQUIRED_DEPENDENCY_" + target)
    for op in OPERATIONS[1:]:
        requires(op, "fixture")
    requires("patch.race", "patch.pagination")
    requires("verify.merge", "patch.pagination", "patch.race", "patch.loading", "test.pagination", "test.race", "test.states")
    requires("verify.baseline", "verify.merge")
    requires("verify.candidate", "verify.baseline")
    requires("build", "verify.candidate")
    requires("review", "build")
    requires("deploy", "review")
    requires("testforge", "deploy")
    requires("documents", "testforge")
    requires("memory", "documents")
    requires("handover", "memory")
    pair = [by_op[op]["id"] for op in ("patch.pagination", "test.pagination")]
    if pair[0] in ancestors[pair[1]] or pair[1] in ancestors[pair[0]]:
        raise ValueError("TNQD_PLAN_INDEPENDENT_BRANCHES_REQUIRED")
    if not {f"AC{i:02}" for i in range(1, 13)} <= {r for t in tasks for r in t["requirements"]}:
        raise ValueError("TNQD_PLAN_ACCEPTANCE_COVERAGE_REQUIRED")
    for task in tasks:
        if any(len(step.strip()) < 20 for step in task["steps"]) or any(len(x.strip()) < 12 for x in task["acceptance"]):
            raise ValueError("TNQD_PLAN_DETAIL_REQUIRED")
        task["write_paths"] = WRITE_SCOPES.get(task["operation"], [])
        task["executor"] = "NATIVE_TASKLOOP" if task["operation"] in NATIVE_OPERATIONS else "FIXED_RUNNER"
    plan.update(layers=layers, parallel_pair=pair, max_parallel=2)
    plan["digest"] = digest(plan)
    return plan

def planner_prompt():
    return """Bạn là Planner cho pilot TNQD, không viết code. Đọc inputs/context.md và source.
Tạo outputs/result.json là JSON thuần theo schema sau:
{\"title\":\"...\",\"summary\":\"...\",\"tasks\":[{\"id\":\"T01\",\"title\":\"Tên công việc cụ thể tiếng Việt\",\"operation\":\"fixture\",\"role\":\"coordinator\",\"depends_on\":[],\"steps\":[\"ít nhất ba bước, mỗi bước hơn 20 ký tự\"],\"inputs\":[\"...\"],\"outputs\":[\"...\"],\"acceptance\":[\"ít nhất hai điều kiện cụ thể\"],\"requirements\":[\"AC01\"]}]}.
Sinh đúng 17 task, mỗi operation dùng một lần:
fixture; patch.pagination; patch.race; patch.loading; test.pagination; test.race; test.states;
verify.merge; verify.baseline; verify.candidate; build; review; deploy; testforge; documents; memory; handover.
Không thêm field ngoài schema. Tên và bước làm phải nói rõ màn hình, phương thức/file,
điều kiện trước–sau và artifact; không đặt tên chỉ là Develop/Test/Review chung chung.
fixture đứng đầu. Hai nhánh code/test độc lập cùng phụ thuộc fixture.
patch.race phụ thuộc patch.pagination vì sửa cùng component. patch.loading sửa template/style riêng.
Ba task test độc lập với code, dùng spec làm expected result, phủ AC01–AC12.
verify.merge phải chờ cả ba task patch và cả ba task test.
Sau đó nối verify.baseline → verify.candidate → build → review → deploy → testforge → documents → memory → handover.
Baseline phải tái hiện vấn đề trước khi candidate được đánh giá; lỗi môi trường không tính lỗi nghiệp vụ.
Context tài liệu có nguồn được giữ theo snapshot; Memory là ngữ cảnh, không tự xác nhận sản phẩm đạt.
Môi trường trình duyệt pilot là component Angular thật với fixture API 45 hồ sơ;
đừng ghi thành đã chứng nhận backend Java/CSDL hoặc RBAC server.
Viết file bằng tool filesystem, không chỉ trả JSON trong chat. Sau khi có file, cập nhật contract TaskLoop.
Không dùng subagent, không commit/push, không thao tác ngoài workspace task này."""
