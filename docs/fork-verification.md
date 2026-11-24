# Kiểm tra bản nền PokeDev

Ngày: 24/11/2026.

## Nguồn

Bản nền tại `D:/coding/HUST/PokeDev` lấy từ source đang làm việc của ADLC, nhánh `agentHarness`, commit nền `e3f96e1d1a018ad2be85e6997a8fa36addc87b93`. Các thay đổi source chưa commit được giữ trong bản tách. Repository mới dùng lịch sử riêng và ghi nguồn đối chiếu trong `fork-baseline.json`.

Frontend đã đổi tên hiển thị, tiêu đề trang, manifest, tên package và đường dẫn asset về PokeDev. Logo/favicon PokeDev cũ được khôi phục từ commit nền. Namespace backend và hợp đồng API được giữ.

## Kết quả

| Kiểm tra | Kết quả |
|---|---|
| Công cụ xuất source | 6 test đạt, gồm nguồn chưa commit, file bị xóa, không ghi đè đích và loại dữ liệu riêng |
| Registry, resolver và executor router của vAIPlatform | 24 test đạt |
| Accessibility màn hình đăng nhập và app header | 15 test đạt |
| Frontend production build | Đạt, dùng script build có giới hạn tài nguyên trên Windows |

Đã cập nhật kỳ vọng test danh mục cho ba package đang có trong source: `agent-memory-context`, `testforge-replay`, `workflow-plugin-check`. Test accessibility cũng dùng tên PokeDev. Các sửa này chỉ áp dụng tại bản fork.

Frontend đã có dependency cục bộ được cài từ lockfile bằng `npm ci`. Kiểm tra backend dùng bộ thư viện Python hiện có, với module và test lấy từ thư mục PokeDev. Môi trường Python chạy ứng dụng cần được tạo riêng khi cấu hình project mới.

Build còn cảnh báo kích thước chunk và cách import locale của source hiện tại; chưa tối ưu bundle trong phạm vi chuẩn bị fork.

## GitHub và chuyển đổi runtime

Nhánh chuẩn bị là `codex/pokedev-fork-prep`. `origin` trỏ tới `https://github.com/aspiringcoder6/PokeDev.git`, `upstream` trỏ về repository ADLC. Bước chuẩn bị chỉ cấu hình remote cục bộ, chưa tạo hoặc push repository trên GitHub.

Luồng Live project còn import engine Workloop; thao tác repository/issue/PR nghiệp vụ còn dùng Gitea. Các kiểm tra trên xác nhận bản nguồn và phần lõi được chọn, chưa xác nhận hai luồng đó đã chuyển sang vAIPlatform/GitHub. Phạm vi và tiêu chí chuyển đổi nằm trong [kế hoạch fork](fork-preparation.md).
