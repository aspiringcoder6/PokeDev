"""Test Design Agent (Bước 5 & Bước 6).

Nhiệm vụ:
- Từ Standard Test Input và Relevant Rules, mở rộng thành bộ Structured Test Cases.
- Hỗ trợ 6 nhóm: POSITIVE, NEGATIVE, BOUNDARY, VALIDATION, CRUD, PERMISSION.
- Field-generic (generalization): không đóng cứng vào feature "Add User" —
  test case phái sinh từ machine rules (REQUIRED/FORMAT/UNIQUE/LENGTH/PERMISSION)
  và structured steps của Internal Test Context, nên hoạt động cho mọi loại feature
  (Login/Auth, CRUD, Search/Filter, ...).
"""

from typing import Any, Dict, List, Optional, Tuple
from ..normalizer.input_normalizer import InputNormalizer
from .prompt_templates import TEST_DESIGN_SYSTEM_PROMPT, TEST_DESIGN_USER_PROMPT

# Test data mặc định theo field (deterministic; context có thể override qua test_data)
DEFAULT_FIELD_VALUES = {
    "email": "valid_user@test.com",
    "name": "Nguyen Van A",
    "login": "admin@test.com",
    "passcode": "secret123",
    "password": "secret123",
    "query": "nguyen",
}
INVALID_FORMAT_VALUES = {
    "email": "invalid-email-format",
    "phone": "not-a-phone",
    "url": "not a url",
}
SAMPLE_VALUE = "Sample Value"
BOUNDARY_OVER_LENGTH = "A" * 256


