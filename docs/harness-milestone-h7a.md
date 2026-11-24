# H7A — Nền tảng quyền theo project và quản trị bốn role

Ngày: 16/10/2026. Đây là triển khai foundation, không phải mở toàn bộ luồng cộng tác H7.
Kế hoạch tổng: [Team Collaboration & Access Control](adlc-team-roles-plan.md).

Cập nhật 18/10/2026: [H7B](harness-milestone-h7b.md) đã bổ sung chế độ
`COLLABORATION` có xác nhận cho project rỗng và API/UI authoring dùng chung.
Phạm vi `CONFIGURATION_ONLY` bên dưới là trạng thái tại thời điểm hoàn tất H7A;
không tự đổi mode project hoặc mở shared execution khi nâng source.

## Phạm vi đã triển khai

- Bốn preset `adlc.admin`, `adlc.developer`, `adlc.business_analyst`, `adlc.tester`.
  Không thay nghĩa hoặc sửa các role legacy `admin`, `developer`, `viewer`.
- Policy theo project trong `adlc_project_access`; role assignment và nguồn grant
  vẫn dùng bảng `authz_role_assignment` / `authz_role_assignment_grant` hiện có.
- Một action catalog đóng và một hàm quyết định chung cho API quản trị và provider
  trên authorization port hiện có. Quyền nhiều role hợp nhất, explicit deny ưu tiên.
- Owner, superuser và `LANGFLOW_AUTHZ_ENABLED=false` không bypass policy của
  project đã được quản trị. Các project private cũ giữ hành vi tương thích.
- Danh sách legacy cũng lọc policy trước owner override; thu hồi quyền không
  để lại tên project trên danh sách của người tạo. Link PUBLIC cũ không mở được
  flow nằm trong project quản trị. Không dùng SQL scope union với owner để bỏ
  qua bước kiểm tra deny của team.
- Mỗi mutation có compare-and-swap `expected_revision`, kiểm tra lại quyền dưới
  write lock, audit bắt buộc cùng transaction và rollback khi không ghi được audit.
- Không có policy cache giữa các request: worker khác đọc lại membership/rules
  đã commit. Không chờ hết TTL của token để nhận biết việc thu hồi.
- Bảo vệ Admin **có hiệu lực** cuối cùng, kể cả trường hợp một người nhiều role
  có deny, hai Admin đồng thời thu hồi, và thao tác disable/delete tài khoản qua
  lifecycle authorization hiện có.
- API phân quyền legacy không được sửa assignment của các role ADLC quản lý.
  Các grant ADLC giai đoạn này là manual, scope project; không tự nhận quyền IdP.
- UI thật tại `/team-access`: thành viên, role/rules, preview, quyền hiệu lực và audit.
  UI không dùng dữ liệu mẫu hoặc tự quyết định quyền theo tên role.

## Ranh giới quan trọng

H7A chỉ tạo **project mới, rỗng**, với mode bất biến `CONFIGURATION_ONLY`.
Không có thao tác bật team mode cho project đã có dữ liệu. Không chuyển lịch sử
run, source, contract, memory hoặc secret của người tạo sang nhóm một cách ngầm định.

Năm hành động có hiệu lực trong foundation:

- `project:read`
- `policy:read`
- `policy:manage`
- `membership:manage`
- `audit:read`

Các quyền workflow/contract/Verify/candidate thuộc H7B; thực thi, delegation,
memory và publish thuộc H7C. Admin có thể chuẩn bị các grant này trong policy,
nhưng engine vẫn trả `TEAM_SHARED_EXECUTION_NOT_ENABLED`: grant không đủ để mở
một chức năng chưa được triển khai. Một quyền chưa được cấp có thể trả
`TEAM_PERMISSION_DENIED` trước đó.

H7A chưa cho thành viên đọc/viết chung nội dung workflow. H7B mới nâng các truy
vấn owner-only và approval thành actor-aware. H7C mới cho agent dùng delegation
và broker theo policy. Không coi role mới là đã hoàn thành các bước này.

Khi resolve flow, provider dùng folder thực tế từ database, không tin domain hay
folder_id client khai. Folder con nằm dưới project quản trị cũng đi qua ranh giới
này. Scope lỗi/vòng lặp hoặc policy không hợp lệ bị chặn, không fallback allow.

## Cách dùng sau khi triển khai source và migration

1. Dừng các dịch vụ dùng chung database trong cửa sổ bảo trì. Sao lưu database
   theo backend đang sử dụng; xác định tài khoản quản trị nền tảng hiện có.
2. Triển khai đồng bộ source backend/frontend và migration
   `h7a1b2c3d4e5` (sau `c41e8d07a9b2`) bằng cơ chế migration của backend.
   Không dùng `stamp head` để bỏ qua migration. Migration thêm schema và bốn
   preset; **không gán role cho tài khoản nào**.
3. Đăng nhập ADLC bằng tài khoản cá nhân. Auto-login, API key và credential của
   tool/agent không dùng để quản trị H7A.
