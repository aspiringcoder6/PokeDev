# adlc_components — bản vá sẵn cho nền tảng ADLC

Thư mục này chứa **những "linh kiện" làm nên nội dung của nền tảng ADLC**. Ứng dụng (`adlc-flow/`) là cái khung; thư mục này cung cấp:

1. **Node packages** — định nghĩa có phiên bản cho từng loại giai đoạn công việc,
2. **Flow mẫu** — các bản demo nhập thẳng vào canvas để xem nền tảng hoạt động,
3. **Custom components** — các khối dựng sẵn mức thấp dành cho việc phát triển package.

```text
adlc_components/
├── packages/            # ⭐ Node package registry — "nội dung" của mỗi giai đoạn
├── flow/                # 6 flow mẫu (poke-dev-01 → 06) để import vào canvas
├── custom_component/    # Khối mức thấp: agent, model, tool, prompt…
├── package-roadmap/     # Danh mục kế hoạch phát triển package
└── README.md
```

## Node packages (`packages/`) — nền tảng biết chạy gì

Khi bạn dựng một blueprint, mỗi **giai đoạn** (stage) trên canvas không chứa model, prompt hay công cụ nào cả — nó chỉ **trỏ tới một node package theo phiên bản**, ví dụ `coding-agent@0.2.1`. Package mới là nơi khai báo: agent dùng model nào, có những công cụ gì, chạy với chính sách Sandbox/timeout/retry ra sao.

Vì sao quan trọng? **Một phiên bản đã xuất bản là bất biến** — kế hoạch đã duyệt hôm trước vẫn chạy y hệt hôm nay dù bạn nâng cấp package. Muốn thay đổi thì tạo phiên bản mới.

```text
packages/coding-agent/0.2.1/package.json   ← một phiên bản package = một thư mục
```

Các package hiện có:

| Package | Dùng khi nào |
|---|---|
| `approval` | Giai đoạn dừng chờ con người phê duyệt |
| `coding-agent` | Coding agent cơ bản (mock — để thử cơ chế không tốn phí) |
| `coding-agent-opencode` | Cho agent thật chạy qua OpenCode |
| `coding-agent-deepseek-harness` | Cho agent thật chạy qua DeepSeek Harness |
| `coding-agent-contract-harness` | Agent thực thi theo Hợp đồng qua Harness |
| `skilltree-authoring-deepseek-harness` | Soạn roadmap/kỹ năng qua Harness |
| `task-loop` | Vòng lặp "làm → kiểm thử → sửa" (mock) |
| `task-loop-opencode` | Vòng lặp đó với OpenCode thật |

Backend tự tìm thấy thư mục này (tìm `adlc_components/packages` ngược từ vị trí mã nguồn), nên bạn không cần cấu hình gì. Muốn dùng registry ở chỗ khác: đặt biến `ADLC_NODE_PACKAGE_ROOT`.

## Flow mẫu (`flow/`) — xem nền tảng chạy thật

Import bằng cách **kéo file `.json` thả vào canvas** (hoặc qua menu import của giao diện). Sáu flow theo thứ tự một "khoá học" nhỏ:

| Flow | Bạn sẽ thấy gì |
|---|---|
| `poke-dev-01-dieu-phoi-va-phe-duyet.json` | Luồng cơ bản nhất: các giai đoạn nối tiếp và một cổng phê duyệt dừng chờ bạn bấm duyệt. |
| `poke-dev-02-loi-va-retry.json` | Khi một nhiệm vụ thất bại: hệ thống tự thử lại theo chính sách retry, ghi nhận mỗi lần thử. |
| `poke-dev-03-de-xuat-ke-hoach.json` | Planning Agent đọc yêu cầu và **đề xuất** cách phân rã công việc; bạn duyệt trước khi chạy. |
| `poke-dev-04-agent-va-source-patch.json` | Agent sửa code thật; bạn xem **bản vá (patch)** nó đã làm và duyệt/từ chối từng thay đổi. |
| `poke-dev-05-soan-roadmap.json` | Soạn tài liệu roadmap dạng máy đọc được (Skilltree) qua Harness. |
| `poke-dev-06-thuc-thi-contract.json` | Mở rộng: công việc chạy theo **Hợp đồng** — yêu cầu được duyệt trước, kết quả được đối chiếu từng chữ sau. |

## Custom components (`custom_component/`) — dành cho người phát triển package

Đây là các khối mức thấp dùng khi **đóng gói package mới** (thử nghiệm agent, model, tool ở dạng riêng lẻ trước khi gói vào stage). Người dùng cuối bình thường không cần đụng tới.

Muốn nạp vào canvas để thử:

```bash
PYTHONPATH=$(pwd) .venv/bin/python -m langflow.__main__ run \
  --host 127.0.0.1 --port 7860 --backend-only \
  --components-path <đường-dẫn>/adlc_components/custom_component
```

Cấu trúc: `agents/` (orchestrator), `models/` (kết nối model AI), `tools/` (bộ công cụ cho agent), `system_prompts/` (builder prompt), cùng các thư mục trống sẵn chỗ cho `hooks/`, `plugins/`, `skills/`.

### Component OpenCode Model

`custom_component/models/opencode.py` cho phép kéo một node model kết nối tới [OpenCode Zen](https://opencode.ai/zen/v1) ngay trên canvas:

1. Lấy API key (miễn phí) tại https://opencode.ai/auth → trang **Keys** (dạng `sk-...`).
2. Trên node, điền: **Base URL** (`https://opencode.ai/zen/v1`), **API Key**, **Model Name** (ví dụ `deepseek-v4-flash-free`), **Temperature**.
3. Hoặc đặt biến môi trường `OPENCODE_API_KEY` thay vì nhập tay.

> Ghi chú: model free có lúc quá tải và trả lỗi `429` — chọn model khác trong danh sách (ví dụ `nemotron-3-ultra-free`). Component không đọc file trên máy bạn; API key chỉ nằm trong UI hoặc biến môi trường.
