"""Data policy cho Agent 2 — prepare test data pool cho load test.

Chiến lược (Plan 24 §3 M2-P4):
- Pool hiện có: admin@example.com (đã verify qua functional gate của Agent 1)
- Seed pool: tạo thêm N user qua API khi cần (cho D-02 peak 200 VU)
- Mỗi VU chọn random 1 user từ pool → login thất bại 0% (chống 400/401 rác)

Controlled issues (không sửa code SUT):
- missing_index: DROP INDEX users_email_key → login query full-scan
- resource_limit: docker update --cpus=N pm-backend → bcrypt-bound login chậm hơn
"""
import json
import random
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

POOL_ADMIN = [{"email": "admin@example.com", "password": "Admin@123"}]


def write_pool(users: List[Dict[str, str]], out_path: str = "opt/perf/users.json"):
    """Ghi user pool ra file JSON (k6 SharedArray đọc qua __ENV.USERS_JSON)."""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(
        json.dumps(users, ensure_ascii=False), encoding="utf-8")
    return len(users)


def prepare_pool(base_url: str, pool_size: int = 1,
                 admin_email: str = "admin@example.com",
                 admin_password: str = "Admin@123") -> List[Dict[str, str]]:
    """Chuẩn bị user pool. pool_size=1: chỉ admin (đã verify).
    
    pool_size>1: seed thêm user qua API (cần admin token; ghi chú: MVP pool_size=1
    vì login là CPU-bound bcrypt, số liệu perf không phụ thuộc user nào).
    """
    if pool_size <= 1:
        return [{"email": admin_email, "password": admin_password}]

    # Seed: login admin → tạo pool_size user qua API
    # (triển khai khi cần mở rộng — MVP dùng pool admin)
    token = _login(base_url, admin_email, admin_password)
    if not token:
        return [{"email": admin_email, "password": admin_password}]

    pool = []
    ts = int(time.time())
    for i in range(pool_size):
        email = "perf_test_{0}_{1}@example.com".format(ts, i)
        ok = _create_user(base_url, token, email, "PerfTest@123")
        if ok:
            pool.append({"email": email, "password": "PerfTest@123"})
    if not pool:
        pool = [{"email": admin_email, "password": admin_password}]
    return pool


def _login(base_url: str, email: str, password: str) -> Optional[str]:
    """Login API → access_token."""
    try:
        body = json.dumps({"email": email, "password": password}).encode()
        req = urllib.request.Request(
            "{0}/api/v1/auth/login".format(base_url),
            data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("access_token") or data.get("token") or (
                data.get("data", {}).get("access_token") if isinstance(data.get("data"), dict) else None)
    except Exception:
        return None


def _create_user(base_url: str, token: str, email: str, password: str) -> bool:
    """Tạo user qua API (best-effort; nếu endpoint không hỗ trợ → skip)."""
    try:
        body = json.dumps({
            "email": email, "password": password,
            "full_name": "Perf Test User",
        }).encode()
        req = urllib.request.Request(
            "{0}/api/v1/users".format(base_url),
            data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer {0}".format(token)},
            method="POST")
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception:
        return False


# ---- Controlled issue toggles (infra-level, không sửa code SUT) ----

MISSING_INDEX_SQL = "DROP INDEX IF EXISTS users_email_key"
RESTORE_INDEX_SQL = "CREATE UNIQUE INDEX users_email_key ON users(email)"


def toggle_missing_index(enable: bool, db_user: str = "postgres",
                         db_name: str = "project_management") -> bool:
    """Bật/tắt controlled issue: DROP/RESTORE unique index trên users.email.
    
    Login query (SELECT ... WHERE email=...) sẽ full-scan khi index bị drop.
    """
    import subprocess
    sql = MISSING_INDEX_SQL if enable else RESTORE_INDEX_SQL
    proc = subprocess.run(
        ["docker", "exec", "pm-postgres", "psql", "-U", db_user, "-d", db_name, "-c", sql],
        capture_output=True, timeout=10)
    return proc.returncode == 0


def toggle_cpu_limit(enable: bool, cpus: str = "0.5") -> bool:
    """Bật/tắt controlled issue: giới hạn CPU backend container.
    
    bcrypt login là CPU-bound → giới hạn CPU trực tiếp tăng p95/p99.
    Disable: đặt --cpus=0 (Docker: 0 = không giới hạn).
    """
    limit = cpus if enable else "4"
    proc = subprocess.run(
        ["docker", "update", "--cpus={0}".format(limit), "pm-backend"],
        capture_output=True, timeout=10)
    return proc.returncode == 0


__all__ = ["write_pool", "prepare_pool", "toggle_missing_index", "toggle_cpu_limit",
           "POOL_ADMIN"]
