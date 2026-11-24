# vAIPlatform — điều phối AI agent viết phần mềm từ đầu đến cuối

**ADLC** (Agentic Development Life Cycle) là nền tảng web cho phép bạn **giao một công việc lập trình cho AI agent** và **giám sát toàn bộ quá trình** đó: từ câu yêu cầu thô, đến kế hoạch công việc, code do agent viết, kết quả kiểm thử, cho tới quyết định phê duyệt cuối cùng của con người.

Điểm khác biệt của ADLC so với các công cụ "AI viết code" thông thường: **mọi việc đều minh bạch và có con người kiểm soát** — AI không tự ý làm rồi báo cáo cho có, mà phải trình kế hoạch để duyệt, chạy từng bước trong môi trường cô lập, tự kiểm chứng kết quả, và dừng chờ bạn ở mọi điểm then chốt. Toàn bộ quá trình để lại bằng chứng: kế hoạch đã duyệt, từng lần thử, bản vá code, log, kết quả kiểm thử.

```
Bạn viết yêu cầu  ──►  AI sinh bản thiết kế (Blueprint)  ──►  AI đề xuất kế hoạch
                                                                     │
Con người duyệt ◄────────────────────────────────────────────────────┘
      │
      ▼
Nền tảng chạy từng nhiệm vụ ──► Agent viết code trong Sandbox ──► Tự kiểm thử
      │
      ├─ Lỗi?  → tự sửa và thử lại (retry / task loop)
      ├─ Bước nhạy cảm? → tạm dừng, chờ con người phê duyệt
      └─ Xong?  → báo cáo, artifact, log, token... để bạn kiểm tra
```

> **Dùng thử không cần cài gì ngoài Git, Python, Node.js.** Mặc định mọi thứ chạy **mock** (không tốn tiền API); bạn chỉ bật agent thật (OpenCode hoặc DeepSeek Harness) khi muốn.

---

## Nó hoạt động thế nào?

1. **Tạo Blueprint** — Bạn nhập yêu cầu bằng tiếng Việt hoặc tiếng Anh (ví dụ: *"Tạo trang web hiển thị trái tim, bấm vào thì hiện chữ Hello World"*). Trợ lý AI chuyển yêu cầu thành **Blueprint** — sơ đồ các **giai đoạn** (stage) của công việc, ví dụ: Lập kế hoạch → Code → Kiểm thử → Duyệt.
2. **Duyệt kế hoạch** — Planning Agent phân rã blueprint thành danh sách **nhiệm vụ** (task) cụ thể. Bạn xem, sửa, rồi phê duyệt. Không duyệt thì không chạy.
3. **Chạy (Run)** — Nền tảng thực thi từng nhiệm vụ theo đúng thứ tự phụ thuộc. Mỗi nhiệm vụ được giao cho một **coding agent** chạy bên trong **Sandbox** (bản sao Git worktree tách biệt, không đụng code thật của bạn).
4. **Giám sát** — Màn hình Run Detail cho thấy: vòng lặp mỗi nhiệm vụ, số lần thử, bản vá (patch) agent đã sửa, ảnh chụp/log/kết quả kiểm thử, số token tiêu tốn.
5. **Phê duyệt xen kẽ** — Ở các bước nhạy cảm (trước khi chạy, trước hành động quan trọng, hoặc trước khi nhận kết quả), hệ thống dừng và chờ bạn bấm duyệt / từ chối.
6. **Kết quả** — Kết quả cuối kèm toàn bộ bằng chứng thực thi (evidence). Với luồng nâng cao, kết quả được đối chiếu với một **Hợp đồng (Contract)** — tài liệu yêu cầu do công cụ soạn, con người duyệt, máy xác minh từng điều khoản.

Mọi thay đổi trạng thái đều ghi thành **sự kiện (event)** có thứ tự — bạn luôn biết chuyện gì xảy ra, khi nào, do ai.

### Thuật ngữ cần biết