4. Mở **Thành viên & quyền** trên thanh điều hướng, hoặc
   [trang phân quyền](http://localhost:3000/team-access/).
5. Một tài khoản active `is_superuser` hiện có được tạo project rỗng. Tài khoản
   đó nhận Admin của đúng project mới, có audit. H7A không có API tự nâng một
   người thành quản trị nền tảng và không tự cấp quyền cho tài khoản đang mở chat.
6. Trong tab **Thành viên**, nhập username ADLC đã tồn tại/đang hoạt động, chọn
   role và xem bước xác nhận trước khi lưu. UI không tạo tài khoản, gửi email hay
   sửa role ở project khác. Form thay role nói rõ nó thay bộ role hiện có; API hỗ
   trợ bộ nhiều role có cùng ràng buộc deny/độc lập.
7. Trong **Vai trò & quyền**, chọn role; chỉnh Allow/Deny, xem diff và người bị
   ảnh hưởng rồi lưu. Admin bắt buộc giữ các quyền quản trị thiết yếu của project;
   engine vẫn kiểm tra không làm mất Admin có hiệu lực cuối cùng.
8. **Quyền hiệu lực** giải thích kết quả theo policy hiện tại. Thành viên chỉ
   xem quyền của mình; người có quyền quản trị thành viên mới kiểm tra người khác.
9. **Nhật ký** hiển thị actor, revision và thời điểm; thời gian UI theo Việt Nam.

Không cần thêm biến môi trường cấp role. Factory mặc định đăng ký provider
project-policy; startup kiểm tra schema/preset và từ chối thiếu provider nếu đã
có project được quản trị. Nếu cài authorization plugin thay thế, plugin phải
thực hiện hợp đồng team-policy; không thể giữ pass-through rồi chỉ bật cờ AUTHZ.

## API

Prefix: `/api/v1/adlc/team-access`. Mọi route yêu cầu explicit user access token,
không nhận `owner_id`, global domain hoặc danh tính actor trong command.

| Route | Quyền / hành vi |
| --- | --- |
| `GET /projects` | Danh sách project nhìn thấy và khả năng bootstrap của người gọi |
| `POST /projects` | Operator tạo project rỗng và Admin project ban đầu |
| `GET /projects/{id}` | Policy/member đầy đủ chỉ cho Admin; người khác chỉ có quyền của mình |
| `PUT /projects/{id}/policy` | Policy revision + rules đóng; bắt buộc preview ở UI |
| `PUT /projects/{id}/members` | Username active, bộ role project, expected revision |
| `POST /projects/{id}/members/{user}/revoke` | Thu hồi, không xóa tài khoản/lịch sử |
| `GET /projects/{id}/effective/{user}` | Xem quyền hiệu lực; scope và quyền người gọi vẫn được kiểm tra |
| `GET /projects/{id}/audit` | Tối đa 100 sự kiện quản trị gần nhất của đúng project |

Mutation thành công tăng revision. Hai command cùng revision không cùng thắng.
UI giữ bản nháp cũ để đối chiếu nhưng khóa lưu khi server đã sang phiên bản mới;
không tự rebase hay tự gửi lại mutation.

## Mã lỗi vận hành

- `TEAM_EXPLICIT_LOGIN_REQUIRED`: đăng nhập cá nhân, không đổi flag để vượt guard.
- `TEAM_BOOTSTRAP_OPERATOR_REQUIRED`: cần operator hiện có; không tự nâng quyền DB.
- `TEAM_POLICY_REVISION_CONFLICT`: tải phiên bản mới, kiểm tra và quyết định lại.
- `TEAM_LAST_ADMIN_PROTECTED`: gán một Admin active/có hiệu lực khác trước khi thu hồi.
- `TEAM_MANAGED_ROLE_USE_SCOPED_API`: dùng UI/API H7A, không sửa assignment qua API legacy.
- `TEAM_PRESETS_NOT_READY` / `TEAM_ENFORCEMENT_PROVIDER_REQUIRED`: kiểm tra deployment,
  migration và provider; không fallback sang service allow-all.
- `TEAM_POLICY_STORE_UNAVAILABLE` / `TEAM_POLICY_STORE_INVALID`: thao tác bị chặn.
  Khôi phục store hoặc sửa bằng migration có kiểm chứng, không xóa policy table.

Downgrade tự động bị từ chối để không biến project đã được quản trị thành project
allow-by-owner. Rollback code/store phải có kế hoạch giữ ranh giới quyền và audit;
không chạy bản cũ không biết team policy trên dữ liệu đã được chuyển sang H7A.

## Kiểm chứng và những điều chưa được thực hiện

Test H7A dùng SQLite thật và HTTP ASGI; UI dùng React Query và response fixtures.
Không gọi model, Docker, memory backend hay GitHub để chứng minh phân quyền.
Các ca gồm isolation, chống self-escalation, schema/role migration, unknown action,
deny nhiều role, revision/race, audit rollback, thu hồi giữa worker, chặn API key,
owner override, danh sách/link public, scope flow giả và folder con, cùng các
thao tác UI xác nhận. Migration được thử cả trường hợp schema được tạo trước
bằng metadata và trường hợp role trùng tên/ID; không chấp nhận role chưa xác minh.

Kết quả kiểm tra ngày 16/10/2026:

| Kiểm tra | Kết quả |
| --- | --- |
| H7A + factory + guards + visibility prefilters + public access + API quản trị/lifecycle | 232 test backend đạt |
| Trang phân quyền và API client | 13 test đạt (2 suite) |
| Ruff trên các module H7A và các guard/list/public đã sửa | Đạt |
| Biome trên 4 file UI/client/test mới | Đạt |
| TypeScript semantic check cho page/client H7A | 0 lỗi trong phạm vi H7A |

Không coi đây là toàn bộ repository/build đã xanh: kiểm tra TypeScript còn
13 diagnostic ở dependency/source ngoài H7A; một số test authorization cũ còn
trỏ vào đường dẫn `base/langflow` không tồn tại trong cấu trúc repo hiện tại.
Chưa chạy E2E trình duyệt với database triển khai thật.

Không tự chạy migration hoặc gán quyền trên database người dùng đang dùng trong
lượt triển khai source này. Chưa chứng minh chạy chung nhiều role trên luồng
Harness live; đó là acceptance của H7B/H7C, không phải H7A.
