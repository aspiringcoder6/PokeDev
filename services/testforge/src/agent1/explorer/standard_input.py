"""Chuẩn 5 trường (Standard Test Input) — hợp đồng chung cho mọi đường sinh test.

Quy ước kiến trúc (docs/architecture/04_agent1_functional.md Bước 3): input 5 trường
function_id / feature / precondition / steps / expected_result, schema
`schemas/standard_test_input.schema.json`.

Hai chiều:
- 5 trường -> Gherkin bổ sung (tags @TC-*/@FUNC-*/@REQ-*) làm entry explorer
  (browser-first từ tài liệu 5 trường).
- Gherkin -> 5 trường (derive) — mọi kịch bản sinh test phải truy vết được về
  chuẩn 5 trường; không derive được (thiếu steps/expected) -> Promotion Gate chặn.
"""
import json
import re
from pathlib import Path

import jsonschema

_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "schemas" / "standard_test_input.schema.json"


def validate_standard_input(std):
    """Validate tài liệu 5 trường. Returns: list thông báo lỗi (rỗng = hợp lệ)."""
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    return [e.message for e in sorted(validator.iter_errors(std), key=str)]


def slug_upper(text):
    """'Add User' -> 'USER-ADD' (convention FUNC-{MODULE} của kiến trúc)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(text)).strip("-").upper()
    return slug or "UNKNOWN"


def build_feature_from_standard_input(std):
    """5 trường -> Gherkin bổ sung: tags ID + precondition (mô tả) + When steps + Then oracle.

    Precondition KHÔNG thành step executable: điều kiện phiên (vd "Admin is logged
    in") do explorer đảm bảo bằng per-case login (actor), ghi trong mô tả feature.
    """
    scenario_name = std["feature"]
    function_id = std.get("function_id") or "FUNC-{0}".format(slug_upper(std["feature"]))
    tags = ["@{0}".format(function_id)]
    lines = ["{0}".format(" ".join(tags)),
             "Feature: {0}".format(scenario_name)]
    if std.get("precondition"):
        lines.append("")
        lines.append("  Precondition:")
        for item in std["precondition"]:
            lines.append("  - {0}".format(item))
    lines.append("")
    lines.append("  Scenario: {0} [{1}]".format(scenario_name, function_id))
    steps, expected = std["steps"], std["expected_result"]
    if len(steps) == len(expected):
        # Test design chuẩn: expected_result[i] là kết quả mong đợi của steps[i]
        # (VD menu -> thấy danh sách; click bản ghi -> thấy chi tiết). Ghép xen kẽ
        # để ASSERT chạy đúng thời điểm. Keyword tường minh When/Then mỗi dòng —
        # "And" kế thừa keyword trước đó sẽ làm derive gộp nhầm action vào expected.
        for index in range(len(steps)):
            lines.append("    When {0}".format(steps[index]))
            lines.append("    Then {0}".format(expected[index]))
    else:
        for index, step in enumerate(steps):
            lines.append("    {0} {1}".format("When" if index == 0 else "And", step))
        for index, expected_item in enumerate(expected):
            lines.append("    {0} {1}".format("Then" if index == 0 else "And", expected_item))
    return "\n".join(lines) + "\n"


def derive_standard_input(scenario, feature_name=None):
    """Scenario đã parse -> (5-field dict, list lỗi). Gọi validate trước khi dùng."""
    steps = [s["text"] for s in scenario["steps"] if s["keyword"] == "When"]
    expected = [s["text"] for s in scenario["steps"] if s["keyword"] == "Then"]
    precondition = [s["text"] for s in scenario["steps"] if s["keyword"] == "Given"]
    std = {
        "function_id": scenario.get("function_id")
        or "FUNC-{0}".format(slug_upper(feature_name or scenario["name"])),
        "feature": feature_name or scenario.get("feature_name") or scenario["name"],
        "precondition": precondition,
        "steps": steps,
        "expected_result": expected,
    }
    return std, validate_standard_input(std)


def write_standard_feature(std, out_path):
    """Validate rồi ghi feature bổ sung cho explorer. Raise SystemExit-like ValueError."""
    errors = validate_standard_input(std)
    if errors:
        raise ValueError("Invalid standard input: " + "; ".join(errors[:3]))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_feature_from_standard_input(std), encoding="utf-8")
    return out_path


def load_standard_input(path):
    """Đọc tài liệu 5 trường (utf-8-sig, chống BOM)."""
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))