| Thuật ngữ | Nghĩa |
|---|---|
| **Blueprint** | Sơ đồ các giai đoạn công việc bạn muốn AI thực hiện. |
| **Stage (Giai đoạn)** | Một bước trong blueprint, ví dụ "Implement Backend". Mỗi stage dùng một **node package** — bản dựng có phiên bản, chứa sẵn model, prompt, công cụ cho agent. |
| **Kế hoạch (Plan)** | Danh sách nhiệm vụ cụ thể do AI đề xuất từ blueprint, cần được phê duyệt trước khi chạy. |
| **Nhiệm vụ (Task)** | Một đơn vị công việc; có thể chạy lại nhiều lần (mỗi lần là một **lần thử / attempt**). |
| **Run (Lần chạy)** | Một phiên thực thi toàn bộ kế hoạch, có trạng thái: chạy / chờ duyệt / thành công / thất bại… |
| **Approval (Phê duyệt)** | Cổng dừng chờ con người quyết định, ba loại: trước nhiệm vụ, trước hành động nhạy cảm, sau khi hoàn thành. |
| **Sandbox** | Môi trường cô lập (Git worktree / container Docker) để agent viết và chạy code an toàn. |
| **Task Loop** | Chế độ lặp: agent làm → máy kiểm thử → sửa lỗi → lặp lại tới khi đạt, giới hạn số vòng. |
| **Contract (Hợp đồng)** | Tài liệu yêu cầu dạng máy đọc được, được duyệt trước và đối chiếu từng chữ sau khi thực thi. |
| **Harness / DSH** | DeepSeek Harness — máy chủ thực thi agent bên ngoài mà nền tảng kết nối tới qua SDK. |
| **Node package** | Định nghĩa có phiên bản của một loại stage (ví dụ `coding-agent@0.2.1`). Nâng cấp package = tạo phiên bản mới, không sửa bản cũ. |

---

## Cấu trúc repository

```text
.
├── adlc-flow/            # Ứng dụng chính: backend Python (FastAPI) + frontend React
├── adlc_components/      # Node packages (theo phiên bản), custom components, flow mẫu
├── adlc-contracts/       # Định nghĩa dữ liệu chia sẻ (JSON Schema) giữa các thành phần
├── sdk/                  # dsh_web_sdk — SDK Python để nói chuyện với DeepSeek Harness
├── docs/                 # Tài liệu kiến trúc, state machine, ADR (quyết định thiết kế)
├── BASELINE.md           # Ghi nhận trạng thái kỹ thuật ban đầu của repo
└── Readme.md             # (bạn đang đọc file này)
```

## Cài đặt từ đầu

### Yêu cầu

