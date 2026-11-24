# adlc-flow/frontend — giao diện nền tảng ADLC

Đây là phần giao diện (React + TypeScript, dựng bằng **Vite**) của ứng dụng chính. Bạn thường chỉ cần đọc file này khi muốn phát triển giao diện — hướng dẫn cài đặt và chạy toàn bộ nền tảng nằm ở [Readme.md gốc](../../Readme.md).

## Giao diện gồm những gì?

- **Canvas kéo–thả** (ReactFlow) — nơi dựng/sửa flow và blueprint ADLC.
- **Thanh công cụ ADLC** — nút "Tạo Blueprint", "AI Blueprint" (sinh blueprint từ yêu cầu), chạy ADLC, đề xuất và duyệt kế hoạch.
- **Run Detail** — màn hình theo dõi lần chạy: timeline vòng lặp nhiệm vụ, các lần thử, bản vá nguồn, artifact, phê duyệt.
- **Contract** — panel soạn/xem/thực thi Hợp đồng.
- **Đa ngôn ngữ** — mặc định tiếng Việt (`src/locales/vi.json`), có English; người dùng đổi ở phần Cài đặt (General) hoặc ô chọn ngôn ngữ trên thanh đầu trang.

## Các lệnh thường dùng

Chạy các lệnh từ thư mục này:

```bash
npm install     # cài dependency (lần đầu)
npm run dev     # chạy dev server tại http://localhost:3000 (tự proxy API sang backend)
npx jest        # chạy unit test
npx tsc --noEmit        # kiểm tra kiểu TypeScript
npx biome check         # lint + format check
NODE_OPTIONS="--max-old-space-size=8192" npm run build   # build production
```

> Build cần thêm bộ nhớ heap (8GB) vì bundle lớn — nếu không sẽ bị killed giữa chừng.

## Cấu trúc chính (`src/`)

| Thư mục | Nội dung |
|---|---|
| `pages/RunDetailPage/` | Màn hình chi tiết lần chạy (nhiệm vụ, lần thử, phê duyệt, artifact) |
| `components/adlc/` | Contract panel, contract viewer |
| `components/core/flowToolbarComponent/` | Thanh công cụ trên canvas, gồm các nút ADLC |
| `features/adlc-blueprint/` | Tạo blueprint bằng AI, ví dụ mẫu Heart App |
| `features/adlc-workspace/`, `features/plan-proposal/` | Workspace ADLC, duyệt đề xuất kế hoạch |
| `CustomNodes/`, `CustomEdges/` | Node/edge ADLC trên canvas |
| `locales/` | Bản dịch UI (`en.json`, `vi.json`) |

Chi tiết phần backend và toàn bộ dự án: [adlc-flow/README.md](../README.md) và [Readme.md gốc](../../Readme.md).
