"""Proof Store (Bước 11-17 — Execution Proofs).

Học từ Hercules: mỗi run phải để lại "proofs of execution" đầy đủ để không
ai phải tranh luận "it works on my computer". Layout thích ứng từ Hercules:

    {artifacts_dir}/proofs/{run_id}/
    ├── index.json                 # tổng quan run: case -> status -> files
    └── {test_case_id}/
        ├── result.json            # ExecutionResult (status, error, failed_step...)
        ├── network_logs.json      # network_events (method/url/status)
        ├── ui_evidence.json       # visible messages + dom_probe + page_url
        └── healing_events.json    # audit log self-healing (nếu có)

Khác Hercules (video/webm, trace.zip, accessibility): TestForge chạy Playwright
qua subprocess JSON report nên evidence lấy từ attachment evidence.json —
cùng bản chất (network + UI), bỏ phần media nặng.
"""

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

SAFE_ID = re.compile(r"[^A-Za-z0-9._-]+")


class ProofStore:
    """Ghi bundle bằng chứng thực thi cho một run của pipeline."""

    @classmethod
    def write_run_proofs(
        cls,
        run_id: str,
        artifacts: List[Dict[str, Any]],
        artifacts_dir: str,
    ) -> Dict[str, Any]:
        """Ghi proofs cho toàn bộ case của run.

        Returns:
            {"proofs_dir", "index_path", "cases": [...]}
        """
        safe_run = SAFE_ID.sub("_", str(run_id))
        run_dir = Path(artifacts_dir) / "proofs" / safe_run
        run_dir.mkdir(parents=True, exist_ok=True)

        index_cases: List[Dict[str, Any]] = []
        for artifact in artifacts or []:
            tc_id = str(artifact.get("test_case_id", "TC-UNKNOWN"))
            case_dir = run_dir / SAFE_ID.sub("_", tc_id)
            case_dir.mkdir(parents=True, exist_ok=True)

            files = cls._write_case_proofs(artifact, case_dir)
            index_cases.append({
                "test_case_id": tc_id,
                "status": artifact.get("status", "FAIL"),
                "files": files,
            })

        index = {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total": len(index_cases),
            "cases": index_cases,
        }
        index_path = run_dir / "index.json"
        index_path.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {
            "proofs_dir": str(run_dir),
            "index_path": str(index_path),
            "cases": index_cases,
        }

    @classmethod
    def _write_case_proofs(cls, artifact: Dict[str, Any], case_dir: Path) -> List[str]:
        """Ghi các file bằng chứng của một case; trả về danh sách tên file."""
        written: List[str] = []

        def dump(name: str, payload: Any) -> None:
            if payload is None:
                return
            path = case_dir / name
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            written.append(name)

        # result.json — luôn ghi (không silent pass: case FAIL vẫn có bằng chứng)
        result = {
            "test_case_id": artifact.get("test_case_id"),
            "status": artifact.get("status"),
            "duration_ms": artifact.get("duration_ms"),
            "failed_step": artifact.get("failed_step"),
            "error": artifact.get("error"),
            "artifacts": artifact.get("artifacts", []),
        }
        for key in ("execution_mode", "verification", "db_verification", "requirement_refs", "actor", "cleanup", "retest_result", "oracles", "api_checks"):
            if key in artifact:
                result[key] = artifact[key]
        copied = []
        for index, source in enumerate(artifact.get("artifacts") or []):
            path = Path(source)
            if path.is_file():
                filename = f"attachment-{index}-{SAFE_ID.sub('_', path.name)}"
                shutil.copy2(path, case_dir / filename)
                copied.append(filename)
                written.append(filename)
        result["copied_attachments"] = copied
        if artifact.get("script"):
            result["script_path"] = f"{artifact.get('test_case_id')}.spec.ts"
        dump("result.json", result)

        # network_logs.json + ui_evidence.json — từ evidence enrichment (real mode)
        network = artifact.get("network_events")
        ui_evidence = artifact.get("ui_evidence")
        if network is not None:
            dump("network_logs.json", network)
        if ui_evidence:
            dump("ui_evidence.json", ui_evidence)

        # healing_events.json — audit self-healing (M3.2 schema)
        if artifact.get("healing_events"):
            dump("healing_events.json", artifact["healing_events"])

        # defect.json — Application Defect Gate
        if artifact.get("defect"):
            dump("defect.json", artifact["defect"])

        return written
