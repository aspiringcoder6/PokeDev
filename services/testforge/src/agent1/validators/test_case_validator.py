"""Test Case Validator (Bước 7).

Nhiệm vụ:
- Kiểm tra tính hợp lệ của Structured Test Cases do AI sinh ra.
- Kiểm tra các trường bắt buộc, kiểu dữ liệu, các action được hỗ trợ.
- Kiểm tra trùng lặp (deduplication).
- Phát hiện mâu thuẫn nghiệp vụ (Contradiction Detection) giữa input rules và test case expected results.
"""

from typing import Any, Dict, List, Optional, Set


class TestCaseValidator:
    """Bộ kiểm tra tính hợp lệ và tính nhất quán của Test Case do AI sinh."""

    VALID_TYPES = {"POSITIVE", "NEGATIVE", "BOUNDARY", "VALIDATION", "CRUD", "PERMISSION"}
    VALID_ACTIONS = {"OPEN", "CLICK", "FILL", "SELECT", "UPLOAD", "SUBMIT", "WAIT", "ASSERT", "PRESS"}

    @classmethod
    def validate_test_case(
        cls,
        test_case: Dict[str, Any],
        expected_function_id: Optional[str] = None,
        input_rules: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Xác thực một Test Case riêng lẻ.

        Args:
            test_case: Cấu trúc Structured Test Case
            expected_function_id: function_id mong đợi để đối chiếu
            input_rules: Danh sách business/validation rules từ input để kiểm tra mâu thuẫn

        Returns:
            Dict có dạng {"valid": bool, "errors": [{"code": str, "message": str}]}
        """
        errors: List[Dict[str, str]] = []

        # 1. Kiểm tra test_case_id
        tc_id = test_case.get("test_case_id")
        if not tc_id or not isinstance(tc_id, str):
            errors.append({"code": "TC001", "message": "test_case_id is required and must be a string"})

        # 2. Kiểm tra function_id
        func_id = test_case.get("function_id")
        if not func_id or not isinstance(func_id, str):
            errors.append({"code": "TC002", "message": "function_id is required and must be a string"})
        elif expected_function_id and func_id != expected_function_id:
            errors.append({
                "code": "TC002_MISMATCH",
                "message": f"function_id '{func_id}' does not match expected '{expected_function_id}'",
            })

        # 3. Kiểm tra test type
        tc_type = test_case.get("type")
        if tc_type not in cls.VALID_TYPES:
            errors.append({
                "code": "TC003",
                "message": f"Invalid test type '{tc_type}'. Must be one of {sorted(cls.VALID_TYPES)}",
            })

        # 4. Kiểm tra steps
        steps = test_case.get("steps")
        if not isinstance(steps, list) or len(steps) < 1:
            errors.append({"code": "TC004", "message": "steps must be a non-empty list"})
        else:
            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    errors.append({"code": "TC004_MALFORMED", "message": f"Step {i+1} must be an object"})
                    continue
                action = step.get("action")
                if action not in cls.VALID_ACTIONS:
                    errors.append({
                        "code": "TC004_ACTION",
                        "message": f"Step {i+1} has unsupported action '{action}'. Supported: {sorted(cls.VALID_ACTIONS)}",
                    })

        # 5. Kiểm tra expected_results
        expected_results = test_case.get("expected_results")
        if not isinstance(expected_results, list) or len(expected_results) < 1:
            errors.append({"code": "TC005", "message": "expected_results must be a non-empty list of strings"})

        # 6. Contradiction Detection (Phát hiện mâu thuẫn với input rules)
        contradiction = cls._detect_contradiction(test_case, input_rules or [])
        if contradiction:
            errors.append({
                "code": "TC_CONTRADICTION",
                "message": contradiction,
            })

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }

    @classmethod
    def validate_test_suite(
        cls,
        test_cases: List[Dict[str, Any]],
        expected_function_id: Optional[str] = None,
        input_rules: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Xác thực toàn bộ danh sách Test Cases (bao gồm deduplication)."""
        suite_errors: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()

        for tc in test_cases:
            tc_id = tc.get("test_case_id", "")
            if tc_id in seen_ids:
                suite_errors.append({
                    "test_case_id": tc_id,
                    "code": "TC_DUPLICATE_ID",
                    "message": f"Duplicate test_case_id '{tc_id}' found in test suite",
                })
            seen_ids.add(tc_id)

            res = cls.validate_test_case(tc, expected_function_id, input_rules)
            if not res["valid"]:
                for err in res["errors"]:
                    suite_errors.append({
                        "test_case_id": tc_id,
                        **err,
                    })

        return {
            "valid": len(suite_errors) == 0,
            "errors": suite_errors,
            "total_validated": len(test_cases),
        }

    @classmethod
    def _detect_contradiction(
        cls, test_case: Dict[str, Any], input_rules: List[str]
    ) -> Optional[str]:
        """Phát hiện mâu thuẫn logic giữa test case và input rules."""
        test_data = test_case.get("test_data", {})
        expected_results = [str(r).lower() for r in test_case.get("expected_results", [])]
        rules_text = " ".join(input_rules).lower()

        # Rule 1: Email required, but email is empty/missing in test_data AND expected result says successful
        if "email is required" in rules_text or "email required" in rules_text:
            if "email" in test_data and (test_data["email"] == "" or test_data["email"] is None):
                # Expecting rejection or error
                for exp in expected_results:
                    if any(success_word in exp for success_word in [
                        "created successfully", "success", "user is created", "welcome"
                    ]) and not any(err_word in exp for err_word in ["error", "required", "not created", "fail"]):
                        return (
                            "Contradiction detected: Rule requires Email, but test_data has empty email "
                            f"while expected_result claims success: '{exp}'"
                        )

        # Rule 2: Permission check - Only Admin, but actor is Member/Guest and expected result is success
        if "only admin" in rules_text:
            preconditions = " ".join([str(p).lower() for p in test_case.get("preconditions", [])])
            if "member" in preconditions or "guest" in preconditions:
                for exp in expected_results:
                    if "allowed" in exp or "created successfully" in exp or "permitted" in exp:
                        return (
                            "Contradiction detected: Rule restricts to Admin only, but preconditions "
                            f"specify non-admin while expected_result allows action: '{exp}'"
                        )

        return None
