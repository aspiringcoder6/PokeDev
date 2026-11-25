"""JUnit XML Reporter (Bước 20 — CI/CD handoff).

Học từ Hercules (junit_helper): kết quả test xuất JUnit XML để Jenkins/GitLab/
Azure DevOps/AnyCI tiêu thụ trực tiếp. Pattern hai pha của Hercules:
  per-scenario XML -> merge -> suite-level roll-up.
TestForge làm 1 pha (pipeline đã chạy tuần tự) nhưng giữ format tương thích.

Nguyên tắc "không silent pass" (Hercules): mọi case kết thúc khác PASS đều
phải có <failure message="EXPECTED ... ACTUAL ..."> — CI không bao giờ thấy
PASS giả do report lỗi.
"""

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional


class JUnitReporter:
    """Xuất Functional Result + artifacts thành JUnit XML."""

    @classmethod
    def build_testsuite(cls, functional_result: Dict[str, Any], artifacts: List[Dict[str, Any]]) -> ET.Element:
        """Dựng <testsuite> từ Functional Result + executed artifacts."""
        fr = functional_result
        suite = ET.Element("testsuite", {
            "name": str(fr.get("feature", "Feature")),
            "id": str(fr.get("run_id", "RUN")),
            "tests": str(fr.get("total", 0)),
            "failures": str(fr.get("failed", 0)),
            "errors": "0",
            "skipped": "0",
            "time": "0",
            "timestamp": fr.get("run_id", ""),
        })

        props = ET.SubElement(suite, "properties")
        for key in (
            "gate_passed", "status", "recommended_next_stage",
            "initial_pass_rate", "healed_pass_rate",
            "healing_attempts", "healing_success_rate", "false_repair_rate",
            "execution_mode", "proposal_rejection_rate",
        ):
            ET.SubElement(props, "property", {"name": key, "value": str(fr.get(key))})
        healing = fr.get("healing") or {}
        ET.SubElement(props, "property", {"name": "healing_successful", "value": str(healing.get("successful", 0))})
        ET.SubElement(props, "property", {"name": "defects", "value": ",".join(fr.get("defects", []))})

        for artifact in artifacts or []:
            suite.append(cls._testcase(artifact))
        cases = suite.findall("testcase")
        suite.set("tests", str(len(cases)))
        for tag, attr in (("failure", "failures"), ("error", "errors"), ("skipped", "skipped")):
            suite.set(attr, str(sum(c.find(tag) is not None for c in cases)))
        return suite

    @classmethod
    def _testcase(cls, artifact: Dict[str, Any]) -> ET.Element:
        """Dựng <testcase> cho một case; FAIL/DEFECT/SCRIPT_FAILURE -> <failure>."""
        status = str(artifact.get("status", "FAIL"))
        tc_id = str(artifact.get("test_case_id", "TC-UNKNOWN"))
        case = ET.Element("testcase", {
            "name": tc_id,
            "classname": str(artifact.get("feature", "")),
            "time": str(artifact.get("duration_ms", 0) / 1000.0),
        })

        if status in ("SIMULATED", "SKIPPED") or artifact.get("execution_mode") == "simulated":
            ET.SubElement(case, "skipped", {"message": "Not executed against application"})
            return case
        if status == "ERROR":
            ET.SubElement(case, "error", {"message": str(artifact.get("error") or "Required execution/verification unavailable")})
            return case
        if status in ("PASS", "HEALED_PASS"):
            out = ET.SubElement(case, "system-out")
            out.text = cls._pass_summary(artifact)
            return case

        failure = ET.SubElement(case, "failure", {
            "message": cls._failure_message(artifact),
            "type": status,
        })
        failure.text = cls._failure_body(artifact)
        return case

    @classmethod
    def _pass_summary(cls, artifact: Dict[str, Any]) -> str:
        """system-out cho case PASS (oracle trace + healing, không che KPI)."""
        lines = [f"Status: PASS"]
        trace = artifact.get("oracle_trace") or []
        for t in trace:
            lines.append(f"oracle: {t.get('expected_result')} -> {t.get('assertion')}")
        if artifact.get("proposal_source"):
            lines.append(f"healed_by: {artifact['proposal_source']} retests={artifact.get('retest_count')}")
        return "\n".join(lines)

    @classmethod
    def _failure_message(cls, artifact: Dict[str, Any]) -> str:
        """EXPECTED/ACTUAL format (pattern Hercules assert_summary) + phân loại."""
        status = artifact.get("status", "FAIL")
        analysis = artifact.get("failure_analysis") or {}
        failure_type = analysis.get("failure_type", "UNKNOWN") if isinstance(analysis, dict) else ""
        if status == "APPLICATION_DEFECT":
            defect = artifact.get("defect") or {}
            return f"APPLICATION_DEFECT: {defect.get('actual', 'Application error')}"
        sv = artifact.get("static_validation") or {}
        if status == "SCRIPT_FAILURE" and sv.get("errors"):
            return f"SCRIPT_FAILURE: {sv['errors'][0].get('code', 'SV?')} {sv['errors'][0].get('message', '')[:120]}"
        return f"{status} ({failure_type})" if failure_type else str(status)

    @classmethod
    def _failure_body(cls, artifact: Dict[str, Any]) -> str:
        """Thân failure: EXPECTED vs ACTUAL + evidence pointers."""
        analysis = artifact.get("failure_analysis") or {}
        defect = artifact.get("defect") or {}
        expected = defect.get("expected") or analysis.get("expected") or ""
        actual = defect.get("actual") or artifact.get("error") or analysis.get("error") or ""
        lines = [f"EXPECTED RESULT: {expected}", f"ACTUAL RESULT: {actual}"]
        if artifact.get("healing_events"):
            lines.append("HEALING ATTEMPTS:")
            for ev in artifact["healing_events"]:
                lines.append(f"  - {ev.get('stage')}: {ev.get('detail', '')}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Serializer
    # ------------------------------------------------------------------
    @classmethod
    def build_xml_string(
        cls,
        suites: List[ET.Element],
        name: str = "TestForge AI — Agent 1 Functional",
    ) -> str:
        root = ET.Element("testsuites", {"name": name})
        for s in suites:
            root.append(s)
        ET.indent(root, space="  ")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")

    @classmethod
    def from_functional_result(
        cls,
        functional_result: Dict[str, Any],
        artifacts: List[Dict[str, Any]],
    ) -> str:
        """Convenience: 1 result -> XML string."""
        return cls.build_xml_string([cls.build_testsuite(functional_result, artifacts)])
