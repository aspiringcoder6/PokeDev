# PokeDev

PokeDev là bản tách nguồn từ ADLC/vAIPlatform để phát triển cho project mới, dùng vAIPlatform làm nền tảng điều phối và GitHub làm hệ thống quản lý mã nguồn.

Bản nền lấy mã nguồn đang làm việc, gồm các thay đổi chưa commit, khôi phục tên và logo PokeDev cũ trên frontend. Database, phiên đăng nhập, token, runtime tải về, thư viện đã cài và báo cáo chạy của dự án cũ được tách khỏi bản này.

## Trạng thái bản nền

| Phần | Trạng thái |
|---|---|
| Backend Python, frontend React và hợp đồng ADLC | Đã tách nguồn |
| Nhận diện PokeDev | Đã áp dụng tên và logo cũ trên frontend |
| Git cục bộ | Nhánh `codex/pokedev-fork-prep`, lịch sử mới |
| GitHub dự kiến | `aspiringcoder6/PokeDev`; `origin` được cấu hình cho repo này |
| Cấu hình local | `.env.example`, port riêng 7862, mặc định mock |
| Điều phối project hoàn toàn bằng vAIPlatform | Cần chuyển các luồng còn phụ thuộc Workloop |
| GitHub repository/issue/PR cho project nghiệp vụ | Cần adapter thay đường Gitea hiện tại |

`origin` chỉ là cấu hình đích GitHub. Việc tạo repo trên GitHub và push là bước xuất bản riêng. Bản nguồn và trạng thái chuyển đổi ghi trong [fork-baseline.json](fork-baseline.json) và [kế hoạch tách Workloop](docs/fork-preparation.md).

Kết quả kiểm tra bản nền được ghi trong [biên bản kiểm tra](docs/fork-verification.md).

## Chuẩn bị môi trường phát triển

Tạo môi trường Python và cài dependencies riêng trong `adlc-flow/.venv`, dùng `adlc-flow/requirements.txt`, sau đó cài SDK bằng `pip install -e ./sdk`. Frontend dùng Node theo `adlc-flow/frontend/package.json` và cài bằng `npm ci` tại thư mục frontend. Không chép `.venv`, `node_modules` hoặc file cấu hình đăng nhập từ ADLC.

Sao chép `.env.example` thành `.env`, rồi mở workspace bằng [PokeDev.code-workspace](PokeDev.code-workspace). Cấu hình mẫu dành cho phát triển cục bộ với auto-login; cần cấu hình xác thực trước khi mở cho người dùng khác.

Các hướng dẫn nền của ứng dụng được giữ tại [tài liệu nguồn](docs/upstream-readme.md). Không dùng các lệnh triển khai VPN/local-recovery của dự án cũ để khởi động bản fork; các script đó không được mang sang.

## Công việc tiếp theo

1. Xác định project mới, repository nghiệp vụ và nhóm người dùng.
2. Dùng `AdlcRunService`, kế hoạch đã duyệt, cổng `TaskExecutor` và adapter Harness của vAIPlatform làm đường chạy chính.
3. Thay đường `project_worker.py`/engine Workloop và lớp intake phụ thuộc Workloop trước khi chạy project thật.
4. Bổ sung adapter GitHub cho repository, issue, nhánh, PR và đối soát commit theo quyền.
5. Tích hợp chat/tiếp nhận yêu cầu trực tiếp vào vAIPlatform khi phạm vi Slack/Lark được chốt.

Mã namespace `adlc`, `langflow` và các biến `VAI_*` được giữ để tiếp tục tương thích dữ liệu/hợp đồng; tên sản phẩm hiển thị là PokeDev.
