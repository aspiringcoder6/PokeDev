"""Importer test spec 5 cột: Function ID | Feature | Precondition | Steps | Expected Result.

Chuyển tài liệu test truyền thống (CSV/TSV/JSON/XLSX) thành suite draft cho staging:
- Zero-LLM: chỉ pattern cơ khí; thứ không map chắc chắn thì thành WARNING, không đoán.
- Output luôn review_status: "unreviewed" — phải qua HITL duyệt trước khi chạy gate.
- Locator ưu tiên tái sử dụng profile đã review; thiếu thì sinh locator draft
  (tiền tố "draft-") kèm chiến lược theo locator policy (role+name trước, css sau).
- Truy vết: Function ID -> test_case_id + requirement_refs + source_ref oracle.
"""
import csv
import json
import re
import unicodedata
from pathlib import Path

_COLUMN_ALIASES = {
    "function_id": ("function id", "functionid", "ma tc", "tc id", "id", "ma function"),
    "feature": ("feature", "tinh nang", "chuc nang", "feature name"),
    "precondition": ("precondition", "pre-condition", "dieu kien", "dieu kien tien quyet",
                     "tien dieu kien"),
    "steps": ("steps", "step", "buoc", "cac buoc", "test steps"),
    "expected": ("expected result", "expected", "ket qua mong doi", "ky vong",
                 "ket qua"),
}

_NUMBERING_RE = re.compile(r"^[\s]*(?:\d+[.)\]]|[-*•])\s+(.*)$")
_QUOTED_RE = re.compile(r'"([^"]+)"')
_FILL_VALUE_RE = re.compile(r'(?:with|with value|gia tri|value|là|la|:)\s*"([^"]*)"')
_API_RE = re.compile(
    r"\b(GET|POST|PUT|PATCH|DELETE)\b.*?(/[A-Za-z0-9_\-{}/.$]+).*?\b(\d{3})\b", re.IGNORECASE)
# path có thể đứng sau dấu nháy: URL là "/login"
_URL_PATH_RE = re.compile(r'(?:^|[\s"\x27])(/[A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-{}]+)*)')
_STATUS_ONLY_RE = re.compile(r"\b([1-5]\d{2})\b")

# Hint khớp route tiếng Việt -> key trong profile.routes (heuristic, sai thì WARNING chứ không đoán)
_ROUTE_HINTS = {
    "projects": ("du an", "project"),
    "login": ("dang nhap", "login"),
    "dashboard": ("tong quan", "dashboard"),
    "members": ("thanh vien", "member"),
    "tasks": ("nhiem vu", "task"),
    "board": ("kanban", "board"),
}


def _slug(text):
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", str(text).lower())
                  .encode("ascii", "ignore").decode().strip()).strip("-")
    return slug or "item"


def _norm(value):
    return " ".join(str(value or "").split())


def _alias_key(header):
    key = unicodedata.normalize("NFKD", _norm(header).lower()).encode(
        "ascii", "ignore").decode().strip()
    for canonical, aliases in _COLUMN_ALIASES.items():
        if key in aliases or key == canonical:
            return canonical
    return None


