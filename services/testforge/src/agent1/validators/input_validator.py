"""Test Input Validator (Bước 4).

Kiểm tra Standard Test Input có đủ điều kiện để Agent sinh test hay không.
Quy tắc: Deterministic validation, KHÔNG dùng LLM để đoán các trường bị thiếu.
- IN001: Function ID required
- IN002: Feature required
- IN003: Steps must not be empty
- IN004: Expected Result required
- IN005: Unsupported input version / schema format
"""

from typing import Any, Dict, List


class TestInputValidator:
    """Bộ kiểm tra tính hợp lệ của Standard Test Input."""

    REQUIRED_FIELDS = ["function_id", "feature", "precondition", "steps", "expected_result"]

    @classmethod
    def validate(cls, test_input: Dict[str, Any]) -> Dict[str, Any]:
        """Thực hiện kiểm tra input contract 5 trường theo quy tắc IN001 - IN005.

        Args:
            test_input: Dictionary chứa dữ liệu đầu vào

        Returns:
            Dict có dạng:
            {
                "valid": bool,
                "errors": [{"code": str, "field": str, "message": str}]
            }
        """
        errors: List[Dict[str, str]] = []

        if not isinstance(test_input, dict):
            return {
                "valid": False,
                "errors": [
                    {
                        "code": "IN005",
                        "field": "root",
                        "message": "Input must be a valid JSON object/dictionary",
                    }
                ],
            }

        # IN001: Function ID required
        func_id = test_input.get("function_id")
        if not func_id or not isinstance(func_id, str) or not func_id.strip():
            errors.append({
                "code": "IN001",
                "field": "function_id",
                "message": "Function ID is required and must be a non-empty string",
            })

        # IN002: Feature required
        feature = test_input.get("feature")
        if not feature or not isinstance(feature, str) or not feature.strip():
            errors.append({
                "code": "IN002",
                "field": "feature",
                "message": "Feature is required and must be a non-empty string",
            })

        # IN003: Steps must not be empty
        steps = test_input.get("steps")
        if not isinstance(steps, list) or len(steps) < 1:
            errors.append({
                "code": "IN003",
                "field": "steps",
                "message": "Steps must be a non-empty list of steps",
            })
        elif any(not isinstance(s, str) or not s.strip() for s in steps):
            errors.append({
                "code": "IN003",
                "field": "steps",
                "message": "Each step must be a non-empty string",
            })

        # IN004: Expected Result required
        expected = test_input.get("expected_result")
        if not isinstance(expected, list) or len(expected) < 1:
            errors.append({
                "code": "IN004",
                "field": "expected_result",
                "message": "Expected Result is required and must contain at least 1 outcome",
            })
        elif any(not isinstance(e, str) or not e.strip() for e in expected):
            errors.append({
                "code": "IN004",
                "field": "expected_result",
                "message": "Each expected result item must be a non-empty string",
            })

        # Preconditions check
        preconditions = test_input.get("precondition")
        if preconditions is not None and not isinstance(preconditions, list):
            errors.append({
                "code": "IN005",
                "field": "precondition",
                "message": "Precondition must be a list of conditions",
            })

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }
