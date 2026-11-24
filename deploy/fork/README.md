# Chuẩn bị bản tách nguồn PokeDev

`prepare.py` lấy source đang làm việc, gồm thay đổi chưa commit và file code chưa theo dõi, để tạo một repository cục bộ độc lập. Script không sửa branch/index của nguồn, không chép lịch sử Git, database, credential, runtime tải về hoặc dependency đã cài.

Xem trước từ thư mục ADLC:

```powershell
python deploy/fork/prepare.py --output D:/coding/HUST/PokeDev --github aspiringcoder6/PokeDev
```

Thêm `--write` để ghi vào thư mục mới hoặc trống. Script từ chối đích nằm trong nguồn, đích có nội dung và đường dẫn qua symlink/junction. Nó cấu hình `origin` và `upstream` cục bộ; không tạo repo GitHub, không push và không commit tự động.

Nhận diện frontend được đổi về PokeDev, logo cũ lấy từ commit HEAD của source. Cấu hình mẫu dành riêng cho fork, mặc định mock và port 7862. `migration.md` ghi rõ các đường còn phụ thuộc Workloop và Gitea để chuyển sang vAIPlatform/GitHub.

Kiểm tra công cụ bằng `python -m unittest discover -s deploy/fork/tests -v`. Sau khi xuất cần kiểm tra baseline, chạy kiểm tra phù hợp rồi mới tạo commit đầu tiên.
