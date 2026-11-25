---
name: testforge-ai
description: >
  Quy trình test tự động TestForge AI (Agent 1 Functional + Agent 2 Performance +
  Agent 3 Recommendation) qua broker. Dùng khi cần: sinh/chạy test browser từ requirement
  (5-field JSON/Gherkin), replay + Promotion Gate, healing locator, regression
  suite, performance/load test k6, capacity estimation, chẩn đoán nguyên nhân perf FAIL,
  hoặc LẤY DỮ LIỆU TESTCASE từ Agent Memory. KHÔNG dùng cho code review hay git operations.
---

# TestForge AI — Quy trình chuẩn

## Kiến trúc (đọc 1 lần để hiểu timeout + path)

- Tools gọi **TestForge Broker** (FastAPI, hiện tại `10.0.10.195:9099`) — broker spawn
  subprocess pipeline thật (Playwright Chromium + k6) trên host broker.
- **Path truyền vào tools là path trên broker host** (VD `opt/testspec/...`, `artifacts/...`),
  KHÔNG phải filesystem DSH của bạn.
- **Password không bao giờ truyền trực tiếp** — chỉ truyền TÊN env (`password_env`), broker host
  tự resolve (VD `STAGING_TTEAMFLOW_ADMIN_PASSWORD`).
- Tool explore/replay/staging/perf là **long-running**: tool tự poll giúp bạn (tối đa ~300s).
  Nếu trả `{status: "running", note: ...}` → poll tiếp bằng `testforge_result {job_id}`.

## Secrets & cấu hình (đã hot-reload)

- `TESTFORGE_BROKER_URL` — URL broker (đặt trong Secrets vault hoặc patch.yml config).
- `TESTFORGE_BROKER_TOKEN` — Bearer token broker (nếu broker bật auth).

## Luồng 1 — Functional test từ requirement

1. `testforge_health` — broker online? SUT reachable? (SUT phải up TRƯỚC, broker không dậy stack)
2. `testforge_explore {input_json: "opt/testspec/xxx.standard.json", base_url, api_url, email}`
   (hoặc `{feature: "opt/gherkin/xxx.feature", ...}`) — chờ 60-300s, kết quả chứa `session_dir`.
3. `testforge_replay {session: <session_dir>, api_url, email}` — Promotion Gate 10/10;
   kết quả chứa `promotion.promoted` (true = spec đủ chất lượng promote).

## Luồng 2 — Regression suite

1. `testforge_health`
2. `testforge_staging {profile: "config/tteamflow.staging.docker.json", suite: "opt/staging/xxx.json"}`
   — kết quả `summary.gate_passed` + `summary.status` (PASS/FAIL) + JUnit + proofs.

## Luồng 3 — Performance test

1. `testforge_health` — k6_installed phải true.
2. `testforge_staging` TRƯỚC nếu chưa có gate functional PASS (perf bị block nếu gate FAIL).
3. `testforge_perf {requirement: "opt/perf/perf_login.json", profile: "smoke", capacity_report: true}`
   — kết quả `performance_result` (p50/p95/p99, RPS, error_rate, overall_status) + `capacity`
   (peak_rps, saturation_observed, bottleneck_signals).

## Luồng 4 — Lấy testcase từ Agent Memory (memory-driven testing)

1. `testforge_health` — kiểm tra `agent_memory.reachable = true`.
2. `testforge_fetch_testcase {dataset: "testforge-P01", query: "Add User", function_id: "FUNC-USER-ADD"}`
   — trả RAW chunks + entities.
3. **Đọc các chunk, tự map về 5-field Standard Test Input**:
   `function_id` (mã chức năng/tên scenario) · `feature` (tên chức năng) · `precondition`
   (điều kiện trước) · `steps` (các bước) · `expected_result` (kết quả mong đợi).
4. Lưu payload thành file JSON (qua sandbox tools) rồi chạy
   `testforge_explore {input_json: <file>, ...}`.
   LƯU Ý: input thiếu trường sẽ bị validator (IN001-IN005) chặn STOP — đó là thiết kế,
   đừng "đoán" giá trị thiếu, hỏi lại nguồn (chunk khác hoặc user).
5. Dataset mới cần upload + cognify trên Agent Memory API/dashboard TRƯỚC
   (broker chỉ đọc — không upload).

## Luồng 5 — Chẩn đoán perf FAIL (Agent 3)

1. `testforge_health` — broker v1.3+.
2. Perf vừa FAIL? `testforge_recommend {}` (rỗng = tự lấy PRUN FAIL mới nhất, có LLM)
   hoặc `{perf_run: "PRUN-xxxx", capacity: true, context: "nginx vừa đổi worker..."}`.
   Nhanh không LLM: `{no_llm: true}`.
3. Kết quả REC JSON: `issue_summary` (số liệu thật từ PRUN), `likely_causes` (confidence),
   `recommendations` (priority HIGH/MEDIUM/LOW). Đọc để đề xuất hành động cho user.

## Luồng 6 — Full pipeline E2E

staging (gate) → explore (session) → replay (promotion) → perf (+capacity) →
recommend (nếu perf FAIL) → tổng hợp report.

## Bảng lỗi thường gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `broker unreachable` | Broker chưa chạy / sai URL/token | Kiểm tra `testforge_health`; host chạy `python testforge_broker.py` |
| `401 Unauthorized` | Thiếu/sai `TESTFORGE_BROKER_TOKEN` | Cập nhật Secrets vault (hot-reload, không cần restart) |
| Job `failed` ngay | SUT chưa up / path sai / password env chưa đặt | Đọc `error` + `output.tail` trong kết quả job |
| `fetch-testcase` 502 | Agent Memory chưa chạy | Dậy stack Agent Memory (docker-compose) hoặc bỏ Luồng 4 |
| Plugin poll timeout, job vẫn chạy | Job dài hơn 300s | `testforge_result {job_id}` lặp lại đến completed/failed |
