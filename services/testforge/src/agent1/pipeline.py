"""Agent 1 Pipeline Orchestrator (20-Step End-to-End Workflow).

Điều phối toàn diện quy trình 20 bước từ ADLC Memory đến Functional Quality Gate.
"""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from .memory.adlc_memory_client import ADLCMemoryClient
from .normalizer.input_normalizer import InputNormalizer
from .validators.input_validator import TestInputValidator
from .validators.test_case_validator import TestCaseValidator
from .designer.test_design_agent import TestDesignAgent
from .generator.playwright_generator import PlaywrightGenerator
from .generator.static_validator import StaticValidator
from .generator.artifact_store import ArtifactStore
from .executor.runner import PlaywrightExecutor
from .executor.verification_engine import VerificationEngine
from .analyzer.failure_analyzer import FailureAnalyzer
from .healer.graph import run_healing
from .healer.state import OUTCOME_FAILED, OUTCOME_HEALED_PASS, OUTCOME_REJECTED, OUTCOME_STOP_DEFECT
from .healer.tier1_deterministic import Tier1DeterministicHealer
from .healer.tier2_ai_recovery import Tier2AIRecovery
from .healer.retest_manager import RetestManager
from .reporter.defect_reporter import DefectReporter
from .reporter.functional_reporter import FunctionalReporter
from .reporter.junit_reporter import JUnitReporter
from .reporter.proof_store import ProofStore


