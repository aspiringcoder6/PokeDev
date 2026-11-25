"""Input Normalizer (Bước 3.5).

Nhiệm vụ:
- Chuẩn hóa Standard Test Input (5 trường từ ADLC Memory) thành Internal Test Context
  để các module downstream (Designer, Validator, Generator, Healer, Verification)
  đọc hiểu dữ liệu máy hóa thay vì text thô.
- Hoàn toàn deterministic (Zero-LLM): pattern matching đa ngôn ngữ (English + Tiếng Việt).
- Hợp đồng biên giới (5 trường) không thay đổi; mọi enrichment chỉ tồn tại nội bộ Agent.

Đầu ra tuân thủ schemas/internal_test_context.schema.json:
- identity: function_id + feature
- rules.business / rules.validation: machine rules (kind, field, constraint, source_text)
- steps: hành động cấu trúc (OPEN/CLICK/FILL/SELECT/SUBMIT/WAIT/ASSERT) + target
- verification: mục tiêu xác minh UI/API/DB suy ra từ expected_result
- traceability: nguồn + danh sách rule chưa parse được (kind UNKNOWN)
"""

import re
from typing import Any, Dict, List, Optional

from ..validators.test_case_validator import TestCaseValidator


class InputNormalizer:
    """Chuẩn hóa Standard Test Input thành Internal Test Context (Bước 3.5)."""

    # Thứ tự dò hành động: compound SUBMIT trước CLICK, FILL trước SELECT, v.v.
    ACTION_KEYWORDS = [
        ("OPEN", ["open", "navigate", "go to", "goto", "visit", "truy cập", "mở", "vào trang"]),
        # PRESS phải trước FILL/CLICK: "nhấn Enter"/"press Enter" là phím, không phải fill lẫn click nút
        ("PRESS", ["press enter", "press the enter", "nhấn enter", "ấn enter", "bấm enter"]),
        ("FILL", ["fill", "enter", "input", "type ", "nhập", "gõ", "điền"]),
        ("SUBMIT", ["submit", "save", "lưu", "gửi", "login", "đăng nhập", "đăng ký", "send"]),
        ("SELECT", ["select", "choose", "pick", "chọn"]),
        ("CLICK", ["click", "press", "tap", "bấm", "nhấn", "ấn"]),
        ("WAIT", ["wait", "chờ", "đợi"]),
        ("ASSERT", ["verify", "check", "assert", "expect", "kiểm tra", "xác minh", "xác nhận"]),
    ]

    # Từ ghép (compound): click/bấm + save/submit/login → SUBMIT thay vì CLICK
    COMPOUND_SUBMIT_TRIGGERS = ["click", "press", "bấm", "nhấn", "ấn", "tap"]

    # Từ điển nhận diện field từ tên rule
    FIELD_KEYWORDS = {
        "email": ["email"],
        "name": ["full name", "fullname", "name", "tên"],
        "username": ["username", "user name", "tên đăng nhập"],
        "login": ["login", "đăng nhập"],
        "passcode": ["passcode"],
        "password": ["password", "mật khẩu"],
        "phone": ["phone", "số điện thoại", "điện thoại"],
        "address": ["address", "địa chỉ"],
        "search": ["search", "query", "tìm kiếm"],
    }

    # Kind rule: (kind, keywords dò) — thứ tự ưu tiên khi quét
    RULE_KIND_KEYWORDS = [
        ("PERMISSION", ["admin", "role", "permission", "quyền", "only ", "chỉ "]),
        ("REQUIRED", ["required", "bắt buộc", "không được để trống", "không được bỏ trống", "must be filled", "not empty"]),
        ("UNIQUE", ["unique", "duy nhất", "trùng", "already exists", "đã tồn tại"]),
        ("FORMAT", ["format", "định dạng", "valid", "hợp lệ", "pattern"]),
        ("LENGTH", ["length", "độ dài", "ký tự", "character", "maximum", "minimum", "tối đa", "tối thiểu", "tối đa"]),
    ]

    # Expected result mang tính phủ định (cần ABSENT thay vì VISIBLE)
    ABSENT_PATTERNS = [
        "not created", "not displayed", "not shown", "not visible", "not found",
        "không được tạo", "không hiển thị", "không xuất hiện", "không tồn tại",
    ]

    @classmethod
    def normalize(
        cls,
        standard_input: Dict[str, Any],
        business_rules: Optional[List[str]] = None,
        validation_rules: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Chuẩn hóa Standard Test Input (5 trường) thành Internal Test Context.

        Args:
            standard_input: Hợp đồng biên 5 trường (function_id, feature, precondition, steps, expected_result)
            business_rules: Business rules từ Relevant Requirement Context (nếu có)
            validation_rules: Validation rules từ Relevant Requirement Context (nếu có)

        Returns:
            Dict cấu trúc Internal Test Context (xem schemas/internal_test_context.schema.json)
        """
        std = standard_input or {}
        biz_rules = [str(r) for r in (business_rules or std.get("business_rules") or [])]
        val_rules = [str(r) for r in (validation_rules or std.get("validation_rules") or [])]

        raw_steps = std.get("steps") or []
        raw_expected = std.get("expected_result") or []

        parsed_biz, unparsed_biz = cls.parse_rules(biz_rules, prefix="BR")
        parsed_val, unparsed_val = cls.parse_rules(val_rules, prefix="VR")

        return {
            "identity": {
                "function_id": std.get("function_id", ""),
                "feature": std.get("feature", ""),
            },
            "preconditions": list(std.get("precondition") or []),
            "rules": {
                "business": parsed_biz,
                "validation": parsed_val,
            },
            "steps": cls.normalize_steps(raw_steps),
            "verification": cls.normalize_expected_results(raw_expected),
            "traceability": {
                "source": "standard_test_input",
                "unparsed_rules": unparsed_biz + unparsed_val,
            },
        }

    # ------------------------------------------------------------------
    # Steps: text thô -> action cấu trúc
    # ------------------------------------------------------------------
    @classmethod
    def normalize_steps(cls, steps: List[str]) -> List[Dict[str, Any]]:
        """Chuyển danh sách bước dạng text thành các bước action có cấu trúc.

        Args:
            steps: Danh sách bước nghiệp vụ dạng văn bản

        Returns:
            Danh sách {order, action, target, value, raw_text}
        """
        normalized: List[Dict[str, Any]] = []
        for idx, raw in enumerate(steps):
            text = str(raw).strip()
            action = cls._detect_action(text)
            target = cls._extract_target(text, action)
            value = cls._extract_value(text)

            normalized.append({
                "order": idx + 1,
                "action": action,
                "target": target,
                "value": value,
                "raw_text": text,
            })
        return normalized

    @classmethod
    def _detect_action(cls, text: str) -> str:
        """Dò action theo bảng từ khóa đa ngôn ngữ (deterministic, có thứ tự ưu tiên)."""
        t = text.lower()

        # Compound check: click + save/submit/login -> SUBMIT (ưu tiên cao hơn CLICK)
        if any(w in t for w in cls.COMPOUND_SUBMIT_TRIGGERS) and any(
            w in t for w in ["submit", "save", "lưu", "gửi", "login", "đăng nhập", "đăng ký", "send"]
        ):
            return "SUBMIT"

        for action, keywords in cls.ACTION_KEYWORDS:
            if any(w in t for w in keywords):
                return action

        # Mặc định: coi như điều hướng/mở giao diện
        return "OPEN"

    @classmethod
    def _extract_target(cls, text: str, action: Optional[str] = None) -> str:
        """Loại bỏ động từ của chính action đó để lấy target (không xóa chéo động từ khác).

        Ví dụ: "Fill Login" (FILL) -> chỉ bỏ "fill" -> target "Login",
        không xóa "login" (từ thuộc SUBMIT) làm target bị rỗng.
        Literal value trong ngoặc kép/don ("Fill Name 'Nguyen Van B'") được tách
        riêng vào `value` -> không được lẫn vào target (gây hỏng locator JS).
        """
        target = text.strip().rstrip(".,;:")

        # PRESS không có element: target chuẩn hóa là tên phím
        if action == "PRESS":
            return "Enter"

        # Literal values đã do _extract_value trích -> loại khỏi target
        target = re.sub(r"'[^']*'|\"[^\"]*\"", " ", target)

        keywords_map = dict(cls.ACTION_KEYWORDS)
        if action == "SUBMIT":
            # Compound "Click Save"/"Bấm nút Gửi": chỉ bỏ động từ bấm, giữ tên nút
            lowered = target.lower()
            triggers = [w for w in cls.COMPOUND_SUBMIT_TRIGGERS if w in lowered]
            if triggers:
                keywords = triggers
            else:
                keywords = dict(cls.ACTION_KEYWORDS).get("SUBMIT", [])
        elif action:
            keywords = dict(cls.ACTION_KEYWORDS).get(action, [])
        else:
            keywords = [kw for _, kws in cls.ACTION_KEYWORDS for kw in kws]

        for kw in keywords:
            if kw in target.lower():
                target = re.compile(re.escape(kw), re.IGNORECASE).sub(" ", target)

        # Bỏ từ nối/quán từ phổ biến EN + VI
        for prep in [" the ", " a ", " an ", " to ", " on ", " in ", " of ",
                     " vào ", " trang ", " nút ", " nút", " trong ", " tại ", " của "]:
            target = target.replace(prep, " ")

        target = re.sub(r"\s+", " ", target).strip(" ,-:")
        target = re.sub(r"^(nút|button|btn)\s+", "", target, flags=re.IGNORECASE).strip()
        return target if target else text.strip()

    @classmethod
    def _extract_value(cls, text: str) -> Any:
        """Trích giá trị literal trong step nếu có (e.g. Fill Email 'a@b.com').

        Value quoted RỖNG ('') là hợp lệ (VALIDATION: bắt buộc) — regex dùng
        * thay vì + để không làm mất case rỗng.
        """
        match = re.search(r"['\"]([^'\"]*)['\"]", text)
        return match.group(1) if match else None

    # ------------------------------------------------------------------
    # Rules: text thô -> machine rules
    # ------------------------------------------------------------------
    @classmethod
    def parse_rules(cls, rules: List[str], prefix: str = "BR") -> Any:
        """Chuyển danh sách rule dạng text thành machine rules có cấu trúc.

        Args:
            rules: Danh sách rule dạng văn bản
            prefix: Tiền tố rule_id ("BR" business, "VR" validation)

        Returns:
            Tuple (danh sách machine rules, danh sách rule chưa parse được)
        """
        machine_rules: List[Dict[str, Any]] = []
        unparsed: List[str] = []

        for idx, raw in enumerate(rules):
            text = str(raw).strip()
            kind = cls._detect_rule_kind(text)
            machine_rules.append({
                "rule_id": f"{prefix}{idx + 1:02d}",
                "kind": kind,
                "field": cls._detect_field(text),
                "constraint": cls._extract_constraint(kind, text),
                "source_text": text,
            })
            if kind == "UNKNOWN":
                unparsed.append(text)

        return machine_rules, unparsed

    @classmethod
    def _detect_rule_kind(cls, text: str) -> str:
        """Phân loại rule theo bảng kind (thứ tự ưu tiên: PERMISSION > REQUIRED > UNIQUE > FORMAT > LENGTH)."""
        t = text.lower()
        for kind, keywords in cls.RULE_KIND_KEYWORDS:
            if any(w in t for w in keywords):
                return kind
        return "UNKNOWN"

    @classmethod
    def _detect_field(cls, text: str) -> Any:
        """Nhận diện field mà rule áp dụng (email, name, password...)."""
        t = text.lower()
        for field, keywords in cls.FIELD_KEYWORDS.items():
            if any(w in t for w in keywords):
                return field
        return None

    @classmethod
    def _extract_constraint(cls, kind: str, text: str) -> str:
        """Suy ra constraint chuẩn hóa theo kind."""
        t = text.lower()

        if kind == "REQUIRED":
            return "not_empty"
        if kind == "UNIQUE":
            return "unique"
        if kind == "PERMISSION":
            if "admin" in t:
                return "role=eq:admin"
            return "restricted_access"
        if kind == "FORMAT":
            if "email" in t:
                return "pattern:email"
            if "phone" in t:
                return "pattern:phone"
            if "url" in t:
                return "pattern:url"
            return "pattern:custom"
        if kind == "LENGTH":
            numbers = re.findall(r"\d+", text)
            if numbers:
                is_max = any(
                    w in t for w in ["max", "maximum", "tối đa", "length", " at most", "no more than"]
                )
                return f"max:{numbers[-1]}" if is_max else f"min:{numbers[-1]}"
            return "bounded"
        return "review_required"

    # ------------------------------------------------------------------
    # Expected results -> verification targets
    # ------------------------------------------------------------------
    @classmethod
    def normalize_expected_results(cls, expected_results: List[str]) -> Dict[str, Any]:
        """Chuyển expected_result dạng text thành mục tiêu xác minh UI/API/DB.

        Args:
            expected_results: Danh sách kết quả mong đợi dạng văn bản

        Returns:
            Dict {ui: [{type, value}], api: null, db: null} — API/DB để null chờ bổ sung
        """
        ui_targets: List[Dict[str, str]] = []
        for exp in expected_results:
            text = str(exp).strip()
            t = text.lower()
            is_absent = any(p in t for p in cls.ABSENT_PATTERNS)
            ui_targets.append({
                "type": "TEXT_ABSENT" if is_absent else "TEXT_VISIBLE",
                "value": text,
            })

        return {
            "ui": ui_targets,
            "api": None,
            "db": None,
        }

    # ------------------------------------------------------------------
    # Tiện ích cho downstream
    # ------------------------------------------------------------------
    @classmethod
    def find_rule(cls, context: Dict[str, Any], domain: str, kind: str, field: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Tìm machine rule đầu tiên khớp kind/field — dùng cho Designer & Validator.

        Args:
            context: Internal Test Context
            domain: "business" hoặc "validation"
            kind: Loại rule (REQUIRED, FORMAT, UNIQUE, PERMISSION, LENGTH)
            field: Field cụ thể (tùy chọn)

        Returns:
            Machine rule hoặc None
        """
        for rule in context.get("rules", {}).get(domain, []):
            if rule["kind"] != kind:
                continue
            if field is not None and rule.get("field") != field:
                continue
            return rule
        return None

    @classmethod
    def validate_internal_context(cls, context: Dict[str, Any]) -> Dict[str, Any]:
        """Kiểm tra Internal Test Context hợp lệ tối thiểu trước khi đưa vào Designer.

        Returns:
            {"valid": bool, "errors": [str]}
        """
        errors: List[str] = []

        identity = context.get("identity", {})
        if not identity.get("function_id"):
            errors.append("identity.function_id is required")
        if not identity.get("feature"):
            errors.append("identity.feature is required")

        steps = context.get("steps") or []
        if not steps:
            errors.append("steps must contain at least 1 structured step")
        else:
            valid_actions = TestCaseValidator.VALID_ACTIONS
            for step in steps:
                if step.get("action") not in valid_actions:
                    errors.append(
                        f"Step {step.get('order')} has unsupported action '{step.get('action')}'"
                    )

        verification = context.get("verification") or {}
        if not verification.get("ui"):
            errors.append("verification.ui must contain at least 1 target")

        return {"valid": len(errors) == 0, "errors": errors}
