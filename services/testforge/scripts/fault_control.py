"""Fault Control helper cho benchmark harness M3.1.

Harness dùng module này để activate/deactivate controlled faults. Fault middleware
trong demo_app/server.py đọc cùng file faults.json.

QUAN TRỌNG (rule benchmark): fault ID CHỈ tồn tại ở tầng harness. Bất kỳ thứ gì
dưới harness (generator, executor, analyzer) không được nhận fault ID.
"""

import json
from pathlib import Path

FAULTS_PATH = Path(__file__).resolve().parents[1] / "demo_app" / "faults.json"

VALID_FAULTS = ("C01", "C02", "C03", "C05", "C06", "C01E", "C02E", "C03E", "C05E", "C06E")


def set_active_fault(case_id: str, variant: str = None) -> None:
    """Activate một controlled fault (dev C01-06 / eval C0xE)."""
    if case_id not in VALID_FAULTS:
        raise ValueError(f"Unknown fault: {case_id}. Valid: {VALID_FAULTS}")
    payload = {"active_fault": case_id}
    if variant:
        payload["variant"] = variant
    FAULTS_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def clear_active_fault() -> None:
    """Reset về trạng thái sạch (teardown bắt buộc gọi)."""
    FAULTS_PATH.write_text(json.dumps({"active_fault": None}), encoding="utf-8")


def get_active_fault() -> str:
    """Đọc fault đang active (dùng cho teardown/self-check của harness)."""
    try:
        data = json.loads(FAULTS_PATH.read_text(encoding="utf-8"))
        return data.get("active_fault")
    except (OSError, ValueError):
        return None


def reset_demo_store(base_url: str = "http://127.0.0.1:8931") -> bool:
    """Xoá sạch store demo app (DELETE /api/users) — test isolation cho benchmark local.

    Server standalone (khởi động ngoài runbook) giữ store giữa các run; không reset
    sẽ gây nhiễm dữ liệu (e.g. email trùng 409 làm bẩn fixture ASSERTION).
    Server không chạy -> trả False (playwright webServer sẽ tự khởi động store mới).
    """
    import urllib.request
    try:
        req = urllib.request.Request(f"{base_url}/api/users", method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except OSError:
        return False