class Agent1Pipeline:
    """Orchestrator thực thi luồng 20 bước cho Functional Automation Test Agent."""

    def __init__(
        self,
        memory_client: Optional[ADLCMemoryClient] = None,
        design_agent: Optional[TestDesignAgent] = None,
        executor: Optional[PlaywrightExecutor] = None,
        verification_engine: Optional[VerificationEngine] = None,
        healer_tier1: Optional[Tier1DeterministicHealer] = None,
        healer_tier2: Optional[Tier2AIRecovery] = None,
        retest_manager: Optional[RetestManager] = None,
        static_validate: bool = True,
        artifacts_dir: Optional[str] = None,
        real_execution: bool = False,
        execution_mode: Optional[str] = None,
        accept_healed: bool = False,
    ):
        self.memory = memory_client or ADLCMemoryClient()
        self.designer = design_agent or TestDesignAgent()
        self.executor = executor or PlaywrightExecutor()
        self.verifier = verification_engine or VerificationEngine()
        self.healer_tier1 = healer_tier1 or Tier1DeterministicHealer()
        self.healer_tier2 = healer_tier2 or Tier2AIRecovery()
        self.retester = retest_manager or RetestManager()
        self.static_validate = static_validate
        self.execution_mode = execution_mode or ("local" if real_execution else "simulated")
        if self.execution_mode not in ("local", "simulated"):
            raise ValueError("Pipeline supports local/simulated; sandbox requires its dedicated harness")
        self.real_execution = self.execution_mode != "simulated"
        self.artifacts_dir = artifacts_dir or ("artifacts/automation/runs" if self.real_execution else None)
        self.accept_healed = accept_healed

    def run_pipeline(
        self, project_id: str, function_id: str, context_refs=None,
        simulated_execution_hook=None, on_case_complete=None,
    ) -> Dict[str, Any]:
        """Always return a closed gate and a reportable case on setup/runtime errors."""
        try:
            result = self._run_pipeline(project_id, function_id, context_refs,
                                        simulated_execution_hook, on_case_complete)
            if "functional_result" in result:
                return result
        except Exception as exc:
            result = {"status": "ERROR", "errors": [{"code": type(exc).__name__, "message": str(exc)}]}
        artifact = {"test_case_id": "SETUP-ERROR", "status": "ERROR", "execution_mode": self.execution_mode,
                    "error": str(result.get("errors", []))}
        fr = FunctionalReporter.compile_functional_result("RUN-" + uuid.uuid4().hex, function_id,
            1, 0, 1, execution_mode=self.execution_mode)
        fr.update(status="ERROR", gate_passed=False, exit_code=2)
        result.update(functional_result=fr, artifacts=[artifact], defect_reports=[])
        if self.artifacts_dir:
            try:
                result["reports"] = self._write_ci_reports(fr, [artifact])
            except OSError as exc:
                result["report_error"] = type(exc).__name__
        return result

    def _run_pipeline(
        self,
        project_id: str,
        function_id: str,
        context_refs: Optional[List[str]] = None,
        simulated_execution_hook: Optional[Any] = None,
        on_case_complete: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Chạy toàn bộ quy trình kiểm thử 20 bước.

        Args:
            project_id: Mã dự án
            function_id: Mã chức năng
            context_refs: Tham chiếu bộ nhớ ADLC
            simulated_execution_hook: Hàm giả lập kết quả thực thi (dùng cho test)
            on_case_complete: Callback(artifact_dict) gọi sau MỖI test case xử lý xong
                (stream tiến độ cho UI/demo; None = im lặng)

        Returns:
            Dict chứa toàn bộ artifacts và Functional Result cuối cùng
        """
        # Bước 1 & 2: ADLC Memory -> Relevant Requirement Context
        run_id = f"RUN-{uuid.uuid4().hex}"
        run_dir = str(Path(self.artifacts_dir) / run_id) if self.artifacts_dir else None
        if self.real_execution and simulated_execution_hook is not None:
            raise ValueError("Simulation hooks cannot be used in a real run")
        req_context = self.memory.fetch_requirement_context(project_id, function_id, context_refs)

        # Bước 3: Chuẩn bị Standard Test Input (5 trường)
        std_input = self.memory.to_standard_test_input(req_context)

        # Bước 4: Test Input Validator (Quy tắc IN001-IN005, Zero-LLM)
        input_val_res = TestInputValidator.validate(std_input)
        if not input_val_res["valid"]:
            return {
                "step_completed": 4,
                "status": "INPUT_VALIDATION_FAILED",
                "errors": input_val_res["errors"],
            }

        # Bước 3.5: Input Normalizer (chuẩn hóa nội bộ, Zero-LLM)
        # 5 trường biên giới -> Internal Test Context machine-readable cho downstream
        internal_ctx = InputNormalizer.normalize(
            std_input,
            business_rules=req_context.get("business_rules", []),
            validation_rules=req_context.get("validation_rules", []),
        )
        ctx_val_res = InputNormalizer.validate_internal_context(internal_ctx)
        if not ctx_val_res["valid"]:
            return {
                "step_completed": 4,
                "status": "NORMALIZATION_FAILED",
                "errors": ctx_val_res["errors"],
            }

        # Bước 5 & 6: Test Design Agent -> Structured Test Cases
        test_cases = self.designer.design_test_cases(std_input, internal_context=internal_ctx)

        # Bước 7: Test Case Validator (Contradiction & Schema check)
        all_rules = req_context.get("business_rules", []) + req_context.get("validation_rules", [])
        suite_val_res = TestCaseValidator.validate_test_suite(
            test_cases, expected_function_id=function_id, input_rules=all_rules
        )
        if not suite_val_res["valid"]:
            return {
                "step_completed": 7,
                "status": "TEST_CASE_VALIDATION_FAILED",
                "errors": suite_val_res["errors"],
            }

        # Thực thi từng Test Case
        passed_count = 0
        initial_passed = 0  # PASS ngay lần đầu (trước healing) — KPI transparency
        failed_count = 0
        healing_attempted = 0
        healing_successful = 0
        healing_rejected = 0  # proposal bị anti-cheat gate chặn (false repair tiềm năng)
        defect_reports: List[Dict[str, Any]] = []
        executed_artifacts: List[Dict[str, Any]] = []

        def _emit(artifact: Dict[str, Any]) -> None:
            """Append artifact + stream tiến độ cho callback (demo/UI)."""
            artifact["execution_mode"] = self.execution_mode
            if self.execution_mode == "simulated" and artifact.get("status") in ("PASS", "HEALED_PASS"):
                artifact["status"] = "SIMULATED"
            executed_artifacts.append(artifact)
            if on_case_complete:
                on_case_complete(artifact)

        for tc in test_cases:
            tc_id = tc["test_case_id"]

            # Bước 8: Sinh Playwright Script
            script_code = PlaywrightGenerator.generate_script(tc)

            # Bước 9: Static Validation (chặn script lỗi trước khi tốn tài nguyên browser)
            if self.static_validate:
                static_res = StaticValidator.validate(script_code, tc)
                if not static_res["valid"]:
                    failed_count += 1
                    _emit({
                        "test_case_id": tc_id,
                        "status": "SCRIPT_FAILURE",
                        "static_validation": static_res,
                    })
                    continue

            # Bước 10: Lưu script artifact ra đĩa (nếu cấu hình artifacts_dir)
            spec_path = None
            if self.artifacts_dir:
                saved = ArtifactStore.save_script(tc, script_code, artifacts_dir=run_dir)
                spec_path = saved["spec_path"]
            # Bước 9.5: TypeScript compile / Playwright discovery check
            # (loader thật của Playwright transpile + đăng ký spec — bắt lỗi cú pháp/import
            #  mà Static Guard heuristic không thấy. Chạy TRƯỚC khi tốn browser.)
            if self.real_execution and spec_path:
                discovery = self.executor.discovery_check(spec_path)
                if not discovery.get("ok"):
                    failed_count += 1
                    _emit({
                        "test_case_id": tc_id,
                        "status": "SCRIPT_FAILURE",
                        "stage": "compile",
                        "static_validation": {"valid": False, "errors": [
                            {"code": "SV900", "line": 1, "message": discovery.get("stderr", "")[:200]}
                        ]},
                    })
                    continue

            # Bước 11: Playwright Sandboxed Execution (simulated hoặc real runtime)
            sim_outcome = simulated_execution_hook(tc) if simulated_execution_hook else None
            exec_res = self.executor.execute_script(
                tc_id,
                script_code,
                simulated_outcome=sim_outcome,
                script_path=spec_path,
                real_runtime=self.real_execution and spec_path is not None and sim_outcome is None,
            )
            if self.real_execution and exec_res.get("execution_mode") != "local":
                exec_res.update(status="ERROR", error="Real execution provenance missing or simulated")

            # Bước 12 & 13: Result Verification & PASS/FAIL (UI/API/DB qua verifiers)
            verify_res = self.verifier.verify(
                exec_res,
                tc.get("verification_strategy"),
                internal_context=internal_ctx,
            )

            if exec_res.get("status") == "SIMULATED":
                failed_count += 1
                _emit({"test_case_id": tc_id, "status": "SIMULATED", "script": script_code,
                       "oracle_trace": PlaywrightGenerator.build_oracle_trace(tc), "verification": verify_res})
                continue
            if verify_res["final_status"] == "ERROR":
                failed_count += 1
                _emit({**exec_res, "status": "ERROR", "verification": verify_res})
                continue

            if verify_res["final_status"] == "PASS":
                passed_count += 1
                initial_passed += 1
                _emit({
                    "test_case_id": tc_id,
                    "feature": tc.get("feature", ""),
                    "status": "PASS",
                    "script": script_code,
                    "oracle_trace": PlaywrightGenerator.build_oracle_trace(tc),
                    "duration_ms": exec_res.get("duration_ms", 0),
                    "network_events": exec_res.get("network_events"),
                    "ui_evidence": exec_res.get("ui_evidence"),
                    "artifacts": exec_res.get("artifacts", []),
                    "verification": verify_res,
                })
                continue

            # Xử lý khi FAIL:
            # Bước 14-17: Failure Analysis + Self-healing orchestration (LangGraph)
            # - analyze/defect-stop/heal/validate/retest điều phối trong healing graph
            # - Guardrail: APPLICATION_DEFECT -> STOP (outcome STOP_DEFECT)
            def retest_verified(test_case_id, repaired_script):
                result = self._retest_runner(test_case_id, repaired_script, artifacts_dir=run_dir)
                checked = self.verifier.verify(result, tc.get("verification_strategy"))
                return {**result, "status": checked["final_status"], "verification": checked}

            healing = run_healing(
                test_case=tc,
                execution_result=exec_res,
                script_code=script_code,
                retest_runner=retest_verified,
                tier1_healer=self.healer_tier1,
                tier2_healer=self.healer_tier2,
                max_retries=3,
            )
            failure_analysis = healing["failure_analysis"]

            # Bước 18-19: Application Defect Gate -> STOP + Defect Report
            if healing["outcome"] == OUTCOME_STOP_DEFECT:
                failed_count += 1
                defect_execution = healing.get("retest_result") or exec_res
                defect = DefectReporter.create_defect_report(
                    function_id=function_id,
                    test_case_id=tc_id,
                    expected="; ".join(tc.get("expected_results", [])),
                    actual=str(defect_execution.get("error", "Application Error")),
                    evidence=defect_execution.get("artifacts", []),
                )
                defect_reports.append(defect)
                _emit({
                    "test_case_id": tc_id,
                    "feature": tc.get("feature", ""),
                    "status": "APPLICATION_DEFECT",
                    "defect": defect,
                    "healing_events": healing["healing_events"],
                    "duration_ms": exec_res.get("duration_ms", 0),
                    "network_events": exec_res.get("network_events"),
                    "ui_evidence": exec_res.get("ui_evidence"),
                })
                continue

            if healing["outcome"] == OUTCOME_HEALED_PASS:
                healing_attempted += 1
                healing_successful += 1
                passed_count += int(self.accept_healed)
                failed_count += int(not self.accept_healed)
                _emit({
                    "test_case_id": tc_id,
                    "status": "HEALED_PASS" if self.accept_healed else "REVIEW",
                    "retest_result": healing.get("retest_result"),
                    "proposal": healing["proposal"],
                    "proposal_source": healing["proposal_source"],
                    "retest_count": healing["retest_count"],
                    "healing_events": healing["healing_events"],
                    "oracle_trace": PlaywrightGenerator.build_oracle_trace(tc),
                })
                continue

            # NOT_HEALABLE / FAILED_HEAL / REJECTED
            if healing["outcome"] in (OUTCOME_FAILED, OUTCOME_REJECTED):
                healing_attempted += 1
            if healing["outcome"] == OUTCOME_REJECTED:
                healing_rejected += 1
            failed_count += 1
            _emit({
                "test_case_id": tc_id,
                "feature": tc.get("feature", ""),
                "status": "FAIL",
                "failure_analysis": failure_analysis,
                "healing_events": healing["healing_events"],
                "duration_ms": exec_res.get("duration_ms", 0),
                "network_events": exec_res.get("network_events"),
                "ui_evidence": exec_res.get("ui_evidence"),
            })

        # Bước 20: Functional Result & Quality Gate Evaluation
        defect_ids = [d["defect_id"] for d in defect_reports]
        functional_result = FunctionalReporter.compile_functional_result(
            run_id=run_id,
            feature=std_input["feature"],
            total=len(test_cases),
            passed=passed_count,
            failed=failed_count,
            healing_attempted=healing_attempted,
            healing_successful=healing_successful,
            healing_rejected=healing_rejected,
            defect_ids=defect_ids,
            initial_passed=initial_passed,
            execution_mode=self.execution_mode,
        )
        if any(a["status"] == "ERROR" for a in executed_artifacts):
            functional_result["status"] = "ERROR"
        functional_result["exit_code"] = (2 if functional_result["status"] == "ERROR"
                                          else 0 if functional_result["gate_passed"] else 1)

        # Bước 20.1: CI/CD handoff — JUnit XML + Proofs bundle (nếu có artifacts_dir)
        reports: Dict[str, Any] = {}
        if self.artifacts_dir:
            reports = self._write_ci_reports(functional_result, executed_artifacts)

        return {
            "step_completed": 20,
            "status": "COMPLETED",
            "functional_result": functional_result,
            "defect_reports": defect_reports,
            "artifacts": executed_artifacts,
            **({"reports": reports} if reports else {}),
        }

    def _write_ci_reports(
        self,
        functional_result: Dict[str, Any],
        artifacts: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Ghi JUnit XML (CI consumption) + Proofs bundle (evidence audit).

        Pattern học từ Hercules: report never silently passes — mọi case
        khác PASS phải có <failure message="EXPECTED ... ACTUAL ...">.
        """
        reports: Dict[str, Any] = {}
        junit_dir = Path(self.artifacts_dir) / "junit"
        junit_dir.mkdir(parents=True, exist_ok=True)
        safe_run = re.sub(r"[^A-Za-z0-9._-]+", "_", functional_result.get("run_id", "RUN"))
        junit_path = junit_dir / f"{safe_run}.xml"
        junit_path.write_text(
            JUnitReporter.from_functional_result(functional_result, artifacts),
            encoding="utf-8",
        )
        reports["junit_xml"] = str(junit_path)

        proofs = ProofStore.write_run_proofs(
            run_id=functional_result.get("run_id", safe_run),
            artifacts=artifacts,
            artifacts_dir=self.artifacts_dir,
        )
        reports["proofs_dir"] = proofs["proofs_dir"]
        reports["proofs_index"] = proofs["index_path"]
        return reports

    def _retest_runner(self, test_case_id: str, repaired_script: str, artifacts_dir=None) -> Dict[str, Any]:
        """Bước 17: chạy lại script đã vá trong môi trường thật (hoặc simulated).

        Simulated mode: trả PASS giữ pipeline thông (backward compatible).
        Real execution: lưu script vá (không ghi đè spec gốc) và chạy Playwright thật.
        """
        if not (self.real_execution and self.artifacts_dir):
            return {"test_case_id": test_case_id, "status": "SIMULATED", "execution_mode": "simulated", "duration_ms": 0}
        saved = ArtifactStore.save_script(
            {"test_case_id": f"{test_case_id}-RETEST", "function_id": "RETEST", "feature": "healed retest"},
            repaired_script,
            artifacts_dir=artifacts_dir or self.artifacts_dir,
            script_version="1.0.0-retest",
        )
        return self.executor.execute_script(
            test_case_id, repaired_script, script_path=saved["spec_path"], real_runtime=True
        )