def parse_spec(path):
    """Đọc file spec -> list dict 5 cột chuẩn hoá. Ném ValueError nếu thiếu cột bắt buộc."""
    path = Path(path)
    suffix = path.suffix.lower()
    raw_rows = []
    if suffix in (".csv", ".tsv", ".txt"):
        text = path.read_text(encoding="utf-8-sig")
        delimiter = "\t" if suffix == ".tsv" else (";" if text.count(";") > text.count(",") else ",")
        raw_rows = []
        for row in csv.DictReader(text.splitlines(), delimiter=delimiter, restkey="__extra__"):
            if row.get("__extra__"):
                raise ValueError(
                    "Row has more fields than header — fields containing quotes/commas/"
                    "semicolons must be wrapped in double quotes (RFC4180): {0}".format(
                        str(row.get("__extra__"))[:120]))
            raw_rows.append(row)
    elif suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, list):
            raise ValueError("JSON spec must be a list of objects")
        raw_rows = data
    elif suffix == ".xlsx":
        try:
            import openpyxl
        except ImportError as exc:
            raise ValueError("Install openpyxl to read .xlsx (pip install openpyxl)") from exc
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active
        rows = list(sheet.iter_rows(values_only=True))
        headers = [str(cell or "").strip() for cell in (rows[0] if rows else [])]
        raw_rows = [
            {headers[i]: cell for i, cell in enumerate(row) if i < len(headers)}
            for row in rows[1:]
        ]
    else:
        raise ValueError("Unsupported spec format: {0}".format(suffix))

    if not raw_rows:
        raise ValueError("Spec has no data rows")

    mapped, missing = [], set()
    for index, raw in enumerate(raw_rows):
        row = {}
        for header, value in raw.items():
            key = _alias_key(header)
            if key:
                row[key] = _norm(value)
        absent = [c for c in ("function_id", "feature", "steps", "expected")
                  if not row.get(c)]
        if absent:
            missing.add("row {0} missing: {1}".format(index + 2, ", ".join(absent)))
        mapped.append(row)
    if missing:
        raise ValueError("Unmappable columns/rows: {0}".format("; ".join(sorted(missing))))
    return mapped


def _resolve_locator(profile_locators, new_locators, target, action, counter):
    """Tái sử dụng locator đã review nếu khớp; không thì sinh locator draft."""
    for key, locator in profile_locators.items():
        if locator.get("name", "") == target and locator.get("by") == "role":
            return key, False
        if str(locator.get("value", "")) == target:
            return key, False
    for key, locator in new_locators.items():
        if locator.get("name", "") == target and locator.get("by") == "role":
            return key, False
        if str(locator.get("value", "")) == target:
            return key, False
    counter["n"] += 1
    key = "draft-{0}-{1}".format(_slug(target), counter["n"])
    new_locators[key] = {
        "by": "role",
        "value": "button" if action in ("CLICK", "SUBMIT") else "textbox",
        "name": target,
        "draft": True,
    }
    return key, True


def _parse_precondition(text, profile, warnings):
    steps, actor = [], None
    lowered = text.lower()
    for role_name, actor_cfg in (profile or {}).get("actors", {}).items():
        if actor_cfg.get("anonymous"):
            continue
        if _slug(role_name) and re.search(r"\b{0}\b".format(re.escape(role_name)), lowered):
            actor = role_name
            break
        hints = {"admin": ("admin", "quản trị", "quan tri"),
                 "member": ("member", "thành viên", "thanh vien")}
        if any(h in lowered for h in hints.get(role_name, ())):
            actor = role_name
            break
    if "đăng nhập" in lowered or "logged in" in lowered or "login" in lowered:
        if actor is None:
            named = [k for k, v in (profile or {}).get("actors", {}).items()
                     if not v.get("anonymous")]
            actor = named[0] if named else None
    else:
        actor = None

    quoted = _QUOTED_RE.findall(text)
    for item in quoted:
        if item.startswith("/"):
            steps.append({"action": "OPEN", "target": item, "is_route": False})
    if "trang" in lowered or "page" in lowered:
        text_slug = _slug(text)
        for key, route in (profile or {}).get("routes", {}).items():
            key_slug = _slug(key)
            hints = [key_slug, key_slug.rstrip("s")] + \
                [_slug(h) for h in _ROUTE_HINTS.get(key_slug, ())]
            if any(hint and hint in text_slug for hint in hints):
                steps.append({"action": "OPEN", "target": key, "is_route": True})
    if re.search(r"đã có|đã tồn tại|existing|có sẵn", lowered):
        warnings.append("Precondition needs seeded data — define a fixture: {0}".format(
            text[:120]))
    return actor, steps


