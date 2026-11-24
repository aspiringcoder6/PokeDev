# Không gian phát triển ứng dụng — Delivery Workspace

Cập nhật: 19/10/2026, gồm H8B. UI và migration đã bật trên máy local; xem phần nghiệm thu để phân biệt kiểm thử phần mềm với nghiệm thu một ứng dụng thật.

## Luồng người dùng

Điểm vào chính là `/work`. Không còn Studio và Agent Harness là hai module điều hướng riêng.

1. **Yêu cầu**: nhập tên, người dùng, chức năng và điều kiện chấp nhận. Chọn dự án đã liên kết mã nguồn hoặc mở bộ chọn thư mục. Các gợi ý chỉ điền nội dung, không tự gọi model.
2. **Workflow**: AI tạo các giai đoạn bằng API tạo Blueprint hiện có. Xem mục tiêu/đầu ra của từng giai đoạn, rồi duyệt chính phiên bản này. Có thể chỉnh ở trình soạn workflow nâng cao.
3. **Kế hoạch**: compiler hiện có tạo task, đầu ra và quan hệ phụ thuộc từ Blueprint đã duyệt. Chọn **Sơ đồ / Danh sách** để xem cùng một kế hoạch đã lưu; chọn một công việc để mở chi tiết chỉ đọc. Kế hoạch luôn cần một lần duyệt riêng, kể cả package không khai báo gate. Sau đó người dùng xác nhận bắt đầu thực thi.
4. **Theo dõi**: Gantt và Kanban đọc ExecutionPlan/WorkflowRun thật. Các yêu cầu FORM và việc gửi kết quả của agent được nối từ phiên runtime. Cổng duyệt thay đổi mã nguồn dẫn tới bộ duyệt hiện có, giữ nguyên điều kiện phải đọc patch/evidence trước khi chấp nhận.
5. **Kết quả**: đọc bản kết quả agent đã lưu trong ADLC và các báo cáo Verify độc lập. Phần nâng cao có JSON, trace, source diff, scope/candidate/suite và công cụ đối soát.

**Gantt không tự đặt ngày kết thúc.** Khi thiếu timestamp thực tế, trục là lớp phụ thuộc, ghi rõ DỰ KIẾN; hai task độc lập có thể nằm cùng mốc. Chỉ dùng trục thời gian thực tế khi đủ dữ liệu. Task FAILED/CANCELLED/SKIPPED không được tính là hoàn tất thành công.

**SUCCEEDED không tự bằng Verify PASS.** Chỉ tổng hợp báo cáo Verify có report, receipt và evidence digest. Kết luận áp dụng cho candidate/phạm vi của từng báo cáo, không chứng nhận toàn ứng dụng. Báo cáo do agent viết được trình bày riêng, không đổi tên thành Verify độc lập.

## Chu kỳ phát triển — H8B

Ngay dưới tên công việc có bộ chọn **Chu kỳ đang xem**, mục tiêu, phiên bản workflow/đặc tả/kế hoạch và mục **Lịch sử chu kỳ & kế hoạch**. Yêu cầu dài được thu gọn; có thể mở toàn bộ để đọc nguyên văn. Chọn chu kỳ chỉ đổi dữ liệu đang xem, không phê duyệt hay chạy agent.

1. Mở công việc hiện có. Link `/work/{id}` và API GET không truyền `cycle_id` vẫn đọc **chu kỳ 1**, không tự chuyển sang bản nháp mới nhất.
2. Bấm **Chuẩn bị chu kỳ tiếp theo**, nhập mục tiêu rồi **Lưu bản nháp**. Thao tác chỉ ghi dữ liệu; không gọi model, áp patch, tạo run hoặc dùng lại phê duyệt.
3. Chu kỳ mới hiện **Bản nháp · chưa cấp quyền thực thi**. **Chỉnh mục tiêu** tạo một revision đặc tả mới, không ghi đè revision cũ. Workflow được tham chiếu bằng snapshot/digest; chưa tự dùng candidate đang chờ duyệt làm baseline.
4. Chọn lại chu kỳ 1 để xem plan, Gantt/Kanban, kết quả và gate cũ. Mở lịch sử để đọc các phiên bản plan đã lưu bằng viewer hiện có.
5. **Trao đổi & phát sinh** được lưu theo chu kỳ nguồn, có người ghi và chống gửi trùng; chưa tự chọn làm yêu cầu của chu kỳ kế tiếp.

H8B chỉ cho **một bản nháp kế tiếp đang chờ**. Khi bản nháp đã tồn tại, chu kỳ trước hiện **Mở bản nháp tiếp theo**, không tạo thêm bản sao. Chu kỳ mới chưa có nút biên dịch/bắt đầu; backend cũng từ chối mượn plan/approval/run của chu kỳ 1. H8C sẽ nối lập task graph chi tiết cho chu kỳ mới, H8D xử lý chọn feedback và replanning, H8E khép vòng kết quả/phát hành. **Product Loop hoàn chỉnh chưa được chứng nhận ở H8B.**

Chi tiết: [H8B — kiến trúc, hợp đồng và nghiệm thu](harness-milestone-h8b.md).

## Tài khoản và bốn role

Trang đăng nhập dùng tài khoản thật cho Admin, Business Analyst, Developer và Tester. Quyền được server xác định theo project; không có cách chọn Admin để tự nâng quyền. Bộ chọn ngữ cảnh chỉ được hiện role đã cấp. Không có role trong project hiện tại thì hiện **Cá nhân**.

Không thay đổi mật khẩu, seed tài khoản, cấp role hay mở quyền GitHub trong thay đổi UI này. Thành viên & quyền và Không gian nhóm tiếp tục sử dụng H7A/H7B.

**Adapter thực thi của Delivery Workspace hiện là owner-scoped/private.** Project managed của H7A/H7B bị chặn ở backend, kể cả người đó sở hữu folder hoặc là superuser cũ. Không dùng quyền chủ project để chạy thay BA/Tester. Thực thi dùng chung với danh tính/delegation của agent cần H7C; hiện chưa coi đây là team runtime hoàn chỉnh.

## Dữ liệu và chốt thực thi

`adlc_delivery` là liên kết UX bền vững tới Flow, ExecutionPlan archive và WorkflowRun, không phải một scheduler/task engine mới. Lưu yêu cầu gốc, hai receipt duyệt, revision, run và ghi chú phát sinh.

- Body thao tác đóng, không nhận actor/role/approved status từ browser.
- Các route yêu cầu human JWT rõ ràng, không tự đăng nhập bằng tài khoản mặc định hoặc API key.
- Read/write/execute dùng authorization hiện có; bản ghi khác chủ trả 404.
- Duyệt gắn semantic SHA-256 digest và SQL compare-and-swap revision. Đổi mục tiêu, input, package, policy hay edge làm mất hiệu lực duyệt. Di chuyển canvas hoặc đổi bộ đếm publish không làm mất duyệt.
- Plan được lưu trong archive thật và khôi phục sau restart. Phải lưu archive thành công trước khi cấp receipt duyệt.
- Legacy start cũng kiểm tra receipt từ database; xóa marker trên graph không bỏ được gate. Chỉ key dispatch được workspace khóa mới được materialize; không tạo run thứ hai bằng key tùy ý.
- Đánh dấu `dispatch_plan_id` trước khi gọi coordinator. Nếu mất acknowledgement, không tự gửi lại agent. **Đối soát lượt chạy** chỉ gắn một run canonical duy nhất cùng owner/flow/plan; không thực thi. Nếu chưa thấy hoặc thấy nhiều run, tiếp tục khóa và yêu cầu kiểm tra nhật ký.
- Trước khi giữ chỗ dispatch Task Loop Harness, kiểm tra flag, credential và health/release digest bằng GET, không tạo session. Dịch vụ chưa sẵn sàng trả `DELIVERY_HARNESS_LOOP_NOT_READY`; không tăng revision, khóa plan hay tạo run. Đây là kiểm tra sẵn sàng tại thời điểm đó, không bảo đảm dịch vụ không thể lỗi sau khi đã dispatch.
- Audit ghi actor thực, không phải role đang hiển thị trên dropdown.
- Package runtime mô phỏng bị từ chối khi khởi chạy trong luồng sản phẩm này.
- Ghi chú có command UUID chống trùng. Yêu cầu phát sinh được lưu để xem xét ở lượt sau, **chưa tự áp vào phạm vi đang chạy**.

## API

Prefix `/api/v1/adlc/deliveries`:

| Method/path | Ý nghĩa |
| --- | --- |
| GET / | Danh sách có phân trang, lọc quyền trước khi tính total |
| POST / | Gắn một Flow riêng với yêu cầu gốc |
| GET /{id} | Snapshot thật, quyền hiện tại, digest, plan/run |
| GET /{id}?cycle_id={uuid} | Snapshot của đúng chu kỳ; không tìm thấy/khác công việc thì từ chối |
| POST /{id}/cycles | Tạo bản nháp kế tiếp, không kế thừa quyền thực thi |
| POST /{id}/cycles/{cycle_id}/spec | Lưu revision mục tiêu của bản nháp |
| POST /{id}/approve-workflow | Duyệt chính workflow đang xem |
| POST /{id}/compile | Compiler hiện có, bắt buộc review plan |
| POST /{id}/approve-plan | Duyệt plan đã lưu, không recompile ngầm |
| POST /{id}/start | Gọi coordinator/materializer hiện có |
| POST /{id}/reconcile | Đối soát run sau acknowledgement không rõ |
| POST /{id}/notes | Ghi yêu cầu phát sinh/câu hỏi/ghi chú |

Các API tạo Flow, tạo Blueprint, Harness interaction, test/Verify và runtime không bị thay bằng mô phỏng frontend. Dữ liệu cũ không tự chuyển thành Delivery Workspace; vẫn mở được ở **Workflow nâng cao** và lịch sử cũ.

Link `/studio` chuyển về `/work`. Link `/harness` và `/harness-demo` cũ giữ query/fragment, chuyển tới viewer kỹ thuật `/runtime-sessions`. Không xóa lịch sử/Flow cũ.

## Bật trên máy local

Migration mới: `dw01a2b3c4d5`, sau bản vá naming H7B `h7b3c4d5e6f7`. Migration EXPAND chỉ thêm bảng, unique/FK/check/index; không cấp quyền, sửa role hay dữ liệu business. Từ chối adopt bảng lạ hoặc bảng đã có dữ liệu chưa được quản lý bởi revision này. Downgrade yêu cầu kế hoạch bảo toàn evidence riêng; không tự xóa bảng.

Trước khi cập nhật:

1. Dừng run đang thực thi và các backend dùng cùng database.
2. Sao lưu SQLite bằng online backup API hoặc snapshot nhất quán, không chỉ copy file `.db` khi WAL đang hoạt động. Giữ backup ở local, không commit/upload.
3. Khởi động bằng môi trường dự án và cấu hình hiện tại. Startup sẽ upgrade Alembic và kiểm tra schema. Không `stamp head`, không xóa database hoặc tắt schema check.
4. Mở `/work`, đăng nhập tài khoản thật. Kiểm tra danh sách và quyền trước khi tạo yêu cầu có trả phí.
5. Chọn repository/project được phép sửa, chỉ chạy model đã được chốt (hiện tại `my-codex / cx/gpt-5.6-luna` khi nghiệm thu). Đọc và duyệt từng gate; không coi việc bật UI là cấp quyền push/merge.

Không cần reload Harness chỉ để thêm bảng Delivery Workspace. Nếu API trả 404 trong khi UI mới đã hot reload, backend còn bản cũ; cần cập nhật backend và migration, không đổi token để che lỗi.

### Nâng cấp H8B

