# PokeDev — chạy local và build các service

PokeDev gồm frontend React, backend Python và các dịch vụ hỗ trợ agent: Harness, Sandbox, Memory, TestForge. Dùng Docker để chạy cả bộ, hoặc chạy backend/frontend trực tiếp khi phát triển.

## Chuẩn bị

- Git và Python 3.14. Có thể cài thêm `uv` để tạo môi trường Python.
- Docker Desktop dùng Linux containers/WSL 2, đang ở trạng thái **Engine running**.
- Node.js 22 và npm nếu phát triển ngoài Docker.
- Nên dành 16 GB RAM và khoảng 20 GB dung lượng trống cho image, dependencies và dữ liệu. Lần build đầu cần Internet để tải các gói.

```powershell
git clone https://github.com/aspiringcoder6/PokeDev.git
cd PokeDev
```

Trên máy hiện tại, dùng `cd D:\coding\HUST\PokeDev`. Các lệnh bên dưới chạy ở thư mục gốc repository.

## Chạy toàn bộ bằng Docker

```powershell
python deploy/local/stack.py init
python deploy/local/stack.py up
python deploy/local/stack.py status
```

`init` tạo `.env` và sinh mật khẩu/token riêng; chạy lại giữ cấu hình đã có. `up` lần lượt build image, chuẩn bị image thực thi Sandbox, khởi động các service, đợi kiểm tra sức khỏe rồi nối backend với Harness. Frontend được build trong Docker và phục vụ cùng backend.