class TestDesignAgent:
    """Agent thiết kế bộ Test Cases đa chiều."""

    def __init__(self, llm_client: Optional[Any] = None):
        """Khởi tạo agent với LLM client tùy chọn."""
        self.llm_client = llm_client

    def design_test_cases(
        self,
        standard_input: Dict[str, Any],
        internal_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Sinh danh sách Structured Test Cases từ Standard Test Input.

        Nếu có Internal Test Context (Bước 3.5) thì dùng machine rules + structured steps,
        nếu không sẽ fallback về heuristic parse text thô (backward compatible).
        Nếu có LLM client thì gọi LLM, nếu không thì dùng heuristic generator chuẩn.
        """
        if self.llm_client:
            return self._generate_with_llm(standard_input)
        return self._generate_deterministic(standard_input, internal_context)

    def _generate_deterministic(
        self,
        standard_input: Dict[str, Any],
        internal_context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Sinh bộ test cases theo 6 nhóm, phái sinh từ rules + steps của feature.

        Mỗi nhóm case chỉ được sinh khi feature có rule/field tương ứng —
        điều kiện để Test Design generalize (Login không có BOUNDARY name,
        Search không có VALIDATION email, ...).
        """
        func_id = standard_input["function_id"]
        feature = standard_input["feature"]
        preconditions = standard_input.get("precondition", [])
        steps = standard_input.get("steps", [])
        expected = standard_input.get("expected_result", ["Success"])
        val_rules = standard_input.get("validation_rules", [])
        biz_rules = standard_input.get("business_rules", [])

        # Dùng Internal Test Context khi có (ưu tiên machine-readable)
        ctx_steps: Optional[List[Dict[str, Any]]] = None
        required_rule: Optional[Dict[str, Any]] = None
        format_rule: Optional[Dict[str, Any]] = None
        unique_rule: Optional[Dict[str, Any]] = None
        length_rule: Optional[Dict[str, Any]] = None
        permission_rule: Optional[Dict[str, Any]] = None

        if internal_context:
            ctx_steps = internal_context.get("steps") or None
            required_rule = InputNormalizer.find_rule(internal_context, "validation", "REQUIRED")
            format_rule = InputNormalizer.find_rule(internal_context, "validation", "FORMAT")
            unique_rule = InputNormalizer.find_rule(internal_context, "validation", "UNIQUE")
            length_rule = InputNormalizer.find_rule(internal_context, "validation", "LENGTH")
            permission_rule = InputNormalizer.find_rule(internal_context, "business", "PERMISSION")

        fill_fields = self._fill_fields(ctx_steps or [])
        test_data = self._build_test_data(standard_input, ctx_steps or [])
        # Thông điệp "không thực thi được" theo hợp đồng nghiệp vụ của feature
        # (mặc định giữ hợp đồng M2: "Entity is not created")
        rejection = str(standard_input.get("rejection_message") or "Entity is not created")

        suite: List[Dict[str, Any]] = []

        # 1. POSITIVE Test Case — dùng đúng luồng nghiệp vụ của feature
        positive_steps = ctx_steps or [
            {"order": idx + 1, "action": "CLICK" if "click" in s.lower() else "FILL" if "fill" in s.lower() or "enter" in s.lower() else "OPEN", "target": s}
            for idx, s in enumerate(steps)
        ]
        suite.append({
            "test_case_id": f"TC-{func_id}-001",
            "function_id": func_id,
            "feature": feature,
            "type": "POSITIVE",
            "priority": "CRITICAL",
            "preconditions": preconditions,
            "test_data": dict(test_data),
            "steps": positive_steps,
            "expected_results": expected,
            "verification_strategy": {"ui": True},
        })

        # 2. VALIDATION: Missing Required Fields (field-generic từ rule)
        # Generalization guard: rule field phải khớp một FILL field thật của feature
        req_rule = required_rule or next((r for r in val_rules if "required" in r.lower()), None)
        req_field = self._rule_field(req_rule) or (fill_fields[0] if fill_fields else None)
        field_applicable = (not ctx_steps) or (req_field in fill_fields)
        if req_rule and req_field and field_applicable:
            rule_meta = self._rule_to_meta(req_rule)
            title = self._field_title(req_field)
            suite.append({
                "test_case_id": f"TC-{func_id}-002",
                "function_id": func_id,
                "feature": feature,
                "type": "VALIDATION",
                "priority": "HIGH",
                "preconditions": preconditions,
                # test_data giữ giá trị GỐC — perturb (rỗng) chỉ nằm ở step override,
                # để các bước setup không bị nhiễm (multi-step workflow)
                "test_data": dict(test_data),
                "steps": self._derive_steps(ctx_steps, {req_field: ""}) or self._fallback_required_steps(),
                "expected_results": [
                    f"{title} required message is displayed",
                    rejection,
                ],
                "verification_strategy": {"ui": True},
                **({"source_rule": rule_meta} if rule_meta else {}),
            })

        # 3. NEGATIVE: Format Violation (theo field của FORMAT/UNIQUE rule)
        fmt_rule = format_rule or next((r for r in val_rules if "format" in r.lower()), None)
        uni_rule = unique_rule or next((r for r in val_rules if "unique" in r.lower()), None)
        neg_rule = fmt_rule or uni_rule
        neg_field = self._rule_field(neg_rule) if neg_rule else None
        neg_applicable = (not ctx_steps) or (neg_field in fill_fields)
        if neg_rule and neg_field and neg_applicable:
            rule_meta = self._rule_to_meta(neg_rule)
            field = neg_field
            bad_value = INVALID_FORMAT_VALUES.get(field, "!!invalid!!")
            suite.append({
                "test_case_id": f"TC-{func_id}-003",
                "function_id": func_id,
                "feature": feature,
                "type": "NEGATIVE",
                "priority": "MEDIUM",
                "preconditions": preconditions,
                "test_data": dict(test_data),
                "steps": self._derive_steps(ctx_steps, {field: bad_value}) or self._fallback_negative_steps(field),
                "expected_results": [
                    f"Invalid {field} format error message is displayed",
                ],
                "verification_strategy": {"ui": True},
                **({"source_rule": rule_meta} if rule_meta else {}),
            })

        # 4. BOUNDARY: Length Check — chỉ sinh khi feature có LENGTH rule (max)
        # hoặc field "name" (hợp đồng demo app: NAME_LENGTH max 255)
        boundary_field, boundary_meta = self._resolve_boundary_field(length_rule, fill_fields)
        boundary_applicable = (not ctx_steps) or (boundary_field in fill_fields)
        if boundary_field and boundary_applicable:
            boundary_steps = self._derive_steps(ctx_steps, {boundary_field: BOUNDARY_OVER_LENGTH})
            if not boundary_steps:
                boundary_steps = [
                    {"order": 1, "action": "OPEN", "target": "Form"},
                    {"order": 2, "action": "FILL", "target": self._field_title(boundary_field), "value": BOUNDARY_OVER_LENGTH},
                    {"order": 3, "action": "SUBMIT", "target": "Submit Button"},
                ]
            suite.append({
                "test_case_id": f"TC-{func_id}-004",
                "function_id": func_id,
                "feature": feature,
                "type": "BOUNDARY",
                "priority": "MEDIUM",
                "preconditions": preconditions,
                "test_data": dict(test_data),
                "steps": boundary_steps,
                "expected_results": [
                    "Maximum length exceeded error is displayed",
                ],
                "verification_strategy": {"ui": True},
                **({"source_rule": boundary_meta} if boundary_meta else {}),
            })

        # 5. PERMISSION: Check Role Access (rule-driven — feature không phân quyền thì bỏ qua)
        perm_rule = permission_rule or next(
            (r for r in biz_rules if "admin" in r.lower() or "role" in r.lower() or "permission" in r.lower()), None
        )
        if perm_rule:
            rule_meta = self._rule_to_meta(perm_rule)
            suite.append({
                "test_case_id": f"TC-{func_id}-005",
                "function_id": func_id,
                "feature": feature,
                "type": "PERMISSION",
                "priority": "HIGH",
                "preconditions": ["Member (non-admin) user is logged in"],
                "test_data": {},
                "steps": [
                    {"order": 1, "action": "OPEN", "target": feature},
                ],
                "expected_results": [
                    "Access Denied (403) or redirect to unauthorized page",
                ],
                "verification_strategy": {"ui": True},
                **({"source_rule": rule_meta} if rule_meta else {}),
            })

        return suite

    # ------------------------------------------------------------------
    # Field/data derivation (generalization helpers)
    # ------------------------------------------------------------------
    @staticmethod
    def _derive_steps(
        ctx_steps: Optional[List[Dict[str, Any]]],
        fill_overrides: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Nhân bản structured steps của feature, ghi đè value các bước FILL
        theo field (VALIDATION/NEGATIVE/BOUNDARY — không hardcode form Add User).

        Khi một field xuất hiện NHIỀU lần (multi-step workflow: form setup +
        form target), override chỉ áp dụng cho lần XUẤT HIỆN CUỐI — bước hành động
        bị kiểm thử — giữ nguyên các bước setup (e.g. tạo user trước khi edit).
        """
        if not ctx_steps:
            return []
        # Vị trí xuất hiện cuối của mỗi FILL field
        last_index: Dict[str, int] = {}
        for idx, step in enumerate(ctx_steps):
            if step.get("action") == "FILL":
                field = str(step.get("target", "")).lower()
                if field:
                    last_index[field] = idx
        derived: List[Dict[str, Any]] = []
        for idx, step in enumerate(ctx_steps):
            new_step = dict(step)
            if new_step.get("action") == "FILL":
                field = str(new_step.get("target", "")).lower()
                if field in fill_overrides and last_index.get(field) == idx:
                    new_step["value"] = fill_overrides[field]
            derived.append(new_step)
        return derived

    @staticmethod
    def _field_title(field: str) -> str:
        """'passcode' -> 'Passcode' (viết hoa cho message oracle)."""
        return field[:1].upper() + field[1:] if field else field

    @staticmethod
    def _fill_fields(ctx_steps: List[Dict[str, Any]]) -> List[str]:
        """Danh sách field (lowercase) xuất hiện ở các bước FILL."""
        return [
            str(s.get("target", "")).lower()
            for s in ctx_steps
            if s.get("action") == "FILL" and s.get("target")
        ]

    @staticmethod
    def _rule_field(rule: Any) -> Optional[str]:
        """Field của machine rule."""
        if isinstance(rule, dict) and rule.get("field"):
            return str(rule["field"])
        return None

    @staticmethod
    def _resolve_boundary_field(
        length_rule: Optional[Dict[str, Any]],
        fill_fields: List[str],
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Chọn field cho BOUNDARY: LENGTH rule constraint max:<n>, hoặc field 'name'.

        Không đủ điều kiện -> (None, None): designer không sinh case BOUNDARY
        vô nghĩa cho feature không có ràng buộc độ dài.
        """
        if isinstance(length_rule, dict):
            constraint = str(length_rule.get("constraint", ""))
            if constraint.startswith("max:") or constraint == "bounded":
                return length_rule.get("field") or "name", TestDesignAgent._rule_to_meta(length_rule)
        if "name" in fill_fields:
            return "name", None
        return None, None

    @staticmethod
    def _build_test_data(
        standard_input: Dict[str, Any],
        ctx_steps: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Test data POSITIVE: context test_data ưu tiên, sau đó default theo field."""
        data = {str(k).lower(): v for k, v in (standard_input.get("test_data") or {}).items()}
        for step in ctx_steps:
            if step.get("action") == "FILL":
                field = str(step.get("target", "")).lower()
                if field and field not in data:
                    data[field] = DEFAULT_FIELD_VALUES.get(field, SAMPLE_VALUE)
        return data

    @staticmethod
    def _fallback_required_steps() -> List[Dict[str, Any]]:
        return [
            {"order": 1, "action": "OPEN", "target": "Form"},
            {"order": 2, "action": "FILL", "target": "Name", "value": "Nguyen Van A"},
            {"order": 3, "action": "SUBMIT", "target": "Submit Button"},
        ]

    @staticmethod
    def _fallback_negative_steps(field: str) -> List[Dict[str, Any]]:
        value = INVALID_FORMAT_VALUES.get(field, "invalid-value")
        return [
            {"order": 1, "action": "OPEN", "target": "Form"},
            {"order": 2, "action": "FILL", "target": TestDesignAgent._field_title(field), "value": value},
            {"order": 3, "action": "SUBMIT", "target": "Submit Button"},
        ]

    @staticmethod
    def _rule_to_meta(rule: Any) -> Optional[Dict[str, Any]]:
        """Chuyển machine rule (Bước 3.5) thành metadata traceability gắn vào test case."""
        if isinstance(rule, dict) and "kind" in rule:
            return {
                "rule_id": rule.get("rule_id"),
                "kind": rule.get("kind"),
                "field": rule.get("field"),
                "constraint": rule.get("constraint"),
                "source_text": rule.get("source_text"),
            }
        return None

    def _generate_with_llm(self, standard_input: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Thực thi gọi LLM để sinh Structured Test Cases (khi có LLM runtime)."""
        prompt = TEST_DESIGN_USER_PROMPT.format(
            function_id=standard_input.get("function_id"),
            feature=standard_input.get("feature"),
            preconditions=standard_input.get("precondition"),
            steps=standard_input.get("steps"),
            expected_results=standard_input.get("expected_result"),
            business_rules=standard_input.get("business_rules", []),
            validation_rules=standard_input.get("validation_rules", []),
        )
        # Giả định LLM trả về JSON cấu trúc
        return self._generate_deterministic(standard_input)