Revision mới `h8b1c2d3e4f5` nối sau `dw01a2b3c4d5`, chỉ thêm sáu bảng cycle/spec/head/plan-revision/feedback/operation và backfill từ Delivery cũ. Không đổi role hoặc trạng thái run/approval. Bản spec import ghi rõ nguồn `LEGACY_IMPORT`; tiêu chí/baseline của Task Loop cũ vẫn nằm trong plan cũ, không được suy ra thành một CycleSpec mới đã duyệt.

Sau khi dừng run thực thi và được phép cập nhật backend, từ `adlc-flow`:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\backup_product_cycles.py
.\scripts\start_delivery_services.ps1
```

Script đầu dùng SQLite backup API cho database chính và các kho runtime local, kiểm tra integrity, lưu manifest checksum và thử migration trên **bản sao**. Script khởi động không dừng listener hiện có: nếu backend cũ vẫn chạy, cần dừng đúng tiến trình backend đã xác định trước khi khởi động lại; không dừng mọi Python/Docker. Backend tự chạy Alembic, không `stamp head`. Không restore bản rehearsal đè lên database thật.

Ngay sau activation, trước khi tạo dữ liệu mới, có thể đối chiếu:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\backup_product_cycles.py --verify data\backups\<thu-muc-backup>
```

`--verify` so sánh fingerprint nghiêm ngặt. Sau khi người dùng lưu bản nháp/note, revision và timestamp Delivery thay đổi hợp lệ; không kỳ vọng fingerprint toàn bộ Delivery còn giống backup. Khi đó đối chiếu riêng authority, plan archive và record run canonical. Giữ backup/log riêng trên máy, không commit/upload.

Có thể đọc công việc/lịch sử khi Harness offline. Startup không tạo token thay thế; tạo workflow hoặc thực thi vẫn cần cấu hình và preflight runtime thật. H8B không tự bật Docker, Harness, memory, sandbox hay TestForge.