Mở **[PokeDev](http://127.0.0.1:7862)**. Chế độ local mặc định tự đăng nhập; tác vụ dùng model thật vẫn tắt cho đến khi cấu hình provider.

| Service | Địa chỉ trên máy | Vai trò |
|---|---|---|
| PokeDev | [127.0.0.1:7862](http://127.0.0.1:7862) | UI, API và điều phối ADLC |
| Harness | [127.0.0.1:3082](http://127.0.0.1:3082) | Phiên agent, model và runtime plugins |
| Sandbox broker | [127.0.0.1:8002/health](http://127.0.0.1:8002/health) | Workspace và thực thi cách ly |
| OpenSandbox | `127.0.0.1:8082` | Quản lý container thực thi |
| Memory API | [127.0.0.1:8012/health](http://127.0.0.1:8012/health) | Cognee, lưu/tìm lại ngữ cảnh |
| Memory MCP | `http://127.0.0.1:8013/mcp` | Kết nối Memory qua MCP |
| TestForge | [127.0.0.1:9092/api/v1/health](http://127.0.0.1:9092/api/v1/health) | Kiểm thử với Chromium/Playwright và k6 |
| VFS | `vfs:8001`, chỉ trong Docker | Lưu file workspace |
| PostgreSQL | `postgres:5432`, chỉ trong Docker | Database backend |
| Redis | `redis:6379`, chỉ trong Docker | Cache backend |

Project Docker có tên `pokedev-local`, dùng volume riêng. Các cổng host chỉ bind vào `127.0.0.1`. OpenSandbox được gắn Docker socket để quản lý container; socket này không gắn vào container thực thi của agent.

```powershell
# Build lại tất cả, chưa khởi động
python deploy/local/stack.py build

# Build/cập nhật riêng một service
python deploy/local/stack.py build testforge
python deploy/local/stack.py up testforge --no-build

# Xem trạng thái và log gần nhất
python deploy/local/stack.py status
python deploy/local/stack.py logs app
python deploy/local/stack.py logs harness

# Dừng, giữ dữ liệu
python deploy/local/stack.py down

# Khởi động lại từ image đã build
python deploy/local/stack.py up --no-build
```

Chỉ cần UI/backend, PostgreSQL và Redis:

```powershell
python deploy/local/stack.py up --core-only
python deploy/local/stack.py status --core-only
```

## Cấu hình model và phiên Harness

```powershell
python deploy/local/stack.py open-harness
```

Lệnh trên mở browser với liên kết đăng nhập của Harness PokeDev. Trong Settings, khai báo provider/API key, base URL nếu dùng dịch vụ tương thích OpenAI, và model. Chọn model mặc định để dùng chat trong Harness.

Để profile thực thi của PokeDev dùng model đó, đặt **đúng ID provider và ID model đã khai báo** trong `.env`:

```dotenv
POKEDEV_HARNESS_PROVIDER=your-provider-id
POKEDEV_HARNESS_MODEL=your-model-id
```

Đây là các ID cấu hình, không phải API key. Cấu hình được áp dụng lúc khởi động; không cần build lại image khi đổi model:

```powershell
python deploy/local/stack.py up harness --no-build
```

Khi chạy tác vụ cần thu thập thay đổi Git, đặt thêm `POKEDEV_PROJECT_REPO=D:/path/to/project-repo` trỏ tới checkout Git của project. Thư mục này được gắn chỉ đọc; Harness tạo workspace thực thi riêng. Mặc định thư mục project rỗng, nên khả năng thu thập artifacts chưa sẵn sàng. Chỉ bật chức năng thực thi cần dùng, ví dụ `ADLC_HARNESS_ENABLED=true`, sau khi đã cấu hình model và project:

```powershell
python deploy/local/stack.py up app --no-build
```

Sau khi Harness khởi động lại, nếu kết nối báo hết phiên:

```powershell
python deploy/local/stack.py connect-harness
```

Helper cập nhật phiên mới trong `.env` rồi nạp lại backend Docker nếu đang chạy. Không dùng token/phiên của ADLC. Không commit `.env` hoặc API key. Kiểm tra sức khỏe không gọi tác vụ LLM có tính phí; Memory có thể tải model embedding/extraction khi bắt đầu xử lý dữ liệu.

### Source và build Harness

- `deploy/local/harness.Dockerfile`: tự build image `pokedev-harness:local`.
- `deploy/local/harness.patch.yml`: đăng ký plugin và các profile thực thi.
- `deploy/local/harness-config.mjs`: đưa ID provider/model từ `.env` vào profile lúc khởi động.
- `services/harness/plugins/`: source plugin runtime ADLC, driver, Git artifacts, verifier, task loop, Sandbox và TestForge.

```powershell
python deploy/local/stack.py build harness
python deploy/local/stack.py up harness --no-build
python deploy/local/stack.py open-harness
```

Lõi Harness hiện được cài từ gói `@deepseek-ai/dsh@0.1.5-rc.2` khi build Docker; repository này chứa bộ build và source plugin của PokeDev, chưa vendor toàn bộ source lõi DSH. Xem [hướng dẫn Harness](services/harness/README.md) để đổi model, quản lý dữ liệu và chỉnh plugin.

## Chạy trực tiếp khi phát triển

```powershell
python deploy/local/stack.py setup
python deploy/local/stack.py run
```

`setup` tạo `adlc-flow/.venv`, cài backend theo `deploy/local/requirements.lock.txt`, cài package/SDK nội bộ, chạy `npm ci` và build frontend. Có `uv` thì helper dùng `uv`; nếu không, dùng Python 3.14 và pip. Cache đặt trong `adlc-flow/data/local/cache`.

`run` phục vụ UI và API ở **[127.0.0.1:7862](http://127.0.0.1:7862)**, dùng SQLite `data/pokedev.db`. Giữ cửa sổ này mở, nhấn `Ctrl+C` để dừng. Không chạy đồng thời Docker `app` trên cùng cổng.

Để chạy các service agent với backend trên máy, mở cửa sổ khác:

```powershell
python deploy/local/stack.py up harness sandbox vfs opensandbox memory memory-mcp testforge
python deploy/local/stack.py connect-harness
```

Trong `.env`, đặt `VAI_PLATFORM_URL=http://127.0.0.1:3082` và giữ `ADLC_HARNESS_BASE_URL=http://127.0.0.1:3082`. Khởi động lại `stack.py run` sau khi cập nhật cấu hình.

Build lại giao diện:

```powershell
python deploy/local/stack.py frontend
```

Hoặc chạy Vite để cập nhật trong lúc sửa, cùng backend đang chạy:

```powershell
cd adlc-flow/frontend
$env:BACKEND_URL='http://127.0.0.1:7862'
$env:VITE_PROXY_TARGET='http://127.0.0.1:7862'
npm run dev -- --host 127.0.0.1
```

Dùng các lệnh `setup` ở trên thay cho `uv sync` trong `adlc-flow`: metadata monorepo cũ không khớp cây source đã tách. Bộ cài local nằm ở `pyproject.toml` tại gốc và `deploy/local/`.

## Cấu hình và dữ liệu

### Tiếp nhận yêu cầu và Lark

Mở [Tiếp nhận yêu cầu](http://127.0.0.1:7862/intake) để tạo hồ sơ, sửa nội dung và xem lịch sử phiên bản. Đặt `POKEDEV_INTAKE_ENABLED=true` trong `.env` rồi khởi động lại backend. Phần này hoạt động độc lập với model; hồ sơ thuộc riêng người tạo và chưa tự chạy agent.

Tích hợp Lark đang ở bước kiểm chứng SDK và transport. Bộ thử nằm trong [services/lark-connector](services/lark-connector/README.md); chưa bật nhận DM vào hồ sơ hoặc hỏi–đáp tự động. Theo dõi [kết quả triển khai](docs/lark-intake-implementation.md) và [các slice tiếp theo](docs/plans/lark-intake-slices.md).

Source access GitHub/Lark và workflow requirement readiness đã được tích hợp từ `Phuc/specification`. Readiness mặc định tắt (`ADLC_REQUIREMENT_READINESS_ENABLED=false`), cần source bindings, tài khoản dịch vụ, presets/model Harness và HumanBridge trước khi dùng thật. Xem [biên bản tích hợp](docs/operations/branch-integration-20261125.md) và [hướng dẫn cấu hình](docs/operations/requirement-readiness.md).

| Đường dẫn | Nội dung |
|---|---|
| `.env.example` | Mẫu cấu hình có thể commit |
| `.env` | Mật khẩu/token và cấu hình local; Git bỏ qua |
| `deploy/local/requirements.in`, `requirements.lock.txt` | Dependencies và phiên bản backend đã khóa |
| `compose.yml`, `Dockerfile`, `deploy/local/*.Dockerfile` | Bộ build và định nghĩa service |
| `services/` | Source các service/plugins, kèm manifest nguồn và license có sẵn |
| `data/`, `adlc-flow/data/` | Dữ liệu/cache khi chạy trực tiếp; Git bỏ qua |
| Volume có tiền tố `pokedev-local_` | Database, workspace và artifacts của Docker |

`down` giữ dữ liệu. Sao lưu trước khi xóa volume hoặc đổi mật khẩu database đã có dữ liệu. Nếu đổi cổng trong `compose.yml`, cập nhật cả URL callback, proxy và cấu hình kiểm tra liên quan.

## Xử lý lỗi

- **Không kết nối Docker:** mở Docker Desktop, chờ **Engine running**, chạy `docker info` rồi thử lại.
- **Cổng 7862 đang dùng:** dừng backend chạy trực tiếp trước khi bật Docker `app`, hoặc ngược lại.
- **Build bị gián đoạn:** chạy lại `stack.py build <service>`; Docker dùng lại các lớp đã build. Helper build lần lượt để giảm sử dụng bộ nhớ.
- **Service chưa healthy:** xem `stack.py logs <service>`. Memory cần hoàn thành migration trước khi MCP khởi động. `status` trả lỗi khi các endpoint chưa sẵn sàng.
- **Harness yêu cầu đăng nhập lại:** chạy `connect-harness`, rồi `open-harness` nếu cần mở UI.
- **Mất mạng khi dùng VPN:** kiểm tra kết nối/routing trước. Bộ local không cần thay đổi cấu hình VPN.

## Phạm vi hiện tại

Bộ local cung cấp UI/API và hạ tầng agent độc lập. Bản fork vẫn đang chuyển đổi: một số luồng live project còn gọi engine Workloop; adapter repository/issue/PR nghiệp vụ còn theo Gitea; Memory tools cần nối đầy đủ với luồng agent. Service healthy chưa đồng nghĩa toàn bộ vòng đời project đã chạy bằng vAIPlatform/GitHub.

Theo dõi phần còn lại trong [kế hoạch chuyển đổi](docs/fork-preparation.md). Thông tin bản nền ở [fork-baseline.json](fork-baseline.json); source được lưu tại [aspiringcoder6/PokeDev](https://github.com/aspiringcoder6/PokeDev).