def _parse_steps(text, profile, new_locators, counter, warnings):
    steps = []
    raw_chunks = [l for l in text.splitlines() if _norm(l)]
    if not raw_chunks:
        raw_chunks = [text]
    segments = []
    for chunk in raw_chunks:
        # danh sách có đánh số/phân tách ; thì không tách câu (tránh cắt "1." thành dòng rời)
        if re.match(r"^\s*\d+[.)\]]", chunk) or ";" in text or len(raw_chunks) > 1:
            segments.extend(part for part in chunk.split(";") if _norm(part))
        else:
            segments.extend(re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ỹ])", chunk))
    for segment in segments:
        line = _norm(segment)
        match = _NUMBERING_RE.match(line)
        if match:
            line = _norm(match.group(1))
        if not line or re.fullmatch(r"[\d.)\]]+", line):
            continue
        lowered = line.lower()
        quoted = _QUOTED_RE.findall(line)

        if re.match(r"^(open|go to|truy cập|truy cap|đi tới|mo trang|mở trang)\b", lowered):
            if quoted:
                steps.append({"action": "OPEN", "target": quoted[0]})
            else:
                warnings.append("OPEN step without target: {0}".format(line[:100]))
            continue
        if re.match(r"^(fill|type|điền|dien|nhập|nhap)\b", lowered):
            if not quoted:
                warnings.append("FILL step without quoted field: {0}".format(line[:100]))
                continue
            field = quoted[0]
            value_match = _FILL_VALUE_RE.search(line)
            if value_match:
                value = value_match.group(1)
            elif re.search(r"rỗng|roong|empty", lowered):
                value = ""
            else:
                value = quoted[1] if len(quoted) > 1 else ""
                if not value:
                    warnings.append("FILL step without value, defaulted empty: {0}".format(
                        line[:100]))
            key, _ = _resolve_locator(profile.get("locators", {}) if profile else {},
                                      new_locators, field, "FILL", counter)
            steps.append({"action": "FILL", "target": key, "value": value})
            continue
        if re.match(r"^(select|choose|chọn|chon)\b", lowered):
            if len(quoted) >= 2:
                key, _ = _resolve_locator(profile.get("locators", {}) if profile else {},
                                          new_locators, quoted[0], "SELECT", counter)
                steps.append({"action": "SELECT", "target": key, "value": quoted[1]})
            else:
                warnings.append("SELECT step needs field and value: {0}".format(line[:100]))
            continue
        if re.match(r"^(submit|xác nhận|xac nhan|confirm|nộp|nop)\b", lowered):
            key = None
            if quoted:
                key, _ = _resolve_locator(profile.get("locators", {}) if profile else {},
                                          new_locators, quoted[0], "SUBMIT", counter)
                steps.append({"action": "CLICK", "target": key})
            else:
                warnings.append("SUBMIT step without button name: {0}".format(line[:100]))
            continue
        if re.match(r"^(click|tap|press|bấm|bam|nhấn|nhan)\b", lowered):
            if quoted:
                key, _ = _resolve_locator(profile.get("locators", {}) if profile else {},
                                          new_locators, quoted[0], "CLICK", counter)
                steps.append({"action": "CLICK", "target": key})
            else:
                warnings.append("CLICK step without target: {0}".format(line[:100]))
            continue
        if quoted:
            key, _ = _resolve_locator(profile.get("locators", {}) if profile else {},
                                      new_locators, quoted[0], "CLICK", counter)
            steps.append({"action": "CLICK", "target": key})
            warnings.append("Inferred CLICK from quoted step: {0}".format(line[:100]))
        else:
            warnings.append("Unmapped step (no pattern, no quotes): {0}".format(line[:100]))
    return steps


