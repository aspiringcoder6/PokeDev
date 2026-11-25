"""Performance Reporter — performance_result.json + junit.xml + proofs copy (Plan 24 §2 & §3 M2-P3).

Chức năng:
1. Validate performance_result theo schema JSON.
2. Sinh JUnit XML từ kết quả đánh giá (chuẩn CI/CD tương thích Hercules).
3. Đóng gói proofs (script, ndjson, data pool) vào thư mục con proofs/ để đối soát.
"""
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Optional

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
RESULT_SCHEMA_PATH = ROOT / "schemas" / "performance_result.schema.json"


def build_junit_xml(result: Dict[str, Any], requirement: Optional[Dict[str, Any]] = None) -> str:
    """Tạo JUnit XML từ performance result và threshold evaluation.

    Mỗi threshold metric được biểu diễn thành 1 <testcase>.
    - FAIL -> <failure message="VIOLATED ...">
    - PASS_WITH_WARNING -> <system-out>WARNING ...</system-out>
    - PASS / SKIP -> thẻ testcase thông thường.
    """
    req = requirement or {}
    scenario_name = req.get("scenario_name") or result.get("perf_req_id", "PerfScenario")
    perf_run_id = result.get("perf_run_id", "PRUN")
    evals = result.get("threshold_evaluation") or []
    metrics = result.get("metrics") or {}

    total_tests = len(evals)
    failures = sum(1 for e in evals if e.get("result") == "FAIL")

    suite = ET.Element("testsuite", {
        "name": str(scenario_name),
        "id": str(perf_run_id),
        "tests": str(total_tests),
        "failures": str(failures),
        "errors": "0",
        "skipped": str(sum(1 for e in evals if e.get("result") == "SKIP")),
        "time": str(result.get("duration_actual_seconds", 0)),
        "timestamp": str(result.get("executed_at", "")),
    })

    props = ET.SubElement(suite, "properties")
    ET.SubElement(props, "property", {"name": "perf_req_id", "value": str(result.get("perf_req_id", ""))})
    ET.SubElement(props, "property", {"name": "profile", "value": str(result.get("profile", ""))})
    ET.SubElement(props, "property", {"name": "overall_status", "value": str(result.get("overall_status", ""))})
    ET.SubElement(props, "property", {"name": "action", "value": str(result.get("action", ""))})
    ET.SubElement(props, "property", {"name": "environment", "value": str(result.get("environment", ""))})
    ET.SubElement(props, "property", {"name": "throughput_rps", "value": str(metrics.get("throughput_rps", 0))})
    ET.SubElement(props, "property", {"name": "error_rate", "value": str(metrics.get("error_rate", 0))})
    ET.SubElement(props, "property", {"name": "p50_ms", "value": str(metrics.get("p50_ms", ""))})
    ET.SubElement(props, "property", {"name": "p95_ms", "value": str(metrics.get("p95_ms", ""))})
    ET.SubElement(props, "property", {"name": "p99_ms", "value": str(metrics.get("p99_ms", ""))})

    for ev in evals:
        metric = ev.get("metric", "unknown")
        threshold = ev.get("threshold")
        actual = ev.get("actual")
        status = ev.get("result", "PASS")

        case = ET.Element("testcase", {
            "name": str(metric),
            "classname": "PerformanceThreshold.{0}".format(result.get("perf_req_id", "Perf")),
            "time": "0",
        })

        if status == "FAIL":
            fail_el = ET.SubElement(case, "failure", {
                "message": "VIOLATED threshold {0}: actual={1} vs threshold={2}".format(
                    metric, actual, threshold),
                "type": "PerformanceThresholdViolation",
            })
            fail_el.text = "Metric {0} failed: actual={1} exceeded threshold={2}".format(
                metric, actual, threshold)
        elif status == "PASS_WITH_WARNING":
            sys_out = ET.SubElement(case, "system-out")
            sys_out.text = "WARNING: Metric {0} actual={1} passed within acceptable limit (target={2})".format(
                metric, actual, threshold)
        elif status == "SKIP":
            ET.SubElement(case, "skipped")

        suite.append(case)

    return ET.tostring(suite, encoding="utf-8", xml_declaration=True).decode("utf-8")


def save_report(
    result: Dict[str, Any],
    requirement: Dict[str, Any],
    output_dir: Path | str,
    script_path: Optional[Path | str] = None,
    data_path: Optional[Path | str] = None,
    ndjson_path: Optional[Path | str] = None,
    schema_path: Optional[Path | str] = None,
) -> Dict[str, Path]:
    """Validate kết quả, lưu performance_result.json, junit.xml và đóng gói proofs/."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1. Validate JSON schema
    s_path = Path(schema_path) if schema_path else RESULT_SCHEMA_PATH
    if s_path.is_file():
        schema = json.loads(s_path.read_text(encoding="utf-8"))
        jsonschema.validate(result, schema)

    # 2. Ghi performance_result.json & requirement.json
    res_file = out / "performance_result.json"
    res_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    req_file = out / "requirement.json"
    req_file.write_text(json.dumps(requirement, indent=2, ensure_ascii=False), encoding="utf-8")

    # 3. Ghi junit.xml
    junit_xml = build_junit_xml(result, requirement)
    junit_file = out / "junit.xml"
    junit_file.write_text(junit_xml, encoding="utf-8")

    # 4. Sao chép bằng chứng vào proofs/
    proofs_dir = out / "proofs"
    proofs_dir.mkdir(parents=True, exist_ok=True)

    copied = {
        "result": res_file,
        "requirement": req_file,
        "junit": junit_file,
        "proofs_dir": proofs_dir,
    }

    if script_path and Path(script_path).is_file():
        dest = proofs_dir / Path(script_path).name
        shutil.copy2(script_path, dest)
        copied["proof_script"] = dest

    if data_path and Path(data_path).is_file():
        dest = proofs_dir / Path(data_path).name
        shutil.copy2(data_path, dest)
        copied["proof_data"] = dest

    if ndjson_path and Path(ndjson_path).is_file():
        dest = proofs_dir / Path(ndjson_path).name
        shutil.copy2(ndjson_path, dest)
        copied["proof_ndjson"] = dest

    return copied


__all__ = ["build_junit_xml", "save_report"]
