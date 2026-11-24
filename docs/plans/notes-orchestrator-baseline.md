# Ghi chú baseline test — Gói G1 (hạ tầng chuyển đổi orchestrator)

> Mục đích: mốc so sánh trước khi hiện thực bất kỳ routing mới nào (G2+).
> Cách chạy:
> ```bash
> cd adlc-flow
> PYTHONPATH=$(pwd) .venv/bin/python -m pytest \
>   tests/unit/adlc/test_orchestrator_plugin.py \
>   tests/unit/adlc/test_executor_router.py \
>   tests/unit/api/v1/test_adlc_runs.py -v
> ```
> Nhánh baseline: `orchestrator-g1-baseline` (tách từ `orchestrator` sau khi merge
> `origin/main`, commit gốc `c1b18b9`). Chạy **trước** khi thêm flag
> `ADLC_ORCHESTRATOR_ROUTING`. Chỉ ghi tên test + trạng thái; không sửa test nào.

## Kết quả tổng

| Nhóm | Số test | PASSED | FAILED |
| --- | --- | --- | --- |
| tests/unit/adlc/test_orchestrator_plugin.py | 30 | 30 | 0 |
| tests/unit/adlc/test_executor_router.py | 2 | 2 | 0 |
| tests/unit/api/v1/test_adlc_runs.py | 8 | 4 | 4 |
| **Tổng** | **40** | **36** | **4** |

> ⚠️ 4 test FAILED trong `test_adlc_runs.py` là **lỗi có sẵn trên nhánh sạch,
> trước mọi thay đổi của G1** (code `adlc/delivery.py::ensure_run_authority`
> gọi `session.exec` còn mock trong test là `SimpleNamespace` thiếu thuộc tính
> đó — phát sinh khi merge `origin/main`). G1 không đụng tới các file này;
> mốc nghiệm thu của G2+ là: các test này **không red thêm** so với baseline.

## Danh sách test

### tests/unit/adlc/test_orchestrator_plugin.py

| Test | Trạng thái |
| --- | --- |
| TestInterfaceModels::test_intent_requires_description | PASSED |
| TestInterfaceModels::test_intent_default_capabilities_empty | PASSED |
| TestInterfaceModels::test_plan_step_requires_capabilities | PASSED |
| TestInterfaceModels::test_execution_plan_requires_steps | PASSED |
| TestInterfaceModels::test_plugin_metadata_requires_capabilities | PASSED |
| TestMonarchPlugin::test_metadata | PASSED |
| TestMonarchPlugin::test_plan_produces_single_step | PASSED |
| TestMonarchPlugin::test_plan_uses_intent_capabilities | PASSED |
| TestMonarchPlugin::test_execute_plan_only_mode | PASSED |
| TestMonarchPlugin::test_execute_with_mock_agent | PASSED |
| TestMonarchPlugin::test_reflect_summarizes_result | PASSED |
| TestDeepSeekHarnessPlugin::test_metadata_disabled_by_default | PASSED |
| TestDeepSeekHarnessPlugin::test_execute_stub_mode | PASSED |
| TestDeepSeekHarnessPlugin::test_reflect_suggests_wiring_client | PASSED |
| TestOrchestratorHost::test_register_and_get | PASSED |
| TestOrchestratorHost::test_get_unknown_raises | PASSED |
| TestOrchestratorHost::test_unregister | PASSED |
| TestOrchestratorHost::test_register_replaces | PASSED |
| TestOrchestratorHost::test_list_metadata | PASSED |
| TestOrchestratorHost::test_list_enabled_excludes_disabled | PASSED |
| TestOrchestratorHost::test_find_capable | PASSED |
| TestOrchestratorHost::test_find_capable_excludes_disabled | PASSED |
| TestOrchestratorHost::test_dispatch_plan_with_explicit_plugin | PASSED |
| TestOrchestratorHost::test_dispatch_plan_auto_selects | PASSED |
| TestOrchestratorHost::test_dispatch_plan_no_capable_raises | PASSED |
| TestOrchestratorHost::test_dispatch_execute_uses_plan_plugin | PASSED |
| TestOrchestratorHost::test_dispatch_reflect_uses_result_plugin | PASSED |
| TestOrchestratorHost::test_dispatch_execute_unknown_plugin_raises | PASSED |
| TestDefaultHost::test_get_default_host_returns_singleton | PASSED |
| TestDefaultHost::test_reset_clears_singleton | PASSED |

### tests/unit/adlc/test_executor_router.py

| Test | Trạng thái |
| --- | --- |
| test_router_dispatches_a_package_service_alias_to_its_executor | PASSED |
| test_router_fails_an_unregistered_service_without_falling_back | PASSED |

### tests/unit/api/v1/test_adlc_runs.py

| Test | Trạng thái |
| --- | --- |
| test_adlc_controller_reads_saved_flow_and_exposes_run_resources | FAILED (có sẵn trước G1) |
| test_adlc_controller_returns_contract_validation_error | FAILED (có sẵn trước G1) |
| test_legacy_run_endpoint_rejects_a_different_explicit_mode | PASSED |
| test_required_adlc_routes_are_registered | PASSED |
| test_opencode_readiness_endpoint_is_authenticated_and_secret_free | PASSED |
| test_harness_callback_route_uses_hmac_not_end_user_auth | PASSED |
| test_harness_control_routes_are_owner_scoped_and_forward_exact_session | FAILED (có sẵn trước G1) |
| test_saved_flow_slice_works_through_mounted_http_routes | FAILED (có sẵn trước G1) |