def _parse_expected(text, warnings):
    oracles, api_checks = [], []
    parts = [p for p in re.split(r"[\n;]+|\s+và\s+|\s+va\s+|\s+and\s+", text) if _norm(p)]
    for part in parts:
        part = _norm(part)
        lowered = part.lower()
        quoted = _QUOTED_RE.findall(part)

        api = _API_RE.search(part)
        if api:
            api_checks.append({"path": api.group(2), "method": api.group(1).upper(),
                               "expected_status": int(api.group(3))})
            continue
        status = _STATUS_ONLY_RE.search(part)
        path = _URL_PATH_RE.search(part)
        if path and status and any(k in lowered for k in ("api", "http", "trả về", "tra ve",
                                                          "status", "endpoint")):
            api_checks.append({"path": path.group(1), "expected_status": int(status.group(1))})
            continue
        if any(k in lowered for k in ("url", "đường dẫn", "duong dan", "điều hướng",
                                      "dieu huong", "redirect")) and path:
            oracles.append({"type": "URL", "expected": path.group(1), "timeout_ms": 10000})
            continue
        if any(k in lowered for k in ("không hiển thị", "khong hien thi", "không thấy",
                                      "khong thay", "không tồn tại", "khong ton tai",
                                      "not visible", "disappear", "biến mất", "bien mat")):
            if quoted:
                oracles.append({"type": "ABSENT", "target": quoted[0], "timeout_ms": 5000})
            else:
                warnings.append("ABSENT expectation without quoted text: {0}".format(part[:100]))
            continue
        if any(k in lowered for k in ("thấy", "thay", "hiển thị", "hien thi", "xuất hiện",
                                      "xuat hien", "see", "visible", "expect")) and quoted:
            oracles.append({"type": "VISIBLE", "target": quoted[0], "timeout_ms": 10000})
            continue
        if quoted:
            oracles.append({"type": "VISIBLE", "target": quoted[0], "timeout_ms": 10000})
            warnings.append("Inferred VISIBLE from quoted expectation: {0}".format(part[:100]))
            continue
        warnings.append("Unparsed expectation (no checkable assertion): {0}".format(part[:100]))
    return oracles, api_checks


def build_suite(rows, profile=None, source=""):
    """rows (từ parse_spec) -> {"suite", "profile_additions", "warnings", "stats"}."""
    profile = profile or {}
    new_locators = {}
    counter = {"n": 0}
    warnings = []
    cases = []
    feature_names = []
    mapped_steps = mapped_expectations = 0

    for index, row in enumerate(rows, start=1):
        case_warnings_before = len(warnings)
        actor, pre_steps = _parse_precondition(row.get("precondition", ""), profile, warnings)
        steps = _parse_steps(row.get("steps", ""), profile, new_locators, counter, warnings)
        steps = pre_steps + steps
        oracles, api_checks = _parse_expected(row.get("expected", ""), warnings)
        function_id = row.get("function_id") or "draft-{0}".format(index)
        case = {
            "test_case_id": function_id,
            "actor": actor or (list(profile.get("actors", {}).keys()) or [None])[0],
            "requirement_refs": [function_id],
            "steps": steps,
        }
        if actor is None:
            warnings.append("{0}: actor not detected in precondition".format(function_id))
        if not steps:
            warnings.append("{0}: no steps parsed".format(function_id))
        if oracles:
            for oracle in oracles:
                oracle["source_ref"] = function_id
            case["ui_oracles"] = oracles
            mapped_expectations += len(oracles)
        if api_checks:
            for check in api_checks:
                check["source_ref"] = function_id
            case["api_checks"] = api_checks
            mapped_expectations += len(api_checks)
        if len(warnings) == case_warnings_before:
            mapped_steps += len(steps)
        feature_names.append(row.get("feature", ""))
        cases.append(case)

    suite = {
        "version": 1,
        "name": feature_names[0] if feature_names else "Imported test spec",
        "review_status": "unreviewed",
        "source_spec": str(source),
        "cases": cases,
    }
    stats = {
        "cases": len(cases),
        "steps": sum(len(c["steps"]) for c in cases),
        "steps_clean": mapped_steps,
        "expectations": sum(len(c.get("ui_oracles", [])) + len(c.get("api_checks", []))
                            for c in cases),
        "expectations_clean": mapped_expectations,
        "draft_locators": len(new_locators),
    }
    return {
        "suite": suite,
        "profile_additions": {"locators": new_locators},
        "warnings": warnings,
        "stats": stats,
        "clean": not warnings,
    }
