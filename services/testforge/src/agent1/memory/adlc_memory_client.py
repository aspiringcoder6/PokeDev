"""ADLC Memory Client (Bước 1 & Bước 2).

Nhiệm vụ:
- Bước 1: Nhận project_id, function_id, context_refs để truy xuất đúng context cần thiết từ ADLC Memory.
- Bước 2: Chuẩn bị Relevant Requirement Context cho chức năng kiểm thử.
"""

from typing import Any, Dict, List, Optional


class ADLCMemoryClient:
    """Client kết nối và truy vấn ngữ cảnh từ ADLC Memory."""

    def __init__(self, memory_store: Optional[Dict[str, Dict[str, Any]]] = None):
        """Khởi tạo với bộ nhớ cục bộ hoặc kết nối ADLC Memory service.

        Args:
            memory_store: Mock data store dạng {project_id: {function_id: context}}
        """
        self._memory_store: Dict[str, Dict[str, Any]] = memory_store or {}

    def register_function_context(
        self, project_id: str, function_id: str, context: Dict[str, Any]
    ) -> None:
        """Đăng ký context vào memory store (dùng cho testing/mock)."""
        if project_id not in self._memory_store:
            self._memory_store[project_id] = {}
        self._memory_store[project_id][function_id] = context

    def register_gherkin(self, project_id: str, gherkin_text: str) -> List[str]:
        """Bước 0 (Gherkin In): parse .feature -> đăng ký mỗi scenario là function.

        Học từ Hercules ("Gherkin in, results out") nhưng deterministic Zero-LLM:
        Scenario Outline + Examples được expand bằng GherkinParser, không để LLM
        tự suy diễn test data.

        Returns:
            Danh sách function_id đã đăng ký (mỗi scenario một function).
        """
        from ..normalizer.gherkin_parser import GherkinParser

        registered: List[str] = []
        for scenario in GherkinParser.parse(gherkin_text):
            self.register_function_context(
                project_id=project_id,
                function_id=scenario["function_id"],
                context=GherkinParser.to_function_context(scenario),
            )
            registered.append(scenario["function_id"])
        return registered

    def fetch_requirement_context(
        self,
        project_id: str,
        function_id: str,
        context_refs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Bước 1 -> Bước 2: Truy xuất Relevant Requirement Context theo function_id.

        Args:
            project_id: Mã dự án (e.g. 'P01')
            function_id: Mã chức năng (e.g. 'FUNC-USER-ADD')
            context_refs: Danh sách URI tham chiếu bộ nhớ

        Returns:
            Dict chứa Relevant Requirement Context
        """
        project_data = self._memory_store.get(project_id, {})
        context = project_data.get(function_id)

        if not context:
            # Trả về fallback / minimal context nếu không tìm thấy
            return {
                "function_id": function_id,
                "feature": "Unknown Feature",
                "business_rules": [],
                "validation_rules": [],
                "ui_flow": [],
                "context_refs": context_refs or [],
            }

        return {
            "function_id": function_id,
            "feature": context.get("feature", ""),
            "business_rules": context.get("business_rules", []),
            "validation_rules": context.get("validation_rules", []),
            "ui_flow": context.get("ui_flow", []),
            "precondition": context.get("precondition", []),
            "expected_result": context.get("expected_result", []),
            "test_data": context.get("test_data", {}),
            "rejection_message": context.get("rejection_message", ""),
            "context_refs": context_refs or [],
        }

    def to_standard_test_input(self, req_context: Dict[str, Any]) -> Dict[str, Any]:
        """Chuyển đổi Relevant Requirement Context thành Standard Test Input (5 trường).

        Args:
            req_context: Dictionary kết quả từ Bước 2

        Returns:
            Standard Test Input contract (5 trường chuẩn)
        """
        return {
            "function_id": req_context.get("function_id", ""),
            "feature": req_context.get("feature", ""),
            "precondition": req_context.get("precondition", ["User is authenticated"]),
            "steps": req_context.get("ui_flow", []),
            "expected_result": req_context.get("expected_result", [
                f"{req_context.get('feature', 'Action')} completed successfully"
            ]),
            "business_rules": req_context.get("business_rules", []),
            "validation_rules": req_context.get("validation_rules", []),
            "test_data": req_context.get("test_data", {}),
            "rejection_message": req_context.get("rejection_message", ""),
        }
