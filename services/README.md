# Service source snapshots

Thư mục này chứa các phần source cần để build PokeDev local từ một checkout mới. Docker không đọc source hoặc runtime từ thư mục ADLC bên cạnh.

- `harness/plugins`: plugin ADLC runtime, model driver, verifier, Git artifacts, task loop, Sandbox và TestForge.
- `sandbox`: broker, dashboard, VFS và wrapper xác thực broker.
- `memory`: Cognee API/MCP và các module dữ liệu cần thiết; giữ LICENSE/NOTICE từ nguồn.
- `testforge`: broker, công cụ kiểm thử và schema.

Các file được lấy từ source service đã dùng trong ADLC. Không mang theo `.git`, `.env`, database, phiên đăng nhập, token, `node_modules`, `.venv` hoặc cache của dự án cũ.

`source-manifest.json` ghi đường dẫn nguồn và SHA-256: `source_sha256` là nội dung khi lấy từ nguồn, `sha256` là nội dung trong snapshot PokeDev. Các chỉnh sửa local được mô tả ở `local_changes`. Các file hướng dẫn riêng của PokeDev không nằm trong danh sách snapshot.

Docker recipes nằm ở `deploy/local/`. Xem [README chính](../Readme.md) và [hướng dẫn Harness](harness/README.md) để build, cấu hình provider/model và chạy các service.
