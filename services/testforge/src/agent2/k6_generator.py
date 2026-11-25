"""k6 script generator Zero-LLM — Performance Requirement + Handoff -> script.js.

Cùng triết lý G2 Synthesizer của Agent 1: KHÔNG dùng LLM để viết code,
chỉ dịch contract sang template. Cùng input -> cùng output (deterministic).

**Update Plan 24 §2:** nhận `performance_handoff` từ Agent 1 chứa
`verified_flows` (endpoint, method, payload_schema, expected_status đã verify).
Khi có handoff → sinh script dựa trên dữ liệu thật đã xác minh.
Khi thiếu handoff → fallback _ACTION_TEMPLATES (backward compat).
"""
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_ACTION_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "login": {
        "method": "POST",
        "path": "/api/v1/auth/login",
        "tag": "login",
        "body": "JSON.stringify({ email: user.email, password: user.password })",
        "checks": (
            "      'status is 2xx': (r) => r.status >= 200 && r.status < 300,\n"
            "      'has token': (r) => {\n"
            "        try { const b = r.json(); return b.access_token !== undefined "
            "|| b.token !== undefined || b.data !== undefined; }\n"
            "        catch (e) { return false; }\n"
            "      },\n"
        ),
    },
}


def _threshold_target_value(raw: Any) -> Optional[float]:
    """Lấy giá trị target từ threshold (số đơn cũ hoặc {target, acceptable_max} mới)."""
    if isinstance(raw, dict):
        return float(raw.get("target", 0))
    if isinstance(raw, (int, float)):
        return float(raw)
    return None


def _profile_stages(profile: Dict[str, Any]) -> str:
    vus = int(profile["vus"])
    ramp_up = profile.get("ramp_up") or "10s"
    duration = profile.get("duration") or "1m"
    ramp_down = profile.get("ramp_down") or "10s"
    return (
        "    stages: [\n"
        "      {{ duration: '{0}', target: {1} }}, // ramp up\n"
        "      {{ duration: '{2}', target: {1} }}, // sustain\n"
        "      {{ duration: '{3}', target: 0 }},    // ramp down\n"
        "    ],\n"
    ).format(ramp_up, vus, duration, ramp_down)


def _threshold_lines(thresholds: Dict[str, Any], tag: str) -> str:
    """Map requirement thresholds → k6 threshold expressions (dùng target value)."""
    lines = []
    dur_pcts = []
    for key, expr in (("p50_ms_max", "p(50)"), ("p95_ms_max", "p(95)"),
                      ("p99_ms_max", "p(99)")):
        if key in thresholds:
            val = _threshold_target_value(thresholds[key])
            if val is not None:
                dur_pcts.append("{0}<{1}".format(expr, int(val)))
    if dur_pcts:
        lines.append("      'http_req_duration{{type:{0}}}': ['{1}'],".format(
            tag, "', '".join(dur_pcts)))
    if "error_rate_max" in thresholds:
        val = _threshold_target_value(thresholds["error_rate_max"])
        if val is not None:
            lines.append("      'http_req_failed':               ['rate<{0}'],".format(val))
    if "throughput_rps_min" in thresholds:
        val = _threshold_target_value(thresholds["throughput_rps_min"])
        if val is not None:
            lines.append("      'http_reqs':                     ['rate>{0}'],".format(int(val)))
    return "\n".join(lines) + "\n"


