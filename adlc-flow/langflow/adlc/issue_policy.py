"""Explainable issue triage and deterministic approval rules.

Adapted to PokeDev's durable run model from the triage/gate ideas in workloop
d4370ca and the R0-R3 guidance in factory-wilson bb5cb56. No remote code runs.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata

VERSION = "issue-policy-v1"
AUTOMATIC_MODES = {"auto", "risk"}
POLICY_DEFAULTS = {
    "auto_allowed_paths": ["docs/**", "tests/**"],
    "auto_max_runs_per_day": 3,
    "auto_max_active_minutes": 20,
}
QUESTIONS = [
    {"id": "goal", "question": "Kết quả cụ thể bạn muốn đạt được là gì?"},
    {"id": "scope", "question": "Phần nào hoặc file nào được thay đổi? Có gì cần giữ nguyên?"},
    {"id": "acceptance", "question": "Kiểm tra thế nào để biết công việc đã hoàn thành đúng?"},
]


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def normalized(text):
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.casefold().replace("đ", "d")) if not unicodedata.combining(c)
    )


def valid_relative_path(path):
    if not isinstance(path, str) or not path or len(path) > 300 or any(c in path for c in "\\:*?[]\x00"):
        return False
    return all(
        part.casefold() not in {"", ".", "..", ".git", "node_modules", ".venv"}
        and not part.casefold().startswith(".env")
        and not any(ord(c) < 32 for c in part)
        for part in path.split("/")
    )


def normalize_allowed_paths(paths):
    if not isinstance(paths, list) or len(paths) > 20:
        raise ValueError("ISSUE_ALLOWED_PATHS_INVALID")
    result = []
    for pattern in paths:
        if not isinstance(pattern, str):
            raise ValueError("ISSUE_ALLOWED_PATHS_INVALID")
        pattern = pattern.strip()
        base = pattern[:-3] if pattern.endswith("/**") else pattern
        if not valid_relative_path(base) or base.split("/")[0].casefold() in {".git", "node_modules", ".venv"}:
            raise ValueError("ISSUE_ALLOWED_PATHS_INVALID")
        if pattern not in result:
            result.append(pattern)
    return result


def path_allowed(path, patterns):
    return valid_relative_path(path) and any(
        path.startswith(p[:-2]) if p.endswith("/**") else path == p for p in patterns
    )


def triage_issue(issue, clarification=None):
    """A score describes rule coverage, never grants tool or execution permission."""
    clarification = clarification or {}
    answers = clarification.get("answers", {})
    source = fingerprint([issue.get("title", ""), issue.get("body", "")])
    complete = clarification.get("source_digest") == source and all(
        isinstance(answers.get(q["id"]), str) and len(answers[q["id"]].strip()) >= 8 for q in QUESTIONS
    )
    input_digest = fingerprint([VERSION, source, clarification])
    body = issue.get("body", "").strip()
    text = normalized(issue.get("title", "") + "\n" + body)
    needs_spec = bool(
        re.search(
            r"\b(epic|architecture|redesign|new platform|new application|kien truc|xay dung nen tang|thiet ke lai)\b",
            text,
        )
    )
    uncertain = bool(re.search(r"\b(tbd|todo|not sure|to be decided|chua ro|chua quyet dinh|can thao luan)\b", text))
    expected = bool(
        re.search(
            r"\b(without|must|should|expected|return|display|shows?|acceptance|khong|phai|hien thi|tra ve|tieu chi|ket qua)\b",
            text,
        )
    )
    explicit_steps = len(re.findall(r"(?m)^\s*(?:[-*]|\d+[.)])\s+\S", body)) >= 2
    if complete:
        action, confidence = "ready", 1.0
        reasons = ["Bạn đã bổ sung mục tiêu, phạm vi và tiêu chí nghiệm thu cho bản issue này."]
    elif needs_spec:
        action, confidence = "needs_spec", 0.65
        reasons = ["Yêu cầu có phạm vi thiết kế hoặc thay đổi lớn; cần chốt đặc tả và phạm vi trước khi giao việc."]
    elif len(body) < 35 or not issue.get("title", "").strip() or uncertain or not (expected or explicit_steps):
        action, confidence = "needs_human", 0.45
        reasons = ["Issue chưa mô tả đủ kết quả có thể kiểm chứng, hoặc còn điểm chưa được quyết định."]
    else:
        action, confidence = "ready", 0.85
        reasons = ["Issue có mô tả công việc và điều kiện kết quả để bắt đầu lập kế hoạch."]
    return {
        "version": VERSION,
        "action": action,
        "confidence": confidence,
        "reasons": reasons,
        "questions": [] if action == "ready" else QUESTIONS,
        "input_digest": input_digest,
        "planning_style": clarification.get("approach", "spec_first" if needs_spec else "implement"),
    }


# Sensitive paths are checked independently of both the issue wording and scopes.
SENSITIVE_PATH = re.compile(
    r"(?:^|/)(?:auth|authentication|authorization|security|permissions?|secrets?|credentials?|billing|payments?|iam)(?:/|[._-]|$)|(?:^|/)(?:\.env[^/]*|id_rsa|[^/]+\.(?:pem|key))$",
    re.I,
)
SHARED_PATH = re.compile(
    r"(?:^|/)(?:migrations?|deploy|deployment|infra|terraform|kubernetes|\.github|\.gitea)(?:/|$)|(?:^|/)(?:package(?:-lock)?\.json|pyproject\.toml|requirements[^/]*\.txt|Dockerfile|docker-compose[^/]*|compose\.ya?ml|.*\.lock)$",
    re.I,
)


def risk_assessment(issue, clarification=None, plan=None):
    answers = (clarification or {}).get("answers", {})
    texts = [issue.get("title", ""), issue.get("body", ""), *answers.values()]
    if plan:
        texts.extend([plan.get("title", ""), plan.get("summary", "")])
        for task in plan.get("tasks", []):
            texts.extend([task.get("title", ""), *task.get("steps", []), *task.get("acceptance", [])])
    text = normalized("\n".join(str(x) for x in texts))
    read_only = plan is None and bool(
        re.search(
            r"^\s*(summari[sz]e|explain|analy[sz]e|phan tich|tom tat|giai thich)\b", normalized(issue.get("title", ""))
        )
    )
    factors = [
        {
            "factor": "reversibility",
            "level": 0 if read_only else 1,
            "reason": "Yêu cầu phân tích hoặc đọc thông tin; chưa có kế hoạch thay đổi file."
            if read_only
            else "Thay đổi code được chuẩn bị trong bản làm việc có thể xem lại trước khi xuất bản.",
        }
    ]
    if re.search(
        r"\b(passwords?|credentials?|secrets?|tokens?|permissions?|authentication|authorization|access control|payments?|billing|refund|mat khau|bi mat|phan quyen|quyen truy cap|thanh toan|hoan tien|du lieu ca nhan|pii)\b",
        text,
    ):
        factors.append(
            {
                "factor": "sensitivity",
                "level": 3,
                "reason": "Nội dung liên quan danh tính, quyền, bí mật hoặc dữ liệu/tài chính nhạy cảm.",
            }
        )
    if re.search(
        r"\b(production|deploy|publish|release to|send email|send notification|customer|xoa vinh vien|delete all|drop table|truncate table|gui email|gui thong bao|khach hang)\b",
        text,
    ):
        factors.append(
            {
                "factor": "external_effect",
                "level": 3,
                "reason": "Có yêu cầu tác động môi trường vận hành, công bố, gửi ra ngoài hoặc xóa dữ liệu.",
            }
        )
    if re.search(
        r"\b(migration|database schema|dependencies|dependency|upgrade package|shared config|co so du lieu|cau hinh dung chung|nang cap thu vien)\b",
        text,
    ):
        factors.append(
            {"factor": "blast_radius", "level": 2, "reason": "Có thay đổi dữ liệu, phụ thuộc hoặc cấu hình dùng chung."}
        )
    paths = sorted({p for task in (plan or {}).get("tasks", []) for p in task.get("write_paths", [])})
    for path in paths:
        if not valid_relative_path(path) or SENSITIVE_PATH.search(path):
            factors.append(
                {"factor": "sensitivity", "level": 3, "reason": f"File nhạy cảm hoặc đường dẫn không hợp lệ: {path}"}
            )
        elif SHARED_PATH.search(path):
            factors.append(
                {
                    "factor": "blast_radius",
                    "level": 2,
                    "reason": f"File ảnh hưởng cấu hình, hạ tầng hoặc phụ thuộc: {path}",
                }
            )
    if len(paths) > 10:
        factors.append({"factor": "blast_radius", "level": 2, "reason": "Kế hoạch thay đổi hơn 10 file."})
    if plan is not None and (not paths or not plan.get("commands")):
        factors.append(
            {
                "factor": "verification",
                "level": 2,
                "reason": "Kế hoạch chưa có đủ phạm vi file và lệnh kiểm chứng để tự duyệt.",
            }
        )
    if plan and (
        any(not test_command_allowed(c.get("argv")) for c in plan.get("commands", []))
        or (plan.get("preview") or {}).get("argv")
    ):
        factors.append(
            {
                "factor": "external_effect",
                "level": 2,
                "reason": "Kế hoạch có lệnh tùy ý hoặc khởi chạy dịch vụ; cần người xem lệnh trước khi duyệt.",
            }
        )
    level = max(f["level"] for f in factors)
    return {"level": level, "tier": f"R{level}", "factors": factors, "paths": paths, "preliminary": plan is None}


def test_command_allowed(argv):
    """Risk-limited mode accepts explicit test runners, not arbitrary scripts."""
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(a, str) or re.search(r"[;&|`$<>\r\n]", a) for a in argv)
    ):
        return False
    if argv[0] in {"python", "python3"} and argv[1:3] in (["-m", "unittest"], ["-m", "pytest"]):
        return not any(
            a in {"-c", "--override-ini", "-p", "--pyargs"} or a.startswith(("--override-ini=", "--pyargs="))
            for a in argv[3:]
        )
    return argv[:2] == ["node", "--test"] and not any(
        a.startswith(("--eval", "--require", "--import")) for a in argv[2:]
    )


def assess_issue(issue, clarification, policy, plan=None):
    triage = triage_issue(issue, clarification)
    risk = risk_assessment(issue, clarification, plan)
    code = None
    if triage["action"] != "ready":
        code = "ISSUE_SPEC_REQUIRED" if triage["action"] == "needs_spec" else "ISSUE_CLARIFICATION_REQUIRED"
    elif risk["level"] >= 2:
        code = "ISSUE_RISK_REVIEW_REQUIRED"
    elif not policy.get("watch_issues") or policy["mode"] not in AUTOMATIC_MODES:
        code = "ISSUE_REVIEW_MODE"
    elif policy["mode"] == "risk" and plan is not None:
        scopes = policy.get("auto_allowed_paths", [])
        if not risk["paths"] or any(not path_allowed(path, scopes) for path in risk["paths"]):
            code = "ISSUE_PATH_REVIEW_REQUIRED"
        elif (
            not plan.get("commands")
            or any(not test_command_allowed(c.get("argv")) for c in plan["commands"])
            or (plan.get("preview") or {}).get("argv")
        ):
            code = "ISSUE_COMMAND_REVIEW_REQUIRED"
    decision = {
        "allowed": code is None,
        "code": code,
        "policy_revision": policy["revision"],
        "triage_digest": triage["input_digest"],
        "plan_digest": (plan or {}).get("digest"),
        "risk_tier": risk["tier"],
    }
    return {"triage": triage, "risk": risk, "auto_decision": decision}
