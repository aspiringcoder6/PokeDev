# Harness trong PokeDev

Bộ build chạy độc lập với ADLC/Workloop: image `pokedev-harness:local`, giao diện tại `http://127.0.0.1:3082`, workspace và cấu hình trong các volume `pokedev-local_harness-*`.

## Có những source nào?

| Đường dẫn | Nội dung |
|---|---|
| `deploy/local/harness.Dockerfile` | Cài lõi DSH đã pin phiên bản và đóng gói plugin |
| `deploy/local/harness-entrypoint.sh` | Khởi động Harness trong bubblewrap |
| `deploy/local/harness.patch.yml` | Danh sách plugin, profile và chính sách artifacts |
| `deploy/local/harness-config.mjs` | Áp dụng provider/model lúc khởi động |
| `deploy/local/harness-lock.mjs` | Tính digest plugin khi build; runtime kiểm tra lại trước khi thực thi |
| `services/harness/plugins/` | Source plugin nghiệp vụ của PokeDev |

Lõi DSH được tải từ npm: `@deepseek-ai/dsh@0.1.5-rc.2`. Bộ build không dùng image Harness của ADLC. Source lõi DSH chưa được vendor vào repository; muốn sửa chính lõi runtime cần quản lý source upstream và quy trình build riêng. Để chỉnh plugin hiện có, sửa source trong `services/harness/plugins/` rồi build lại Harness.

## Build và mở giao diện

Chạy từ gốc repository:

```powershell
python deploy/local/stack.py init
python deploy/local/stack.py build harness
python deploy/local/stack.py up harness --no-build
python deploy/local/stack.py open-harness
```

Sandbox/TestForge là các service riêng. Khi sử dụng tools của chúng, chạy cả bộ bằng `python deploy/local/stack.py up` hoặc khởi động các service tương ứng.

## Gắn model

1. Mở giao diện bằng `open-harness`.
2. Trong Settings, thêm provider, API key và model. Nếu provider tương thích OpenAI, nhập base URL do dịch vụ đó cung cấp. Nếu model nằm trên máy host, container truy cập qua `host.docker.internal`, không dùng `127.0.0.1` của container.
3. Chọn model mặc định cho chat trong Harness.
4. Đặt ID provider/model cho các profile PokeDev trong `.env`:

```dotenv
POKEDEV_HARNESS_PROVIDER=your-provider-id
POKEDEV_HARNESS_MODEL=your-model-id
```

5. Nạp lại cấu hình:

```powershell
python deploy/local/stack.py up harness --no-build
```

Hai biến phải cùng được cấu hình. Helper tạo patch runtime trong volume riêng, không ghi API key vào image. Profile pin cả provider và model để tác vụ không tự chuyển sang model khác khi đổi lựa chọn mặc định trong UI.

Đổi provider/model chỉ cần khởi động lại Harness. Sửa plugin hoặc template patch cần `build harness` trước. Sau mỗi lần Harness khởi động lại, helper lấy phiên mới cho backend; có thể chạy lại `connect-harness` nếu backend báo hết phiên. Khi backend chạy trực tiếp, khởi động lại tiến trình đó sau khi cập nhật `.env`.

## Project và trạng thái sẵn sàng

Với tác vụ cần Git artifacts, cấu hình checkout của project:

```dotenv
POKEDEV_PROJECT_REPO=D:/path/to/project-repo
```

Đường dẫn phải là checkout Git hợp lệ. Compose gắn nó vào `/app/project-source` ở chế độ chỉ đọc. Collector tạo worktree trong workspace riêng, kiểm soát đường dẫn file và trả lại patch/artifacts. Mặc định thư mục source rỗng; không tạo project giả hoặc tự chạy LLM.

Native API `/api/v1/adlc-harness/health` có xác thực bằng `ADLC_HARNESS_API_TOKEN`. HTTP 200 cho biết service đang phục vụ. Trường `ready` chỉ thành `true` khi cấu hình driver, project/artifact collector, callback và plugin lock đều hợp lệ. Provider chưa cấu hình, model chưa khai báo hoặc project chưa có Git là các trạng thái cần hoàn tất trước khi chạy công việc thật.

```powershell
python deploy/local/stack.py status
python deploy/local/stack.py logs harness
```

API key/provider settings lưu trong volume workspace Harness; token và cấu hình kết nối backend ở `.env`. `down` giữ các dữ liệu này. Không sao chép volume hoặc phiên đăng nhập từ ADLC sang PokeDev.
