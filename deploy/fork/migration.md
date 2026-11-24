# Chuẩn bị fork PokeDev

## Phạm vi bản nền

Bản này tách nguồn đang làm việc của ADLC thành repository cục bộ mới tại thư mục PokeDev. Tên, logo, tiêu đề trang, manifest và chuỗi hiển thị frontend được chuyển về PokeDev; logic nghiệp vụ, cơ chế duyệt và namespace API được giữ để tiếp tục phát triển.

Đích GitHub mặc định của bản chuẩn bị là `aspiringcoder6/PokeDev`, theo tài khoản GitHub đã kết nối. Cấu hình remote không xác nhận repo đã được tạo trên máy chủ. Nguồn upstream và commit gốc được lưu trong `fork-baseline.json`; manifest ghi hash nguồn và hash bản đã chuyển tên cho từng file.

## Ranh giới cần chuyển khỏi Workloop

| Thành phần | Phụ thuộc hiện tại | Đích PokeDev |
|---|---|---|
| `live_workflows.py` | Khởi chạy `integration-sources/workloop/project_worker.py` | Worker/adapters của vAIPlatform, nhận kế hoạch đã duyệt |
| `project_worker.py` | Import `workloop.backend.processing`, `Store`, `DshHarnessGateway`, `WorkloopTask` từ runtime tải về | `AdlcRunService` và `TaskExecutorRouter` cùng adapter Harness |
| `workloop.py` | Factory catalog, source-lock và runtime dưới `adlc-flow/data/workloop` | Registry node package và kế hoạch phiên bản của vAIPlatform |
| `project_workloop.py` | HTTP tới Workloop và job binding | Trạng thái run/task của vAIPlatform |
| `document_intake.py` | Catalog tài liệu và metadata Slack từ Workloop | Hồ sơ tiếp nhận do PokeDev sở hữu, độc lập kênh |
| `document_revision.py` | Gọi Spec qua Workloop MCP | Dịch vụ Spec qua Harness/công cụ đã đăng ký trong PokeDev |
| `document_progress.py` | Công cụ Confluence qua Workloop | Connector tài liệu trực tiếp hoặc MCP độc lập |
| Giao diện tích hợp | Slack & Workloop, Workloop panel | Kết nối kênh và runtime của PokeDev |

Các wrapper Workloop được giữ trong source để đối chiếu và chuyển đổi. Engine Workloop, database, job đang chạy và runtime tải về không được chép sang. Chưa thể coi luồng Live project hiện tại là đã độc lập Workloop; đổi tên file hoặc nhãn giao diện không giải quyết được các import trên.

Lõi vAIPlatform hiện có `run_service.py`, `executor_router.py`, kho kế hoạch và sự kiện, phê duyệt, adapter Harness, node package và bằng chứng thực thi. Bước tiếp theo cần nối luồng project/intake vào các thành phần đó, giữ các kiểm tra source digest, quyền project và khôi phục không chạy trùng.

## Chuyển sang GitHub

Remote GitHub dùng để lưu source PokeDev và adapter GitHub phục vụ repository nghiệp vụ là hai hạng mục riêng. Hiện `gitea_projects.py`, issue automation và PR handover vẫn sử dụng Gitea; đặt `origin` lên GitHub chưa chuyển các API này thành GitHub API.

Cần tách cổng repository cho liệt kê/chọn repo, snapshot commit, nhánh ứng viên, issue, PR, checks và merge theo commit đã xem. Mỗi thao tác phải giữ scope tài khoản/project, mã thao tác và biên nhận. Chỉ chuyển dữ liệu nghiệp vụ cũ nếu có yêu cầu cụ thể; bản nền không tự nhập project hoặc kết quả chạy từ ADLC.

## Thứ tự triển khai

1. Kiểm tra bản nguồn, commit nền và nhận diện PokeDev.
2. Chuẩn bị Python/frontend riêng, database mới và một project thử nghiệm.
3. Nối một workflow đơn giản qua control plane vAIPlatform, loại đường engine Workloop cho workflow đó.
4. Bổ sung GitHub adapter, chạy trên repository thử nghiệm riêng và đối soát source/PR.
5. Chuyển tiếp nhận yêu cầu, Spec và hỏi đáp với người dùng sang dịch vụ PokeDev.
6. Bỏ route, giao diện và dependency Workloop sau khi luồng thay thế đã kiểm chứng.

## Tiêu chí hoàn thành chuyển đổi

- Project thử nghiệm chạy được khi không có server và runtime Workloop.
- Đọc source, tạo nhánh và PR qua GitHub đúng repository/commit được duyệt.
- Quyền project, phê duyệt, câu hỏi con người và các biên nhận không bị giảm khi đổi backend.
- Khởi động lại không gọi lại model, gửi lại quyết định hay tạo PR trùng.
- Giao diện desktop dùng PokeDev, không dẫn sang workspace/bot của project cũ trong luồng mới.

## Đối chiếu nguồn và trạng thái

`deploy/fork/source-manifest.json` ghi các file lấy từ source. Những file có hash khác nguồn là chuyển tên trên frontend. Logo/favicon, README, cấu hình mẫu, ignore rules và metadata được tạo riêng cho bản PokeDev. Manifest là căn cứ đối chiếu lúc tách; các chỉnh sửa tiếp theo cần được ghi bằng Git.

Không áp dụng script phục hồi, di chuyển dữ liệu hoặc cấu hình remote của ADLC lên PokeDev. Kết nối Harness/GitHub/kho tài liệu sẽ được cấu hình riêng khi chuyển từng luồng.
