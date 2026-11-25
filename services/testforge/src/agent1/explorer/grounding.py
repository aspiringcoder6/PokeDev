"""Deterministic grounding: ARIA snapshot -> locator candidates -> chosen locator.

The ARIA snapshot serves two purposes at once (docs/20):
1. nén context cho LLM navigator;
2. nguồn locator candidates hoàn toàn deterministic — LLM không bao giờ
   tự chế selector. Executor chỉ chạy locator sinh từ snapshot thật.
"""
import re

CLICK_ROLES = {
    "button", "link", "tab", "menuitem", "checkbox", "radio", "switch", "option",
    # Data table: hàng/ô là pattern click-mở-chi-tiết chuẩn (VD TNQD ng-vts-table)
    "cell", "row", "gridcell", "treeitem",
}
INPUT_ROLES = {"textbox", "searchbox", "combobox", "spinbutton"}

_ARIA_LINE = re.compile(r'^(\s*)-\s+([A-Za-z0-9_]+):?(?:\s+"((?:[^"\\]|\\.)*)")?')


def parse_snapshot(snapshot):
    """Parse Playwright aria_snapshot() thành list element {role, name, depth}."""
    elements = []
    for line in snapshot.splitlines():
        match = _ARIA_LINE.match(line)
        if not match:
            continue
        indent, role, name = match.group(1), match.group(2), match.group(3) or ""
        elements.append({"role": role.lower(), "name": name, "depth": len(indent) // 2})
    return elements


def _subtree_at(lines, start_idx):
    """Trả về (dòng của subtree bắt đầu tại start_idx, chỉ số dòng kết thúc)."""
    match = _ARIA_LINE.match(lines[start_idx].rstrip("\n"))
    indent = len(match.group(1))
    end = start_idx + 1
    while end < len(lines):
        match_next = _ARIA_LINE.match(lines[end].rstrip("\n"))
        if match_next and len(match_next.group(1)) <= indent:
            break
        end += 1
    return lines[start_idx:end], end


def prune_snapshot(snapshot, max_chars):
    """Nén snapshot theo ARIA region: ưu tiên subtree role=dialog (mọi độ sâu) rồi main.

    Modal của SPA có thể render NESTED trong main và ở CUỐI snapshot (~27k chars) —
    cắt đuôi hoặc chỉ giữ main đều làm LLM "mù" dialog đang mở rồi bấm lại nút
    phía sau overlay (defect thật khi demo). Thứ tự ghép: dialog* (nguyên vẹn)
    -> main -> các region còn lại, trong budget max_chars.
    """
    if max_chars <= 0 or len(snapshot) <= max_chars:
        return snapshot
    lines = snapshot.splitlines(keepends=True)

    dialog_subtrees = []
    dialog_indices = set()
    for index, line in enumerate(lines):
        match = _ARIA_LINE.match(line.rstrip("\n"))
        if match and match.group(2).lower() == "dialog":
            subtree, end = _subtree_at(lines, index)
            dialog_subtrees.append("".join(subtree))
            dialog_indices.update(range(index, end))
    remaining_lines = [line for i, line in enumerate(lines) if i not in dialog_indices]

    segments, current = [], []
    for line in remaining_lines:
        match = _ARIA_LINE.match(line.rstrip("\n"))
        if match and len(match.group(1)) == 0 and current:
            segments.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        segments.append(current)

    def role_of(segment):
        match = _ARIA_LINE.match(segment[0].rstrip("\n"))
        return match.group(2).lower() if match else ""

    main_segment = next((s for s in segments if role_of(s) == "main"), None)
    rest = [s for s in segments if s is not main_segment]

    kept, budget = [], max_chars
    pieces = dialog_subtrees + (["".join(main_segment)] if main_segment else []) \
        + ["".join(s) for s in rest]
    for piece in pieces:
        if budget <= 0:
            break
        kept.append(piece[:budget])
        budget -= len(piece)
    return "".join(kept)


def _match_score(target, name):
    t, n = target.strip().lower(), name.strip().lower()
    if not t:
        return 0.0
    if t == n:
        return 1.0
    if t in n:
        return 0.8
    t_clean = t.rstrip("* ").strip()
    n_clean = n.rstrip("* ").strip()
    if t_clean and t_clean == n_clean:
        return 0.9
    if t_clean and t_clean in n_clean:
        return 0.7
    return 0.0


def locator_candidates(elements, target, intent="CLICK"):
    """Rank elements khớp target. role bonus theo intent (CLICK->interactive, FILL->input)."""
    scored = []
    for element in elements:
        if not element["name"]:
            continue
        score = _match_score(target, element["name"])
        if score <= 0.0:
            continue
        role = element["role"]
        if intent in ("CLICK", "SUBMIT") and role in CLICK_ROLES:
            score += 0.1
        if intent == "FILL" and role in INPUT_ROLES:
            score += 0.1
        scored.append({"strategy": "role", "value": role, "name": element["name"], "score": round(score, 2)})
    scored.sort(key=lambda c: (-c["score"], c["name"]))
    return scored


def chosen_element(candidate):
    """Candidate -> element cho executor: {role, name}."""
    return {"role": candidate["value"], "name": candidate["name"]}


def js_locator_expr(element):
    """Locator biểu thức JS cho spec tổng hợp — trùng khớp ngữ nghĩa với executor Python."""
    name = element["name"].replace("\\", "\\\\").replace("'", "\\'")
    return "page.getByRole('{0}', {{ name: '{1}', exact: true }})".format(element["role"], name)
