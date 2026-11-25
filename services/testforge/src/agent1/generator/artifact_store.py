"""Automation Script Artifact Store (Bước 10).

Nhiệm vụ:
- Lưu Playwright script sinh ra ra đĩa: artifacts/automation/{test_case_id}.spec.ts
- Lưu metadata JSON đi kèm: {test_case_id}.meta.json (function_id, script_version, generated_at, checksum)
- Lưu oracle traceability: {test_case_id}.oracle.json (expected_result -> assertion, SV006)
- Trả về đường dẫn để executor (Bước 11) đọc lại khi chạy thật.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

SAFE_ID_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


class ArtifactStore:
    """Quản lý lưu trữ script kiểm thử và metadata trên đĩa."""

    DEFAULT_DIR = "artifacts/automation"

    @classmethod
    def save_script(
        cls,
        test_case: Dict[str, Any],
        script_code: str,
        artifacts_dir: Optional[str] = None,
        script_version: str = "1.0.0",
        generator_model: str = "deterministic-v2",
    ) -> Dict[str, Any]:
        """Lưu script + metadata ra đĩa.

        Args:
            test_case: Structured Test Case gốc
            script_code: Nội dung mã nguồn .spec.ts
            artifacts_dir: Thư mục lưu (mặc định artifacts/automation)
            script_version: Phiên bản script
            generator_model: Model/generator sinh script

        Returns:
            {"spec_path", "meta_path", "test_case_id"}
        """
        tc_id = str(test_case.get("test_case_id", "TC-UNKNOWN"))
        safe_id = SAFE_ID_PATTERN.sub("_", tc_id)
        base = Path(artifacts_dir or cls.DEFAULT_DIR)
        base.mkdir(parents=True, exist_ok=True)

        spec_path = base / f"{safe_id}.spec.ts"
        meta_path = base / f"{safe_id}.meta.json"
        oracle_path = base / f"{safe_id}.oracle.json"

        spec_path.write_text(script_code, encoding="utf-8")

        metadata = {
            "test_case_id": tc_id,
            "function_id": test_case.get("function_id", ""),
            "feature": test_case.get("feature", ""),
            "type": test_case.get("type", ""),
            "script_version": script_version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generator_model": generator_model,
            "spec_file": spec_path.name,
            "checksum_sha256": cls._checksum(script_code),
        }
        meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        # SV006 Oracle Traceability Record: mỗi expected_result -> assertion
        from .playwright_generator import PlaywrightGenerator
        oracle_trace = PlaywrightGenerator.build_oracle_trace(test_case)
        oracle_path.write_text(
            json.dumps(oracle_trace, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        return {
            "test_case_id": tc_id,
            "spec_path": str(spec_path),
            "meta_path": str(meta_path),
            "oracle_path": str(oracle_path),
        }

    @classmethod
    def load_metadata(cls, test_case_id: str, artifacts_dir: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Đọc lại metadata của một script đã lưu (traceability).

        Returns:
            Dict metadata hoặc None nếu không tồn tại
        """
        safe_id = SAFE_ID_PATTERN.sub("_", str(test_case_id))
        meta_path = Path(artifacts_dir or cls.DEFAULT_DIR) / f"{safe_id}.meta.json"
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _checksum(content: str) -> str:
        """Tính SHA-256 của nội dung script (phát hiện script bị sửa sau lưu)."""
        import hashlib
        return hashlib.sha256(content.encode("utf-8")).hexdigest()
