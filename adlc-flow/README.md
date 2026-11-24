# adlc-flow — ứng dụng chính của nền tảng ADLC

Đây là **ứng dụng bạn chạy mỗi ngày** khi dùng nền tảng ADLC: backend Python (FastAPI) kế thừa lõi canvas kéo–thả mã nguồn mở của Langflow, cộng thêm frontend React.

Điểm mới của ứng dụng là lớp hoàn chỉnh gọi là **ADLC control plane**: khả năng mô tả quy trình phát triển phần mềm theo giai đoạn, sinh kế hoạch bằng AI, chạy coding agent trong môi trường cô lập, quản lý phê duyệt của con người, và ghi lại toàn bộ bằng chứng thực thi.

Ứng dụng gồm hai phần chạy song song:

```text
┌────────────────────────┐         ┌────────────────────────────┐
│  frontend/ (React)     │  HTTP   │  langflow/ (Python backend)│
│  http://localhost:3000 │ ──────► │  http://127.0.0.1:7860     │
│  Canvas kéo–thả, màn   │         │  API, cơ sở dữ liệu,       │
│  hình run, phê duyệt   │         │  toàn bộ logic ADLC        │
└────────────────────────┘         └────────────────────────────┘
```

Frontend ở chế độ dev tự chuyển tiếp (proxy) mọi lời gọi API sang backend — bạn không cần cấu hình gì thêm. Nếu backend chạy ở nơi khác, đặt `BACKEND_URL` trong file `.env` ở thư mục gốc của repo.

## Chạy nhanh

Cần cài đặt lần đầu? Xem [Readme.md ở thư mục gốc](../Readme.md) — mục "Cài đặt từ đầu".

```bash
# Terminal 1 — backend (từ thư mục adlc-flow/)
PYTHONPATH=$(pwd) .venv/bin/python -m langflow.__main__ run \
  --host 127.0.0.1 --port 7860 --backend-only --env-file ../.env

# Terminal 2 — frontend (từ thư mục adlc-flow/frontend/)
npm install    # chỉ cần lần đầu
npm run dev    # mở http://localhost:3000
```

## Cấu trúc thư mục

```text
adlc-flow/
├── langflow/             # Backend Python (FastAPI) — lõi canvas lấy từ Langflow
│   └── adlc/             #   ⭐ toàn bộ logic ADLC nằm ở đây (xem bảng dưới)
├── frontend/             # Giao diện React/TypeScript (Vite)
│   └── src/
│       ├── pages/RunDetailPage/   # Màn hình chi tiết lần chạy: timeline, lần thử,
│       │                          #   phê duyệt, bản vá nguồn, artifact…
│       ├── components/adlc/       # Panel và trình xem Hợp đồng (Contract)
│       ├── features/              # adlc-blueprint (tạo blueprint), adlc-workspace,
│       │                          #   plan-proposal (duyệt kế hoạch)…
│       └── locales/               # Bản dịch UI: en.json, vi.json
├── lfx/                  # Thành phần lfx đi kèm
├── scripts/              # Script sinh JSON Schema và chạy demo task loop
├── tests/                # Kiểm thử pytest (unit + integration)
└── adlc-local.db         # Cơ sở dữ liệu SQLite local (tự tạo, bị gitignore)
```

## Logic ADLC nằm đâu? (`langflow/adlc/`)

| Nhóm | Module tiêu biểu | Làm gì |
|---|---|---|
| Blueprint & kế hoạch | `blueprint_generator.py`, `plan_parser.py`, `plan_validator.py`, `planning/` | Đổi yêu cầu thành blueprint; parse, phân rã và xác thực kế hoạch (DAG, slot, package). |
| Điều phối | `plan_orchestrator.py`, `plan_executor.py`, `run_service.py`, `run_persistence.py` | Vòng đời của lần chạy: lịch chạy theo phụ thuộc, retry tự động, tạm dừng, khôi phục sau crash. |
| Thực thi | `executor_router.py`, `coding_agent*.py`, `adapters/` | Chọn executor cho từng nhiệm vụ; agent runtime; adapter OpenCode và DSH. |
| Harness | `harness_*.py` | Nói chuyện với DeepSeek Harness: phiên làm việc, callback có chữ ký, artifact, xác minh kết quả. |
| Task loop | `task_loop*.py` | Vòng lặp "làm → kiểm thử → sửa" có giới hạn vòng, kiểm thử được bảo vệ không cho agent sửa. |
| Hợp đồng | `contract_*.py` | Soạn, duyệt, thực thi và đối chiếu từng chữ Hợp đồng sau khi chạy. |
| Hạ tầng vận hành | `triggers.py`, `metrics.py`, `cron.py`, `expressions.py`, `evidence_plane/`, `resource_manager/` | Chạy định lịch, metrics + cảnh báo, biểu thức mẫu `{{task...}}`, kho bằng chứng, cấp phát tài nguyên. |
| Node package | `packages/` | Registry các stage đóng gói theo phiên bản (mặc định tìm thấy ở `../adlc_components/packages`). |
| Orchestrator plugin | `orchestrator_plugin/` | Điểm cắm orchestrator bên ngoài (Monarch/OpenCode, DeepSeek Harness). |

Muốn hiểu kiến trúc tổng thể: đọc [docs/architecture.md](../docs/architecture.md) ở thư mục gốc.

## Kiểm thử

```bash
# Backend (từ thư mục adlc-flow/)
.venv/bin/python -m pytest tests -x -q

# Frontend (từ thư mục adlc-flow/frontend/)
npx jest                                        # unit test
npx tsc --noEmit                                # kiểm tra kiểu
NODE_OPTIONS="--max-old-space-size=8192" npm run build   # build production
```

## Lưu ý vận hành

- **Cơ sở dữ liệu**: local dùng SQLite (`adlc-local.db`). Xóa file này (khi backend đang dừng) để reset toàn bộ dữ liệu dùng thử. Production dùng PostgreSQL qua `LANGFLOW_DATABASE_URL`.
- **Agent thật phải bật tường minh**: mặc định mọi thứ chạy mock; OpenCode bật bằng `ADLC_OPENCODE_ENABLED=true`, DeepSeek Harness bằng `ADLC_HARNESS_ENABLED=true` (cấu hình trong `.env` ở thư mục gốc).
- **Ngôn ngữ UI**: mặc định tiếng Việt, có thể đổi sang English trong phần cài đặt; cần F5 sau khi đổi.
