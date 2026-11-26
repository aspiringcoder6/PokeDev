# Regression của luồng tiếp nhận PokeDev

Phạm vi ledger này là intake và các consumer trực tiếp, không đại diện toàn bộ repository kế thừa. Baseline xanh: `8fc0426`, 295 backend / 22 connector / 7 UI, PostgreSQL và production build. Audit LI-03 so với baseline, gồm cả diff staged, unstaged và file mới. Điểm kiểm tra LI03-01 → LI03-08 nằm trong [kế hoạch LI-03](plans/li03-implementation.md).

## Contract và backend intake

Downstream: router HTTP, connector, UI intake và bootstrap/migration. Bằng chứng: `rg -n 'pokedev_lark_contracts|lark_intake|LarkLinkPanel' adlc-flow/langflow/api services/lark-connector adlc-flow/frontend/src/features/requirement-intake deploy/local`.

Lệnh nghiệm thu từ gốc repository:

```powershell
adlc-flow/.venv/Scripts/python.exe -m pytest -o addopts='' --confcutdir=adlc-flow/tests/unit/adlc adlc-flow/tests/unit/adlc/source_access adlc-flow/tests/unit/adlc/requirement_readiness adlc-flow/tests/unit/adlc/test_requirement_intake.py adlc-flow/tests/unit/adlc/test_lark_intake.py adlc-flow/tests/unit/adlc/test_lark_conversations.py adlc-flow/tests/unit/adlc/test_harness_client.py -q
```

Thay đổi hợp đồng/router/model phải chạy lệnh trên, connector, UI, PostgreSQL opt-in và build. Source access/readiness/Harness được kiểm tra vì router/bootstrap dùng cùng nền; không chạy tác vụ model thật.

## Connector

Downstream: ingress API và outbox result API; journal v1/v2 đã ghi là consumer tương thích bắt buộc. Bằng chứng: `rg -n 'Backend|InboundMessage|DeliveryResult|Worker' services/lark-connector/connector.py`.

```powershell
services/lark-connector/.venv/Scripts/python.exe -m pytest services/lark-connector/test_probe.py services/lark-connector/test_connector.py -q
```

Thay đổi normalizer/wire/gửi tin phải chạy connector và backend; thử thật chỉ trong nhóm/DM pilot được người dùng cho phép.

## UI desktop

Downstream: người dùng xem nguồn và chọn đúng request. Bằng chứng: import trong `intake-page.tsx`, các endpoint `/adlc/intake/lark` và `/adlc/intake/requests`.

```powershell
Push-Location adlc-flow/frontend
./node_modules/.bin/jest.cmd src/features/requirement-intake --runInBand
Pop-Location
python deploy/local/stack.py frontend
```

Chạy lại khi API/hiển thị thay đổi; kiểm chứng browser desktop trên backend mới. Không thêm layout mobile.

## PostgreSQL

`deploy/local/check_intake_postgres.py` là lệnh opt-in (`POKEDEV_TEST_POSTGRES=1`) trong app container có source/contract đúng phiên bản. Script tạo schema UUID riêng và rollback toàn bộ; không dùng dữ liệu public làm fixture. Chạy khi model, migration, transaction, binding hoặc receipt thay đổi. Ghi exit code và kết quả trong runbook của slice; không suy từ SQLite thành PostgreSQL đã đạt.

## Audit LI-03 — 26/11/2026

Base: `8fc0426`; phạm vi gồm diff staged/unstaged và các file mới trong nhánh `codex/lark-conversations`. Imports/call-sites đã được rà theo các lệnh trên; không có consumer bị tác động nào được miễn kiểm tra.

| Lệnh nghiệm thu | Exit code | Bằng chứng local |
|---|---|---|
| Backend toàn bộ phạm vi đã nêu | 0 — 316 passed | `adlc-flow/data/local/tests-li03-regression-final.log` |
| Connector và probe | 0 — 34 passed | `adlc-flow/data/local/tests-li03-connector-final.log` |
| UI intake | 0 — 12 passed | `adlc-flow/data/local/tests-li03-frontend.log` |
| Production build | 0 | `adlc-flow/data/local/build-li03-frontend.log` |
| PostgreSQL opt-in với source/contract bind mount | 0 — `POSTGRES_INTAKE_AND_LARK_CONVERSATIONS_OK` | `adlc-flow/data/local/tests-li03-postgres-final.log` |

PostgreSQL dùng schema riêng được rollback toàn bộ và container database thử đã dừng lại sau kiểm tra. Giới hạn và kết quả thử tenant thật được ghi tách trong [runbook](operations/lark-li03.md); các exit code xanh không tự chứng minh SDK redelivery hoặc hỗ trợ tin không @.