Nghiệm thu local ngày 19/10/2026: đã sao lưu **9 database**, thử migration rồi activate; Alembic ở `h8b1c2d3e4f5`, health/database đạt, không lỗi foreign key. Chu kỳ 2 `d743a50a-89ff-45bd-8550-affb596e5558` đã lưu tại [công việc thật](http://localhost:3000/work/57c730a8-b21c-4dfd-9fe3-d8a440afb4de?cycle_id=d743a50a-89ff-45bd-8550-affb596e5558), không có plan/run/phê duyệt. Chu kỳ 1 vẫn gắn plan `a4e3dde9-76bb-5457-95ae-2ccf0d549623`, run `4d275bfc-6baf-416d-bddd-9c7d5d5639af` và gate bàn giao đang chờ. Đối chiếu backup xác nhận authority Delivery, toàn bộ plan archive và payload các run canonical không đổi; revision Delivery tăng 5 → 6 đúng một lần khi lưu bản nháp.

Kiểm thử H8B: **155 backend đạt**, **206 frontend / 20 suite đạt**, kiểm tra semantic/syntax TypeScript riêng **9 file không có diagnostic**, Ruff các file Python trong phạm vi đạt. Backend còn hai cảnh báo cấu hình pytest có sẵn (`timeout`, `timeout_method`); không gọi toàn repository build/test là đạt. Không gọi model, duyệt gate, commit/merge/push hoặc reload Harness trong lượt nghiệm thu này. Ảnh live: `26-h8b-live-cycle-draft.jpg`, `27-h8b-live-cycle-mobile.jpg`, `28-h8b-live-cycle-history.jpg` trong `docs/report/delivery-workspace/`; ảnh preview có nhãn mẫu không được dùng thay bằng chứng live.

### Cấu hình tạo workflow qua Harness

Planner dùng `dsh-web-sdk==0.3.0`, lấy từ thư mục `sdk/` của repository Harness tại commit `8c892b2491bc6f8be0f2b439fe782707b7ad169a`. Bản local được cài trong virtualenv; không merge đè checkout Harness đang có thay đổi. SDK là dependency tùy chọn: nếu thiếu, API báo lỗi cấu hình thay vì tạo kết quả giả.

- `ADLC_BLUEPRINT_DSH_BASE_URL`: web gateway, mặc định `http://127.0.0.1:3080`.
- `ADLC_BLUEPRINT_DSH_TOKEN`: **credential đăng nhập web gateway**, không phải model key, callback secret hoặc `ADLC_HARNESS_API_TOKEN` của plugin.
- `ADLC_BLUEPRINT_PROVIDER=my-codex`, `ADLC_BLUEPRINT_MODEL=cx/gpt-5.6-luna`: chọn và đọc lại model trên session trước khi gửi prompt; lệch model thì dừng, không fallback.
- `ADLC_BLUEPRINT_CWD`: thư mục planning riêng trong container. Launcher local dùng `/app/workspace/adlc-blueprint-planning`, không đưa planner vào source repository. Thư mục nằm trên workspace mount: `/tmp` bên ngoài tiến trình không phải `/tmp` riêng của sandbox bwrap.
- `ADLC_BLUEPRINT_DSH_GENERATION_TIMEOUT_SECONDS`: thời gian chờ, mặc định 600 giây.

Transport dùng `prompt()` rồi `wait(timeout_s, poll_s, idle_s)` theo SDK 0.3.0. Tắt retry tự động của SDK (`max_attempts=1`) để mất acknowledgement không tự gọi lại model. Đây chưa phải một hàng đợi generation bền vững: nếu trình duyệt mất kết nối, kiểm tra session trước khi bấm tạo lại.

Launcher `adlc-flow/scripts/start_delivery_workspace.py` dành riêng máy phát triển này: đọc web credential hiện tại từ Docker log và iteration bearer độc lập từ container config **trong tiến trình, không in ra**, ghim Luna và khởi động backend loopback bằng môi trường hiện có. Chạy từ `adlc-flow` bằng `.venv\Scripts\python.exe -X utf8 scripts\start_delivery_workspace.py`. Nó không sửa `.env`, không mở firewall, không bật auto-login và không restart Harness. Nếu gateway đổi credential, chạy lại launcher. Script `scripts/check_delivery_harness.py` chỉ đọc model/preset, không gửi prompt có phí.

Để frontend/backend không phụ thuộc vào terminal của chat trên Windows, từ `adlc-flow` chạy:

```powershell
.\scripts\start_delivery_services.ps1
```

Script dùng tiến trình nền ẩn, backend trên `127.0.0.1:7860`, frontend trên `127.0.0.1:3000`; không cài Windows service hoặc tự chạy khi bật máy. Nếu port đã có listener hoặc đúng launcher đang startup, script giữ nguyên, không stop/restart. Log riêng ở `data/delivery-services` đã được Git ignore; không chia sẻ log thô vì lỗi của thư viện khác có thể chứa thông tin nội bộ. Script không gửi prompt, reload Harness, tạo run hay tự duyệt. Có Node trên PATH và virtualenv dự án là điều kiện trước khi chạy.

Đã kiểm tra startup nền và gọi lại script: PID listener không đổi; cả frontend, `/health_check` và bản xem thử candidate trả HTTP 200. Lần tiếp tục sau gián đoạn đã khôi phục run từ dữ liệu lưu, không gọi lại model. Hết phiên đăng nhập thì người dùng đăng nhập lại; không bật auto-login để né bước này.

Planner hiện dùng preset `minimal` với yêu cầu chỉ lập kế hoạch. Preset này vẫn có shell; thư mục planning riêng và lời nhắc **không phải** một sandbox chống hành vi độc hại. Runtime Task Loop proposal-only là adapter khác, có chặn tool ở plugin và Verify do kernel thực hiện.

### Bật lại adapter Task Loop trên máy này

Chỉ thực hiện sau khi người vận hành đã dừng các run và đồng ý reload. Từ `adlc-flow`:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\enable_delivery_iterations.py --reload-confirmed
```

Script chỉ recreate service `deepseek-harness` hiện có, không build lại image hoặc restart các broker. Trước khi đổi container, script yêu cầu đúng Compose project và hai source bind mount read-only; giữ nguyên nguồn/mount và các flag tích hợp đã có. Iteration bearer được tái sử dụng nếu đủ dài hoặc tạo mới trong bộ nhớ, không ghi vào `.env`, tài liệu hay output. Sau đó tạo thư mục planning riêng và kiểm tra health có giới hạn thời gian. Script không tạo session hoặc gửi prompt.

Khởi động lại backend bằng launcher ở trên để nạp iteration bearer hiện tại. Không dùng model API key hoặc web token thay cho bearer này. Không chạy `docker compose up` tùy ý rồi giả định credential trong tiến trình backend vẫn khớp; nếu container bị recreate bằng cấu hình khác, kiểm tra lại flag, token và health trước khi Start.

Lần kích hoạt được người dùng cho phép ngày 18/10: `ready=true`, protocol `task-loop-runtime:iteration/0.2.0`, runtime `runtime:deepseek-harness-iteration/0.1.0`, model `my-codex / cx/gpt-5.6-luna`; plugin digest `sha256:7670d86d64fdcd6d06acbb268f64000ee2b2967a642f1c14273c7ea6f06d552f`. Chế độ `FILE_PROPOSAL`, session mới cho mỗi iteration; chi phí tiền không được provider báo (`cost_reporting=UNAVAILABLE`), không trình bày như đã có giới hạn tiền chính xác.

### Sửa lỗi đăng nhập và mở dự án

- Login từng trả HTTP 200 nhưng trang không vào workspace: callback bootstrap bị mất khi xóa QueryClient làm unmount trang đăng nhập. Bootstrap nay nằm trong lifecycle của hook; vẫn giữ callback của caller, chống bấm gửi hai lần và đọc được credential native autofill. Không bỏ rate limit, thay mật khẩu hoặc cấp quyền mới.
- Sau khi login, API Delivery/Team từng trả 503 `TEAM_ENFORCEMENT_PROVIDER_REQUIRED`: registry startup đang ghi đè factory bằng provider cũ. Startup nay đăng ký đúng `TeamAuthorizationService`, giữ nguyên enforcement và khả năng override được cấu hình rõ ràng. Đã kiểm tra API thật trả 200; không đổi membership/role.
- Sự kiện submit từ hộp chọn thư mục qua React portal không còn gửi nhầm form yêu cầu. Form cha cũng từ chối event không phải của chính nó và nội dung trống. Hai bộ chọn dự án được phép cùng refresh GET `/projects/`, không bị bộ chống request trùng 300ms làm mất danh sách vừa đăng ký. Không thêm retry cho thao tác ghi.

### Trạng thái kích hoạt ngày 18/10/2026

- Đã sao lưu nhất quán 9 SQLite database tại `adlc-flow/data/backups/delivery-20261018T050546Z`; manifest lưu checksum và số bản ghi. Không đưa backup vào Git.
- Alembic live đã lên `dw01a2b3c4d5`; startup schema check đạt; `foreign_key_check` không có vi phạm.
- Backend `/health_check` trả DB/chat `ok`. UI chính ở `http://localhost:3000/work`, đăng nhập tài khoản thật.
- Đối chiếu ngay sau migration: 15 workflow có chủ sở hữu không đổi nội dung/ID; 25 starter template không có chủ sở hữu được cơ chế startup hiện có làm mới ID. Folder và cấu hình role/policy không bị migration thay đổi. Backup giữ cả ID cũ của template.
- Repo nghiệm thu local riêng: `adlc-flow/data/delivery-acceptance/taskboard/source`, baseline `c5829b61e4d77f353105338ae1ae16e98e5de339`. Agent chỉ được sửa `app.py`; `README.md` và 9 test trong `test_acceptance.py` cố định từ trước. Baseline cố ý chưa triển khai: chạy 9 test hiện trả lỗi `NotImplementedError`, không phải bằng chứng ứng dụng đã đạt.
- Chưa tạo remote GitHub hay push cho repo này. Chưa gọi model triển khai hoặc duyệt thay người dùng.
- Adapter iteration đã được bật/reload theo xác nhận của người dùng; health và preflight thực tế đạt với release/model ở mục trên. Các broker sandbox, TestForge và memory không bị restart. Lượt nghiệm thu này chưa chứng minh đã gọi memory backend hoặc Verify qua TestForge; bộ unittest đang dùng verifier do kernel quản lý, không đổi tên thành bằng chứng từ dịch vụ khác.

### Phiên nghiệm thu thật: tạo workflow → tạo kế hoạch

Mở [Công việc cá nhân · ứng dụng web](http://localhost:3000/work/57c730a8-b21c-4dfd-9fe3-d8a440afb4de) bằng tài khoản đã tạo phiên này. Project riêng là **source (2)** (`083d5688-1736-47d1-a72c-dfbd0d1aa407`), liên kết đúng repo taskboard ở trên. Không phải project **source** cũ.

- Delivery: `57c730a8-b21c-4dfd-9fe3-d8a440afb4de`; Flow: `db88d266-6adb-47ab-a16c-c0c3c5d3f33e`.
- Đã gửi **một** lượt tạo workflow thật bằng Luna. Sau khi agent làm lệch một từ trong specification, người vận hành phục hồi nguyên JSON cố định qua trình sửa workflow rồi lưu trước khi gửi duyệt; không gọi lại model hoặc coi nội dung bị lệch là đúng.
- Người dùng đã duyệt workflow lúc `2026-10-18T08:32:48Z` (15:32:48 giờ Việt Nam). Receipt gắn digest `sha256:f25815a319e608d17dec3607ac8188ec930d854a1654950a59b37ece42d8be90`.
- Compiler đã tạo và lưu plan `a4e3dde9-76bb-5457-95ae-2ccf0d549623`: `VALIDATED`, `validation_status=VALID`, không có validation error hoặc warning, `approval_required=true`.
- Plan digest: `sha256:7188b88d8b1de6b9bead76255635be51e20e602d35fa2da0e2b4367697199d27`. LiveLoopSpec trong plan bằng đúng JSON cố định; spec digest `sha256:048a0223c79f2542cbfe7cc154cb6c13210afbf761487e7a745cd9b318049809`.
- Hai task nối tuần tự: **Triển khai và Verify ứng dụng** (`coding-agent@0.3.0`, Harness/Luna, chỉ `app.py`) → **Phê duyệt trước bàn giao** (`approval@0.1.0`). Task sau chỉ bắt đầu khi task trước thành công. Baseline/source reference trong plan đã đối chiếu với project riêng.
- Người dùng đã duyệt đúng plan digest trên lúc `2026-10-18T08:45:36Z` (15:45:36 giờ Việt Nam). Kiểm tra readiness GET sau lần duyệt này đạt đúng release/model đã khóa. Sau khi người dùng xác nhận bắt đầu, revision lên **5**, dispatch gắn đúng plan và run `4d275bfc-6baf-416d-bddd-9c7d5d5639af`.

### Kết quả thực thi và cổng bàn giao

Lượt thực thi bắt đầu lúc **15:47:47 ngày 18/10/2026**, trả kết quả lúc **15:48:08**, mất **21.116 giây**. Có đúng một iteration triển khai bằng Harness/Luna, **9.691 token** (7.171 input, 2.520 output); provider không báo giá tiền. Không chạy thêm model khi nối UI bằng chứng hoặc tạo bản xem thử.

- Candidate: `fcfbca06-ee84-55cb-bec5-74fe05179357`, digest `sha256:136af03cfdb34e8ce02edfa752b4708012c84511c0266a94557d5198ab761616`, chỉ đổi `app.py`.
- Kernel thực thi command unittest thật trên candidate: **9 test chạy, exit 0, không timeout**, `stop_reason=CHECKS_PASSED`. SHA-256 của `test_acceptance.py` là `09f2ea7c7bc4fabf1d8732590a67f68ae2062422f5f545cb486efe3ecd1c72c8`, đã đối chiếu với file cố định trong repo gốc. Repo gốc vẫn clean tại baseline; không áp candidate vào đó.
- Artifact patch `4f683e69-f470-5c01-9fc3-83440dbf9384` có payload đã lưu và checksum khớp. Hạn truy xuất artifact hiện là **15:47:47 ngày 19/10/2026**; hết hạn không được bỏ chốt để duyệt nội dung chưa đọc.
- Khi ghi nhận candidate ban đầu, task triển khai **WAITING_APPROVAL** với `pending_result=SUCCEEDED`, approval `448abc2b-c90d-4713-9c7e-0b76c0542f0e`. Khi kiểm tra lại trong lượt chỉnh giao diện, task triển khai đã **SUCCEEDED**, còn **Phê duyệt trước bàn giao** đang **WAITING_APPROVAL**, approval `9ba12285-c23d-4b06-9cde-f3037febad47`. Workflow chưa hoàn tất; candidate/digest không đổi. Lượt chỉnh giao diện không gửi quyết định, commit, merge hay push.
- Dữ liệu runtime canonical nằm trong RunRepository (`data/adlc-runs.sqlite3`) và checkpoint Task Loop, không suy ra mất run vì bảng ORM legacy `adlc_workflow_run` không có bản ghi tương ứng. Dùng API/đối soát chính thức; không sửa trực tiếp SQLite để chuyển trạng thái.

Tab **Kết quả** nay hiển thị thêm **Kiểm thử do hệ thống chạy**, đọc API inspection Task Loop đã xác thực. Phần này kiểm tra scope run/task, attempt hiện tại, candidate/spec digest và artifact patch trước khi hiện đạt; không đọc lời tự báo của agent để tạo badge xanh. History thiếu, snapshot fallback, dữ liệu MOCK, sai candidate/attempt, test rỗng, exit khác 0 hoặc timeout đều không được hiện đạt. Báo cáo agent và **Verify độc lập** vẫn là các phần riêng; lượt này chưa có Verify độc lập/TestForge hoặc memory-backend evidence.

Bằng chứng có cấu trúc: `docs/report/delivery-workspace/live-acceptance-evidence.json`, gồm report command, token usage, candidate, checksum và quan sát UI riêng. Lưu ý chẩn đoán: event `workflow_run.created` của coordinator còn cờ legacy `mock=true` đặt cứng; request triển khai thực tế `mock=false`, executor Harness, token usage và kết quả command thật được đối chiếu riêng. Không sửa ngược event lịch sử hoặc dùng cờ legacy này làm chứng nhận thực thi. Đây là lỗi telemetry còn cần xử lý, không phải bằng chứng một simulator đã chạy thay agent.

### Xem thử ứng dụng trước khi duyệt

[Bản xem thử local](http://127.0.0.1:8088/) chạy từ bản sao **đúng byte** của `app.py` trong candidate tại `adlc-flow/data/delivery-previews/taskboard-fcfbca06/app.py`. SHA-256 file: `52068adf8aeb12dd6bcfde51d0db61fa9ef997aae831cc60ddbd3dfa651014a0`. Đã đọc mã nguồn trước khi chạy; chỉ bind loopback, không đưa vào repo gốc hoặc phát hành. Đây là tiến trình Python local riêng, **không phải sandbox bảo mật** hay dịch vụ hosting production. Dữ liệu xem thử nằm trong RAM và mất khi tiến trình dừng.

Quan sát bằng trình duyệt trên đúng bản sao này:

- Thêm công việc, đánh dấu hoàn tất/bỏ hoàn tất, lọc tất cả/chưa xong/đã xong hoạt động.
- Chuỗi `<b>Văn bản thuần</b>` hiển thị nguyên văn, không thành markup. Đây không phải một cuộc kiểm thử bảo mật đầy đủ.
- Đã xem desktop và breakpoint **390×844**; document scroll width là **390px**, các input/button nằm trong viewport, text xuống dòng. Không coi hai kích thước là chứng nhận cho mọi thiết bị.
- Nút xóa trên UI chưa được bấm trong đợt smoke này; HTTP delete đã có trong 9 test kernel. Người dùng có thể thử trên dữ liệu RAM của bản xem thử trước khi quyết định.
- Còn điểm cần cân nhắc về accessibility: ô thêm công việc có placeholder nhưng chưa có label chuyên biệt. Không sửa thầm candidate đã qua kernel hoặc che nhận xét này bằng kết quả test API.

Bước tiếp theo: đăng nhập ADLC nếu phiên cũ hết hạn, mở công việc → **Kết quả** để đọc kiểm thử; **Xem thay đổi & duyệt** hoặc **Xem patch & bằng chứng** dẫn tới bộ duyệt patch hiện có. Đọc patch/candidate chính xác và thử ứng dụng trước khi quyết định. Chỉ người dùng gửi quyết định; sau gate triển khai còn gate **Phê duyệt trước bàn giao** của workflow. Không có bước commit/push trong workflow này.

Budget của một Task Loop: tối đa 3 iteration, 2 lượt không tiến triển, 40.000 token và 600 giây theo LiveLoopSpec. Plan còn mang policy task riêng: `timeout_ms=120000`, `retry.max_attempts=3`; budget loop không phải cam kết tổng chi phí/thời gian của mọi attempt trong workflow. Đây là giới hạn trên, không phải dự báo thời lượng hay cam kết sẽ tạo được ứng dụng. Chỉ khi kernel chạy bộ test thật trên candidate mới được báo kết quả; UI tương tác/responsive cần kiểm tra riêng.

Ảnh live: `08-live-workflow-review.jpg` (workflow), `09-live-plan-review.jpg` (kế hoạch), `10-live-plan-approval.jpg` (cổng duyệt plan trước khi người dùng xác nhận), `11-live-start-confirmation.jpg` (cổng bắt đầu trước xác nhận), `12-live-task-loop-results.jpg` (9 test hiển thị trong ADLC), `13-candidate-desktop.jpg`, `14-candidate-mobile.jpg` (ứng dụng từ đúng candidate), `15-live-candidate-review.jpg` (cổng duyệt candidate chưa gửi). Sau khi người dùng đăng nhập lại, đã mở trang run, đọc được patch đúng digest và không gửi quyết định; bằng chứng vẫn truy xuất được sau restart.

Trong lúc kiểm tra form chọn thư mục trước bản vá, một Flow trống đã được tạo nhưng Delivery POST bị từ chối 422; không có model call cho Flow đó. Record được giữ nguyên, không âm thầm xóa dữ liệu để làm sạch kết quả.

### Màn hình duyệt kết quả đã thu gọn

Mở trang run từ **Xem thay đổi & duyệt**. Mặc định là tab **Thay đổi**, không còn xếp tất cả panel kỹ thuật thành một trang dài:

- **Thay đổi**: so sánh trước/sau hai cột; màu đỏ cho phần xóa, xanh cho phần thêm; số dòng và thống kê từng file. Có chế độ một cột và ngắt dòng, mặc định một cột khi mở ở viewport hẹp. Chỉ đánh số/context có thật trong unified diff; patch không hỗ trợ hoặc thiếu hunk được giữ nguyên dạng text, không đoán nội dung còn thiếu. Mã nguồn luôn là text, không thực thi HTML trong patch. Bản gốc và nút tải patch vẫn có sẵn.
- **Kiểm thử & Verify**: bằng chứng Task Loop thật ở riêng phía trên, tái sử dụng kiểm tra scope/candidate/attempt/spec/patch của Results. Bên dưới là **giao diện mẫu Verify và TestForge**, có nhãn rõ và các trạng thái chờ, không tạo PASS, receipt, số test giả hoặc thao tác thực thi. Phần mẫu không chứng minh tích hợp backend đã chạy và không tham gia điều kiện phê duyệt. Dữ liệu/thao tác Verify và replay thật vẫn truy cập trong mục mở rộng riêng, giữ nguyên các chốt hiện có.
- **Hoạt động & nâng cao**: báo cáo lưu, artifact, lịch sử iteration và sự kiện; contract/memory/cấu hình trong mục thu gọn. ID, checksum, candidate digest và thời hạn lưu vẫn đọc được khi mở chi tiết.

Thanh tổng quan chỉ đưa lên số bản thay đổi, số test có bằng chứng đã đạt và tiến độ task. Các task chưa đủ bằng chứng không được tính là đạt. Điều hướng tab bằng bàn phím được hỗ trợ. Patch review vẫn được giữ mounted khi đổi tab để không mất ràng buộc duyệt; chưa tải được hoặc hết hạn thì nút duyệt tiếp tục bị khóa. Giữ nguyên title/phạm vi của approval thật, không đổi cổng bàn giao thành cổng duyệt candidate.

Ảnh kiểm tra live: `16-source-review-coloured.jpg` và `17-quality-review-samples.jpg` trong `docs/report/delivery-workspace`. Ảnh thứ hai cố ý phân biệt **9 test thật** với **mẫu chưa thực thi**. Không gọi thêm model, restart dịch vụ hoặc gửi approval khi thay đổi UI. Trình duyệt kiểm tra dùng kỹ năng computer-use để quan sát trực tiếp và chụp ảnh; không lấy kết quả từ fixture để thay cho run thật.

## Nghiệm thu và giới hạn

### H8A — Xem sơ đồ công việc ngay trong Kế hoạch

Mở công việc → **Bước 3 · Kế hoạch**. Mặc định là **Sơ đồ**; mũi tên đi từ công việc trước tới công việc phụ thuộc. Nhánh song song và điểm hội tụ không bị biến thành cây hay nhân bản task. Nhãn màu gom theo ID giai đoạn nguồn, không đoán từ tên. Có thu nhỏ/phóng to/đặt lại; trên màn hình hẹp có thể cuộn ngang trong khung hoặc chuyển sang **Danh sách**.

Chọn một ô hoặc một dòng để xem mục tiêu, đầu ra, công việc trước/sau, tiêu chí đã khai báo, phạm vi sửa, executor và gói thực thi. Đầu vào và JSON kỹ thuật nằm trong mục thu gọn. Thông tin còn thiếu được ghi rõ; không tự sinh tiêu chí, người được giao hoặc kết luận Verify. Nút **Xem thay đổi & bằng chứng** chỉ điều hướng sang trang run, không duyệt hay chạy lại agent. Enter mở chi tiết; Escape đóng khi đang focus trong drawer và trả focus về công việc.

Sơ đồ, danh sách, Gantt và Kanban cùng đọc `ExecutionPlan.tasks`. Trạng thái runtime chỉ gắn khi Delivery/flow/plan/run và trace task trùng nhau, có đúng một bản ghi tương ứng. Sai hoặc thiếu liên kết được ghi **Chưa đối soát**, không tự coi là hoàn tất. Đổi plan/digest/run sẽ bỏ lựa chọn chi tiết cũ; polling cập nhật drawer theo task mới nhất. Trạng thái hoàn tất vẫn không phải Verify PASS.

Giới hạn được hiển thị ngay trong kế hoạch: compiler trực tiếp hiện tạo **một task cho mỗi giai đoạn**. H8A chỉ làm rõ graph thật. H8B nay đã bổ sung Product Cycle bền vững và bản nháp/lịch sử; tạo lại task graph từ đặc tả/feedback và thực thi chu kỳ kế tiếp vẫn thuộc H8C–H8E trong [kế hoạch Product Loop](product-loop-implementation-plan.md).

Nghiệm thu H8A ngày 18/10/2026:

- Workspace thật ở trên hiển thị **2 task / 1 liên kết**, task triển khai hoàn tất, gate bàn giao vẫn chờ người dùng. Không tạo run, gọi model, gửi approval, commit hay push trong lượt này.
- Fixture nhánh **4 task / 4 liên kết** được biên dịch và đối chiếu toàn bộ JSON bằng backend compiler thật; chỉ dùng trong trang kiểm tra có nhãn **dữ liệu mẫu, không thực thi**, không chứng minh chạy agent/Verify thật.
- **186 test frontend / 18 suite đạt**, bao gồm view/drawer, scope runtime, stale selection, zoom, keyboard/axe, Plan Detail và Run Detail/approval regressions. **1 test backend** đối chiếu fixture với compiler đạt; Ruff file test đạt. Semantic/syntax TypeScript check riêng **8 file H8A** không có diagnostic; không coi full repository build/typecheck là đạt.
- Đã kiểm tra desktop 1280×720 và narrow 390×844. Ở narrow, document rộng 390px; khung graph rộng 264px và cuộn nội bộ cho canvas 568px. Drawer nằm trong viewport, có cuộn riêng. Đã trả viewport về mặc định sau kiểm tra.
- Ảnh thật: `18-h8a-live-task-graph.jpg`, `19-h8a-live-task-details.jpg`. Ảnh fixture có nhãn: `20-h8a-branching-fixture.jpg`, `21-h8a-narrow-graph.jpg`, `22-h8a-narrow-task-details.jpg`, trong `docs/report/delivery-workspace/`.

Đã có test SQL thật cho hai review, stale revision, semantic digest, idempotent note/audit, cách ly owner/superuser, chặn managed project, khôi phục plan sau restart, chặn mock, chặn legacy key và mất acknowledgement. Test coordinator dùng package **human control gate** thật, dừng WAITING_APPROVAL, không gọi AI hoặc GitHub.

Migration được test với convention Alembic thật, cả database mới và `create_all` trước migration, so sánh metadata không drift, từ chối bảng lookalike thiếu constraint.

Kiểm thử ngày 18/10/2026:

- 140 test backend tập trung (Delivery, migration, H7B, naming, H7A/guards và plan materialization) đạt.
- 25 test frontend/client/navigation/redirect đạt.
- Bản vá transport SDK/model pin, tách web credential khỏi plugin bearer và preflight không dispatch được kiểm thử lại cùng Delivery và migration: **46 test đạt**. Client Delivery: **6 test đạt**, bao gồm thông báo runtime chưa sẵn sàng. Lần chạy mặc định gặp quyền thư mục temp cũ trên Windows; chạy lại với thư mục temp mới riêng trong `data/` đạt, không nới quyền hệ điều hành.
- Kiểm tra trên trình duyệt phát hiện placeholder đè lên credential tự điền; Input của form đăng nhập nay dùng placeholder native, giữ nguyên cơ chế chặn autofill của field cấu hình. **23 test frontend** trong 4 suite (client Delivery, Input a11y/autofill, Login a11y) đạt. Ảnh `07-live-login-ready.jpg` là trang đăng nhập live sau sửa, không phải phiên đã xác thực hoặc bằng chứng chạy model.
- Sau bản vá login lifecycle và registry enforcement: **55 test backend** (Delivery, factory startup và team access) cùng **6 test bootstrap Harness** đạt. Hai regression callback login sau unmount và provider registry được chạy thất bại trước bản vá rồi đạt sau sửa.
- Bộ frontend tập trung sau bản vá gồm login lifecycle/a11y/autofill, client Delivery, UI/model/navigation/redirect và project-list GET guard: **51 test trong 10 suite đạt**. Regression submit form qua portal và GET project trùng được bao phủ; không coi test fixture là lượt chạy agent thật.
- Nối bằng chứng kernel vào Results: **75 test frontend trong 11 suite đạt**, bao gồm 24 trường hợp mới cho schema/scope, candidate/attempt/patch binding, lịch sử thiếu, MOCK, zero-test/exit/timeout và trạng thái chờ duyệt. Không gọi model hoặc thao tác release trong các test này. PowerShell launcher đã parse thành công và kiểm tra startup/idempotency thực tế. Semantic/syntax TypeScript check riêng cả ba file kernel mới không có diagnostic; full TypeScript còn lỗi khác ngoài phạm vi, không coi full build/typecheck là đạt.
- Thu gọn Run Detail, so sánh mã nguồn và khung chất lượng: **134 test trong 12 suite đạt** (toàn bộ RunDetailPage, Kernel Results và workspace page). Bao gồm hunk/line-number, raw fallback, escape HTML, đổi chế độ diff, tab bàn phím, mẫu không gọi API/không mở khóa duyệt, expiry và response trễ khác run. Semantic/syntax TypeScript check riêng 5 file triển khai của thay đổi này không có diagnostic; không coi full repository typecheck/build là đạt. Các file mới được format qua Biome stdin, không đổi cấu hình formatter toàn repo.
- Ruff của 8 file Python thay đổi đạt. Biome CLI gặp xung đột nested root configuration có sẵn; không sửa cấu hình toàn repo trong lượt này, không gọi full formatter/build là đạt.
- Đã mở UI thật ở bản kiểm tra độc lập, xem desktop 1440px, điện thoại 390px và hộp phê duyệt. Ảnh nằm ở `docs/report/delivery-workspace`.
- Bộ backend rộng hơn có 345 test đạt, 14 failure và 30 setup error do hai suite source-level đang trỏ layout cũ `adlc-flow/base/langflow/...` không tồn tại. Không sửa đường dẫn test ngoài phạm vi để che kết quả. Không gọi toàn bộ repository là xanh.
- TypeScript semantic check không có lỗi ở các file UI/client/routes mới trong phạm vi đã kiểm tra, nhưng dependency/source khác của dự án vẫn có diagnostics; chưa coi full build/typecheck là đạt.

Ảnh và trang `/tests/delivery-workspace-preview/index.html` dùng fixture **có nhãn kiểm tra**, không chứng minh một ứng dụng đã được AI tạo xong. Fixture không nằm trong router sản phẩm và không gọi model, ghi database hay push GitHub.

Những việc **chưa được chứng nhận**: một ứng dụng bất kỳ tự phát triển hoàn chỉnh từ đầu đến cuối; chuỗi shared team → agent identity/delegation → release; tự áp yêu cầu phát sinh vào một run mới; migration PostgreSQL live. Cần nghiệm thu trên repo/phạm vi được người dùng chọn và các gate duyệt thật. Không bỏ gate để đạt mục tiêu “tự động”.

## File chính

- UI: `adlc-flow/frontend/src/features/delivery-workspace/`
- Kiểm thử kernel trong UI: `kernel-results.tsx`, `kernel-evidence.ts`, `kernel-results.test.tsx` trong thư mục trên; chỉ đọc inspection, không có nút thực thi/retry model hoặc tự phê duyệt.
- Duyệt thay đổi: `adlc-flow/frontend/src/pages/RunDetailPage/` gồm `CodeDiffViewer.tsx`, `code-diff.ts`, `RunReviewEvidence.tsx`, `SourcePatchReview.tsx`, `review.css` và các regression test tương ứng.
- Client: `adlc-flow/frontend/src/controllers/API/delivery.ts`
- API: `adlc-flow/langflow/api/v1/adlc_delivery.py`
- Guards/digests: `adlc-flow/langflow/adlc/delivery.py`
- SQL model: `adlc-flow/langflow/services/database/models/adlc_delivery.py`
- Tests: `adlc-flow/tests/unit/adlc/test_delivery*.py`
- Bật frontend/backend nền local: `adlc-flow/scripts/start_delivery_services.ps1`

## H8C — Kế hoạch theo chu kỳ

Chu kỳ tiếp theo đã có **Chốt đầu vào → Tạo task chi tiết qua Harness → Xem graph → Duyệt graph**.
Không kế thừa plan/phê duyệt/run chu kỳ trước; không tự Start sau duyệt. Task Loop giữ nguyên một task với spec/check đã khóa.
Xem [hướng dẫn H8C và ranh giới thực thi](harness-milestone-h8c.md) cho cấu hình, thao tác UI, kích hoạt và bằng chứng kiểm thử.