| Công cụ | Phiên bản đã chạy tốt |
|---|---|
| Git | bất kỳ phiên bản gần đây |
| Python | 3.10 – 3.14 (đã thử: 3.14) |
| Node.js + npm | 20+ (đã thử: 22 và 24) |
| uv | bất kỳ (cài theo [docs.astral.sh/uv](https://docs.astral.sh/uv/)) |

Không bắt buộc Docker — môi trường local dùng SQLite và sandbox dạng Git worktree.

### Bước 1 — Lấy mã nguồn và tạo file cấu hình

```bash
git clone <repository-url>
cd VDT-ADLC
cp .env.example .env
```

Mở `.env` và xem các giá trị. Với lần chạy đầu, giữ nguyên mặc định là đủ: hệ thống chạy **mock**, không cần API key nào. Chỉ khi muốn dùng agent thật bạn mới điền thêm (xem mục [Cấu hình](#cấu-hình-biến-môi-trường) bên dưới).

### Bước 2 — Cài backend

```bash
cd adlc-flow
uv venv .venv --clear
uv pip install -r requirements.txt
uv pip install -e ../sdk      # SDK DeepSeek Harness, cần cho phần sinh blueprint và Harness
```

### Bước 3 — Chạy backend (terminal 1)

```bash
cd adlc-flow
PYTHONPATH=$(pwd) .venv/bin/python -m langflow.__main__ run \
  --host 127.0.0.1 --port 7860 --backend-only --env-file ../.env
```

Khi thấy log "server listening" là backend đã chạy tại `http://127.0.0.1:7860`. Trên Windows, thay `PYTHONPATH=$(pwd) …` bằng `set PYTHONPATH=%cd%` rồi gọi `.venv\Scripts\python.exe …`.

### Bước 4 — Chạy giao diện (terminal 2)

```bash
cd adlc-flow/frontend
npm install
npm run dev
```

Mở **http://localhost:3000**. Giao diện tự nối tới backend ở bước 3 (qua biến `BACKEND_URL`, mặc định `http://localhost:7860`). Môi trường local **tự động đăng nhập**, không cần tài khoản.

> Giao diện mặc định hiển thị **tiếng Việt**. Đổi sang English trong phần cài đặt của ứng dụng, sau đó nhấn F5 để nạp lại.

### Bước 5 — Kiểm tra cài đặt

Bạn sẽ thấy: canvas kéo–thả (nơi dựng blueprint), thanh công cụ bên trái với nhóm **ADLC** (nút tạo AI Blueprint, chạy ADLC…). Tạo và lưu được một flow trống là cài đặt đã ổn.

---

## Dùng thử lần đầu (~10 phút)

1. Trên thanh công cụ, mở **AI Blueprint**. Hộp thoại hiện sẵn **ví dụ Heart App** — một yêu cầu trang web mini. Giữ nguyên và gửi.
2. Hệ thống gọi AI sinh **blueprint** gồm các giai đoạn. Xem lại sơ đồ giai đoạn trên canvas.
3. Chạy blueprint ở chế độ ADLC: hệ thống chuyển sang màn hình **đề xuất kế hoạch** — danh sách nhiệm vụ AI phân rã. Đọc, chỉnh nếu muốn, rồi **phê duyệt**.
4. Kế hoạch được duyệt sẽ bắt đầu **chạy**. Mở màn hình **Run Detail** để theo dõi: mỗi nhiệm vụ có timeline, số lần thử, log, artifact.
5. Khi nhiệm vụ chờ ở **cổng phê duyệt**, màn hình hiện nút duyệt/từ chối — bấm duyệt để tiếp tục.
6. Kết thúc: xem tổng kết lần chạy (thành công/thất bại từng nhiệm vụ, token đã dùng, kết quả kiểm thử).

Muốn xem nhanh các tính năng mà không cần agent thật: import một **flow mẫu** từ `adlc_components/flow/` (kéo file `.json` thả vào canvas). Sáu flow `poke-dev-01` → `poke-dev-06` lần lượt minh họa: điều phối + phê duyệt, xử lý lỗi + retry, đề xuất kế hoạch, agent sửa code + review bản vá, soạn roadmap, thực thi hợp đồng.

---

## Cấu hình biến môi trường

Chỉnh trong file `.env` (đầy đủ nhất là `.env.example`). Ba nhóm chính:

**Cơ bản (để mặc định là chạy được):**

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `LANGFLOW_DATABASE_URL` | SQLite local | Nơi lưu dữ liệu. Production nên dùng PostgreSQL. |
| `LANGFLOW_AUTO_LOGIN` | bật | Tự đăng nhập local, không cần mật khẩu. |
| `ADLC_SUBTASK_GENERATION_MODE` | mock | Chế độ sinh nhiệm vụ con. |

**Coding Agent — OpenCode (tùy chọn):**

| Biến | Ý nghĩa |
|---|---|
| `ADLC_OPENCODE_ENABLED` | Đặt `true` để mở khóa agent OpenCode thật. |
| `ADLC_OPENCODE_SOURCE_REPOSITORY` | Repo Git dùng làm nguồn tạo worktree cho mỗi nhiệm vụ. |
| `ADLC_OPENCODE_SERVER_URL` / `_USERNAME` / `_PASSWORD` | Địa chỉ và thông tin đăng nhập OpenCode headless server. |
| `ADLC_OPENCODE_MODEL` | Model dạng `provider/model`. |

**DeepSeek Harness / DSH (tùy chọn):**

| Biến | Ý nghĩa |
|---|---|
| `ADLC_HARNESS_ENABLED`, `ADLC_HARNESS_BASE_URL`, `ADLC_HARNESS_API_TOKEN` | Kết nối tới máy chủ Harness. |
| `ADLC_HARNESS_CALLBACK_SECRET` | Khóa xác thực callback từ Harness về nền tảng. |
| `ADLC_DSH_GOAL_ENABLED` | Bật driver "goal" tự thúc đẩy phiên DSH. |

> Nguyên tắc: **không có cấu hình nào = chạy mock**. Agent thật chỉ được dùng khi bạn bật tường minh — và secret (mật khẩu, API key) không bao giờ được ghi vào blueprint, kế hoạch hay log.

## Kiểm thử và build

```bash
# Backend — từ thư mục adlc-flow/
.venv/bin/python -m pytest tests -x -q

# Frontend — từ thư mục adlc-flow/frontend/
npx jest                                        # unit test
npx tsc --noEmit                                # kiểm tra kiểu TypeScript
NODE_OPTIONS="--max-old-space-size=8192" npm run build   # build production
```

## Xử lý sự cố thường gặp

| Triệu chứng | Cách xử lý |
|---|---|
| Build frontend bị killed / hết bộ nhớ | Thêm `NODE_OPTIONS="--max-old-space-size=8192"` trước lệnh build. |
| Model free trả lỗi `429` (quá tải) | Chọn model khác trong danh sách (ví dụ `nemotron-3-ultra-free`). |
| Đổi ngôn ngữ nhưng giao diện chưa đổi | Nhấn **F5** — gói ngôn ngữ được nạp khi tải trang. |
| Dữ liệu thử nghiệm rối, muốn bắt đầu lại | Dừng backend, xóa `adlc-flow/adlc-local.db*`, khởi động lại (mất toàn bộ run/flow local). |
| Port 7860/3000 bị chiếm | Đổi `--port` của backend và `BACKEND_URL` trong `.env` cho khớp. |
| Backend báo thiếu `dsh_web_sdk` | Chạy `uv pip install -e ../sdk` trong thư mục `adlc-flow/`. |

## Tài liệu sâu hơn

- [Kiến trúc hệ thống](./docs/architecture.md) — các tầng, ranh giới trách nhiệm
- [State machine thực thi](./docs/state-machine.md) — vòng đời run/task/phê duyệt, sự kiện
- [Kiến trúc node package](./docs/node-package-architecture.md) — package theo phiên bản, cách plan được biên dịch
- [Quyết định kiến trúc (ADR)](./docs/adr/README.md) — vì sao chọn thiết kế này
- [Hợp đồng & schemas](./adlc-contracts/README.md) — định dạng dữ liệu giữa các thành phần
- [SDK DeepSeek Harness](./sdk/README.md)

## Bảo mật

- Không bao giờ commit `.env`, API key, mật khẩu hay token.
- Code do agent sinh ra **chỉ chạy trong Sandbox**, không đụng máy thật.
- Giá trị nhạy cảm được lưu dưới dạng **tham chiếu** (`secret_refs`), chỉ được giải mã đúng lúc điều phối nhiệm vụ, không bao giờ nằm trong log hay sự kiện.
- Hành động phá hủy yêu cầu được cho phép tường minh; MCP và tool giới hạn theo danh sách cho phép của từng nhiệm vụ.

## Nguồn gốc

Dự án dựa trên [Langflow](https://github.com/langflow-ai/langflow) (bản 1.12.0). Chi tiết tái lập bản gốc xem [BASELINE.md](./BASELINE.md).

## License

Giữ nguyên license và attribution gốc của Langflow; các yêu cầu license phát sinh thêm từ dependency của ADLC sẽ được ghi nhận tại đây.