def _flow_from_handoff(handoff: Dict[str, Any], target_endpoint: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Trích verified_flow khớp với requirement (hoặc flow đầu tiên nếu không chỉ định) → template dict."""
    flows = handoff.get("verified_flows") or []
    if not flows:
        raise ValueError("performance_handoff thiếu verified_flows")

    flow = None
    if target_endpoint:
        norm_target = target_endpoint.strip().lower()
        for f in flows:
            api_id = f.get("api_id", "").strip().lower()
            path = f.get("path", "").strip().lower()
            if norm_target in api_id or norm_target.endswith(path) or path in norm_target:
                flow = f
                break
    if not flow and not target_endpoint:
        flow = flows[0]

    if not flow:
        return None

    method = flow.get("method", "POST").lower()
    path = flow.get("path", "/")
    expected_status = int(flow.get("expected_status", 200))
    tag = path.strip("/").split("/")[0] if path.strip("/") else "api"

    payload_fields: List[Dict[str, str]] = flow.get("payload_fields") or []
    if payload_fields:
        body_parts = []
        for f in payload_fields:
            fname = f["name"]
            fsource = f.get("source", "user." + fname)
            body_parts.append("{0}: {1}".format(fname, fsource))
        body = "JSON.stringify({" + ", ".join(body_parts) + "})"
    else:
        body = "JSON.stringify({})"

    response_field = flow.get("response_has_field")
    check_lines = (
        "      'status matches verified': (r) => r.status === {0},\n".format(expected_status)
    )
    if response_field:
        check_lines += (
            "      'has {0}': (r) => {{\n"
            "        try {{ const b = r.json(); return b.{0} !== undefined; }}\n"
            "        catch (e) {{ return false; }}\n"
            "      }},\n"
        ).format(response_field)

    return {"method": method, "path": path, "tag": tag, "body": body, "checks": check_lines}


def generate_script(requirement: Dict[str, Any], profile: str = "peak",
                    handoff: Optional[Dict[str, Any]] = None) -> str:
    """Sinh k6 script từ Requirement (+ optional Handoff). Deterministic.

    Args:
        requirement: Performance Requirement dict (schema-validated).
        profile: workload profile key (normal/peak/stress/smoke).
        handoff: performance_handoff từ Agent 1 (verified_flows). Khi None →
                 fallback _ACTION_TEMPLATES theo business_action.

    Raises:
        ValueError: profile thiếu, hoặc business_action chưa hỗ trợ (khi không handoff).
    """
    profiles = requirement.get("workload_profiles") or {}
    if profile not in profiles:
        raise ValueError(
            "Profile '{0}' missing in workload_profiles (có: {1})".format(
                profile, ", ".join(profiles) or "none"))

    template = None
    source_note = ""
    if handoff and handoff.get("verified_flows"):
        target_endpoint = requirement.get("test_target", {}).get("endpoint")
        template = _flow_from_handoff(handoff, target_endpoint=target_endpoint)
        if template:
            source_note = "Handoff: {0}".format(handoff.get("source_run_id", "verified"))

    if template is None:
        action = (requirement.get("business_action") or "").strip().lower()
        template = _ACTION_TEMPLATES.get(action)
        if template is None:
            raise ValueError(
                "business_action '{0}' chưa hỗ trợ và không có performance_handoff. "
                "Cần handoff từ Agent 1 hoặc đăng ký trong _ACTION_TEMPLATES.".format(
                    action or "<empty>"))
        source_note = "_ACTION_TEMPLATES (fallback, no handoff)"

    perf_req_id = requirement["perf_req_id"]
    stages = _profile_stages(profiles[profile])
    thresholds = _threshold_lines(requirement.get("thresholds") or {}, template["tag"])

    return (
        "// Generated by TestForge AI Agent 2 - Zero-LLM\n"
        "// Source: {perf} | Profile: {profile} | Flow: {flow_note}\n"
        "// Thresholds map tu Performance Requirement (sec 3 thiet ke)\n"
        "import http from 'k6/http';\n"
        "import {{ check, sleep }} from 'k6';\n"
        "import {{ SharedArray }} from 'k6/data';\n"
        "\n"
        "const BASE_URL = __ENV.BASE_URL || 'http://localhost';\n"
        "const users = new SharedArray('users', function () {{\n"
        "  return JSON.parse(open(__ENV.USERS_JSON || './users.json'));\n"
        "}});\n"
        "\n"
        "export const options = {{\n"
        "{stages}"
        "  thresholds: {{\n"
        "{thresholds}  }},\n"
        "}};\n"
        "\n"
        "export default function () {{\n"
        "  const user = users[Math.floor(Math.random() * users.length)];\n"
        "  const payload = {body};\n"
        "  const params = {{\n"
        "    headers: {{ 'Content-Type': 'application/json' }},\n"
        "    tags: {{ type: '{tag}' }},\n"
        "  }};\n"
        "  const response = http.{method}(`${{BASE_URL}}{path}`, payload, params);\n"
        "  check(response, {{\n"
        "{checks}  }});\n"
        "  sleep(Math.random() * 2 + 1);\n"
        "}}\n"
    ).format(perf=perf_req_id, profile=profile, flow_note=source_note, stages=stages,
             thresholds=thresholds, body=template["body"],
             method=template["method"].lower(), path=template["path"],
             tag=template["tag"], checks=template["checks"])


def write_script(requirement, profile, out_dir, handoff=None):
    """Ghi script ra out_dir với tên <perf_req_id>_<profile>.js. Trả về Path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = "{0}_{1}.js".format(requirement["perf_req_id"].lower(), profile)
    path = out_dir / name
    path.write_text(generate_script(requirement, profile, handoff), encoding="utf-8")
    return path


__all__ = ["generate_script", "write_script", "_flow_from_handoff", "_threshold_target_value"]
