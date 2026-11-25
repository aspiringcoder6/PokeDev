"""Performance Requirement resolver — Tier-based Fallback (Plan 24 §1.4).

Chiến lược phân giải cấu hình theo ưu tiên:
1. Per-API Override: opt/perf/overrides/{api_id_safe}.json
2. Tier Profile: opt/perf/tiers/{tier}.json (core / crud / heavy)
3. Global Default: opt/perf/global_default.json

Tránh phải viết thủ công từng API; chỉ override khi cần ngưỡng khác biệt.
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[2]
_PERF_DIR = ROOT / "opt" / "perf"

_TIER_DEFAULTS = {
    "core": {"p50_ms_max": {"target": 200, "acceptable_max": 400},
              "p95_ms_max": {"target": 500, "acceptable_max": 800},
              "p99_ms_max": {"target": 800, "acceptable_max": 1500},
              "error_rate_max": {"target": 0.01, "acceptable_max": 0.03},
              "throughput_rps_min": {"target": 50, "acceptable_min": 20}},
    "crud": {"p50_ms_max": {"target": 300, "acceptable_max": 600},
              "p95_ms_max": {"target": 800, "acceptable_max": 1200},
              "p99_ms_max": {"target": 1200, "acceptable_max": 2000},
              "error_rate_max": {"target": 0.01, "acceptable_max": 0.03},
              "throughput_rps_min": {"target": 20, "acceptable_min": 10}},
    "heavy": {"p50_ms_max": {"target": 500, "acceptable_max": 1000},
               "p95_ms_max": {"target": 1500, "acceptable_max": 2500},
               "p99_ms_max": {"target": 2500, "acceptable_max": 4000},
               "error_rate_max": {"target": 0.02, "acceptable_max": 0.05},
               "throughput_rps_min": {"target": 5, "acceptable_min": 2}},
}


def _safe_api_id(api_id: str) -> str:
    """POST /api/v1/auth/login -> POST-api-v1-auth-login"""
    return api_id.replace(" ", "-").replace("/", "-").replace(":", "-")


def resolve_thresholds(api_id: str, tier: str = "crud",
                       override_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Fallback chain: Per-API override → Tier profile → Global default.

    Returns: thresholds dict (3-tier format: target+acceptable_max/min).
    """
    perf_dir = override_dir or _PERF_DIR

    # 1. Per-API Override
    override_path = perf_dir / "overrides" / "{0}.json".format(_safe_api_id(api_id))
    if override_path.is_file():
        override = json.loads(override_path.read_text(encoding="utf-8-sig"))
        return override

    # 2. Tier Profile (file hoặc hardcoded default)
    tier_path = perf_dir / "tiers" / "{0}.json".format(tier)
    if tier_path.is_file():
        tier_data = json.loads(tier_path.read_text(encoding="utf-8-sig"))
        return tier_data.get("thresholds") or _TIER_DEFAULTS.get(tier, _TIER_DEFAULTS["crud"])

    # 3. Global Default
    global_path = perf_dir / "global_default.json"
    if global_path.is_file():
        global_data = json.loads(global_path.read_text(encoding="utf-8-sig"))
        if global_data.get("thresholds"):
            return global_data["thresholds"]

    return _TIER_DEFAULTS.get(tier, _TIER_DEFAULTS["crud"])


def resolve_requirement(api_id: str, tier: str = "crud",
                        base_requirement: Optional[Dict[str, Any]] = None,
                        override_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Phân giải requirement đầy đủ: base + thresholds resolved.

    Args:
        api_id: endpoint key (vd "POST /api/v1/auth/login")
        tier: core / crud / heavy — dùng khi không có per-API override
        base_requirement: dict có workload_profiles, business_action, etc.
                          Thresholds sẽ được ghi đè bởi resolve_thresholds
                          nếu base chưa có (hoặc luôn ghi đè nếu base thiếu).

    Returns: requirement dict với thresholds đã phân giải (ready for schema validate).
    """
    base = dict(base_requirement) if base_requirement else {}
    if "thresholds" not in base or not base.get("thresholds"):
        base["thresholds"] = resolve_thresholds(api_id, tier, override_dir)
    if "tier" not in base:
        base["tier"] = tier
    return base


__all__ = ["resolve_requirement", "resolve_thresholds"]
