# Milestone H7A — Quyền theo project và bốn vai trò

> Ngày soạn kế hoạch: 15/10/2026. Foundation H7A triển khai: 16/10/2026.
> Trạng thái: **H7A đã có source; chưa áp dụng quyền mới lên database đang chạy.** H7B–H7D vẫn là kế hoạch.
> Tài liệu lõi tiếng Việt gộp từ hai tài liệu cũ trong `docs/` (hiện lưu trên nhánh `agentHarness`):
> `docs/harness-milestone-h7a.md` (foundation đã triển khai) và `docs/adlc-team-roles-plan.md`
> (kế hoạch tổng Team Collaboration & Access Control).

## Kết quả cần đạt

ADLC trở thành không gian làm việc chung của con người và agent trong cùng một project: có yêu cầu, contract, công việc được giao, kế hoạch,
thực thi, bằng chứng, phê duyệt và kết quả bàn giao — **không** tạo một hệ thống task riêng bên cạnh workflow. Bốn role trên giao diện:
**Admin, Developer, Business Analyst, Tester**. Admin quyết định ai được làm gì, với tài nguyên nào và trong project nào. Agent có danh tính
thực thi riêng, nhận phạm vi giao việc cụ thể; không đóng giả tài khoản người. Phạm vi giai đoạn này là phân quyền và cộng tác: không tự cấp
quyền GitHub, không mở quyền ghi `main`, không đổi provider/model hay chạy workflow trả phí.

## Nền tảng hiện có và khoảng trống

Đối chiếu source hiện tại:

| Hiện có | Cần bổ sung |
| --- | --- |
| `AuthzRole`, assignment theo domain, team, share, edit lock và audit trong `langflow/services/database/models/auth/authz.py` | Bộ quyền nghiệp vụ ADLC và chính sách theo project |
| API `/authz/roles`, `/authz/role-assignments`, `/authz/teams`, `/authz/me/permissions` | UI quản trị, xem quyền hiệu lực, và resource/action cho Run, Contract, Verify, Harness |
| Role hệ thống cũ `viewer`, `developer`, `admin` | Preset ADLC có phiên bản; không âm thầm sửa quyền của role cũ |
| `Folder` là project; `AdlcLocalProject` nối project với source path | Scope project bền vững cho tài nguyên cộng tác, không lấy đường dẫn local làm ranh giới quyền |
| Run, contract và nhiều artifact được giữ theo `owner_id` | Cho người khác trong project truy cập theo quyền, vẫn giữ người tạo để truy vết |
| Harness workflow kiểm tra phê duyệt từ chính owner và đúng digest | Cho thành viên đủ quyền phê duyệt, ghi đúng danh tính người quyết định |
| Guard và UI permission gate có sẵn | Chế độ cộng tác phải từ chối khi không xác định được quyền |
| `PackageAccessPolicy` và registry capability có sẵn | Chính sách bền vững theo project và delegation cho agent |

Hai điểm phải giải quyết trước khi coi hệ thống hỗ trợ team:

- `LangflowAuthorizationService` mặc định là pass-through. Chỉ bật cờ AUTHZ không chứng minh đã có policy enforcement; cần xác minh provider
  được đăng ký và có kiểm tra allow/deny thực tế. Đây là nhận xét về source mặc định, không phải kết luận rằng môi trường đang chạy đã đăng
  ký hay chưa đăng ký một plugin khác.
- Guard hiện có owner override; UI có fallback cho phép khi thiếu dữ liệu quyền. Hai hành vi tương thích legacy này không được trở thành
  đường vòng trong project đã bật cộng tác. Backend là nơi quyết định, không phải việc ẩn nút trên UI.

## Mô hình quyền

### Role + project + hành động + điều kiện

Role là preset dễ hiểu, **không phải** thứ bậc `BA < Tester < Developer < Admin`; một người có thể là Developer ở project A và Tester ở
project B. Quyết định truy cập gồm:

1. Danh tính đã xác thực và loại actor: USER, AGENT hoặc SERVICE.
2. Membership còn hiệu lực trong project chứa tài nguyên.
3. Quyền hành động được cấp cho role ở đúng scope.
4. Điều kiện của tài nguyên, contract và approval: revision, digest, trạng thái, người soạn, người duyệt, target repository/branch và môi
   trường.

Quyền từ nhiều role được hợp nhất, sau đó áp dụng deny và các ràng buộc bắt buộc. Có hai role không cho phép một người vượt chốt "không tự
duyệt công việc của mình".

### Hai phạm vi quản trị, vẫn chỉ bốn tên role

- **Admin toàn hệ thống** quản lý người dùng, project và chính sách nền tảng.
- **Admin project** chỉ quản lý thành viên, quyền và kết nối trong project được giao; không tự cấp Admin toàn hệ thống hay can thiệp project
  khác.
- `is_superuser` hiện tại là cơ chế bootstrap/vận hành, không tự động đồng nghĩa với mọi quyền nghiệp vụ của mọi project. Không dùng bypass
  superuser để hợp thức hóa phê duyệt contract, sửa bằng chứng hay publish ngoài phạm vi.
- Cần chốt người bootstrap và bảo vệ Admin cuối cùng trước khi bật enforcement; đây không phải hành động cấp quyền mà tài liệu thực hiện
  thay operator.

### Admin điều chỉnh được gì

Màn hình ma trận quyền cho từng project: thành viên nào nhận role nào; với mỗi phần — xem, tạo/sửa bản nháp, gửi duyệt, duyệt, thực thi,
quản trị; package/plugin/tool nào được dùng; loại sandbox, nguồn memory, repository, môi trường và ngân sách thực thi nào được phép; ai đủ
điều kiện nhận cổng duyệt nghiệp vụ, kỹ thuật, kiểm thử, publish.

Admin xem trước thay đổi, danh sách người bị ảnh hưởng và quyền hiệu lực trước khi lưu. Mỗi lần lưu tạo revision và audit — không chỉ lưu
checkbox ở frontend. Các preset ADLC dùng định danh riêng (ví dụ `adlc.business_analyst`) để không thay nghĩa role legacy; preset gốc có
phiên bản, tùy chỉnh theo scope được lưu riêng và vẫn được tính bởi cùng dịch vụ authorization — không tạo policy engine thứ hai.

Admin không được tắt các bất biến: không đọc/export secret thô, không sửa bằng chứng Verify, không sửa contract đã khóa tại chỗ, không cho
agent ký phê duyệt thay người, không bỏ chốt phê duyệt bắt buộc bằng cách cấp quyền rộng hơn.

## Ma trận quyền mặc định

Đây là baseline đề xuất; Admin có thể thu hẹp hoặc mở rộng trong giới hạn an toàn. Mọi quyền trong bảng chỉ có hiệu lực ở project được giao
và với dữ liệu được phép xem.

| Phần / hành động | Admin | Developer | Business Analyst | Tester |
| --- | --- | --- | --- | --- |
| Thành viên, role, chính sách | Quản lý đúng scope | Xem quyền của mình | Xem quyền của mình | Xem quyền của mình |
| Requirement, roadmap, contract | Quản trị quy trình; xem | Xem, góp ý, đề xuất sửa | Soạn, gửi duyệt, duyệt nghiệp vụ nếu đủ điều kiện | Xem, góp ý tiêu chí nghiệm thu |
| Workflow | Quản trị quyền và template | Soạn, compile, khởi chạy phần được cấp | Dùng template nghiệp vụ/planning đã cấp | Soạn và chạy workflow kiểm thử được cấp |
| Kế hoạch kỹ thuật | Chỉ định người duyệt | Soạn và duyệt kỹ thuật nếu đủ điều kiện | Xem, kiểm tra phạm vi nghiệp vụ | Xem, góp ý khả năng kiểm thử |
| Source, candidate, code review | Xem; thao tác theo grant kỹ thuật riêng | Sửa trong sandbox, gửi candidate, review | Xem kết quả/diff được chia sẻ, không sửa source | Xem candidate, tạo bug; sửa test trong phạm vi được cấp |
| Test plan, suite | Quản trị quy trình | Góp ý, chạy pre-check | Góp ý theo acceptance criteria | Soạn, đóng băng suite, chạy Verify độc lập |
| Report Verify | Xem, không sửa kết luận | Xem, xử lý lỗi, yêu cầu chạy lại | Xem mức đáp ứng requirement | Xem, chấp nhận/từ chối nghiệm thu trên bằng chứng |
| Duyệt publish | Cấp người có quyền; không tự bypass gate | Chỉ người được cấp quyền publish, đủ điều kiện độc lập | Không mặc định | Không mặc định |
| Integrations, secret reference | Quản lý kết nối và ai được sử dụng | Sử dụng reference được cấp, không lấy secret | Không mặc định | Sử dụng backend kiểm thử được cấp |
| Task, bàn giao, thảo luận, hoạt động | Quản trị project | Làm việc trong phạm vi được giao | Làm việc trong phạm vi được giao | Làm việc trong phạm vi được giao |

Ghi chú quan trọng:

- Admin là người quản trị quyền; không mặc định là reviewer nghiệp vụ, kỹ thuật và kiểm thử cùng lúc — quyền thực hiện các việc đó phải rõ
  ràng. Duyệt nghiệp vụ khác duyệt kế hoạch thực thi; duyệt Verify khác sửa kết quả Verify. Người chạy máy kiểm thử cũng không được tự ghi
  report ĐẠT.
- Tester chỉ sửa test trước khi suite được đóng băng hoặc tạo revision mới. Agent triển khai không được sửa protected tests rồi dùng chúng
  để tự chứng nhận. Với code do agent viết, người giao/điều khiển task là bên chịu trách nhiệm author; agent ID khác user ID không tự đáp
  ứng tính độc lập của reviewer.
- Khởi chạy template nghiệp vụ không đồng nghĩa được chạy package coding tùy ý: compiler và dispatcher cùng kiểm tra package/capability được
  cấp. Merge vào nhánh bảo vệ/production là quyền và policy riêng, mặc định tắt trong giai đoạn này; luồng GitHub hiện tại vẫn chỉ publish
  nhánh làm việc mới.

## Phạm vi đã triển khai (H7A foundation)

- Bốn preset `adlc.admin`, `adlc.developer`, `adlc.business_analyst`, `adlc.tester`. Không thay nghĩa hoặc sửa các role legacy `admin`,
  `developer`, `viewer`.
- Policy theo project trong `adlc_project_access`; role assignment và nguồn grant vẫn dùng bảng `authz_role_assignment` /
  `authz_role_assignment_grant` hiện có.
- Một action catalog đóng và một hàm quyết định chung cho API quản trị và provider trên authorization port hiện có. Quyền nhiều role hợp
  nhất, explicit deny ưu tiên.
- Owner, superuser và `LANGFLOW_AUTHZ_ENABLED=false` **không** bypass policy của project đã được quản trị. Các project private cũ giữ hành
  vi tương thích.
- Danh sách legacy cũng lọc policy trước owner override; thu hồi quyền không để lại tên project trên danh sách của người tạo. Link PUBLIC cũ
  không mở được flow nằm trong project quản trị. Không dùng SQL scope union với owner để bỏ qua bước kiểm tra deny của team.
- Mỗi mutation có compare-and-swap `expected_revision`, kiểm tra lại quyền dưới write lock, audit bắt buộc cùng transaction và rollback khi
  không ghi được audit.
- Không có policy cache giữa các request: worker khác đọc lại membership/rules đã commit; không chờ hết TTL của token để nhận biết việc thu
  hồi.
- Bảo vệ Admin **có hiệu lực** cuối cùng, kể cả trường hợp một người nhiều role có deny, hai Admin đồng thời thu hồi, và thao tác
  disable/delete tài khoản qua lifecycle authorization hiện có.
- API phân quyền legacy không được sửa assignment của các role ADLC quản lý. Các grant ADLC giai đoạn này là manual, scope project; không tự
  nhận quyền IdP.
- UI thật tại `/team-access`: thành viên, role/rules, preview, quyền hiệu lực và audit. UI không dùng dữ liệu mẫu hay tự quyết định quyền
  theo tên role.

## Ranh giới quan trọng

H7A chỉ tạo **project mới, rỗng**, với mode bất biến `CONFIGURATION_ONLY`. Không có thao tác bật team mode cho project đã có dữ liệu; không
chuyển lịch sử run, source, contract, memory hay secret của người tạo sang nhóm một cách ngầm định.

Năm hành động có hiệu lực trong foundation:

- `project:read`
- `policy:read`
- `policy:manage`
- `membership:manage`
- `audit:read`

Các quyền workflow/contract/Verify/candidate thuộc H7B; thực thi, delegation, memory và publish thuộc H7C. Admin có thể chuẩn bị các grant
này trong policy, nhưng engine vẫn trả `TEAM_SHARED_EXECUTION_NOT_ENABLED`: grant không đủ để mở một chức năng chưa được triển khai. Một
quyền chưa được cấp có thể trả `TEAM_PERMISSION_DENIED` trước đó.

H7A chưa cho thành viên đọc/viết chung nội dung workflow. H7B mới nâng các truy vấn owner-only và approval thành actor-aware; H7C mới cho
agent dùng delegation và broker theo policy. Không coi role mới là đã hoàn thành các bước này. Khi resolve flow, provider dùng folder thực
tế từ database, không tin domain hay `folder_id` client khai; folder con nằm dưới project quản trị cũng đi qua ranh giới này. Scope lỗi/vòng
lặp hay policy không hợp lệ bị chặn, không fallback allow.

## API quản trị

Prefix: `/api/v1/adlc/team-access`. Mọi route yêu cầu explicit user access token, không nhận `owner_id`, global domain hay danh tính actor
trong command.

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

Mutation thành công tăng revision; hai command cùng revision không cùng thắng. UI giữ bản nháp cũ để đối chiếu nhưng khóa lưu khi server đã
sang phiên bản mới — không tự rebase hay tự gửi lại mutation.

## Mã lỗi vận hành

- `TEAM_EXPLICIT_LOGIN_REQUIRED`: đăng nhập cá nhân; không đổi flag để vượt guard.
- `TEAM_BOOTSTRAP_OPERATOR_REQUIRED`: cần operator hiện có; không tự nâng quyền DB.
- `TEAM_POLICY_REVISION_CONFLICT`: tải phiên bản mới, kiểm tra và quyết định lại.
- `TEAM_LAST_ADMIN_PROTECTED`: gán một Admin active/có hiệu lực khác trước khi thu hồi.
- `TEAM_MANAGED_ROLE_USE_SCOPED_API`: dùng UI/API H7A, không sửa assignment qua API legacy.
- `TEAM_PRESETS_NOT_READY` / `TEAM_ENFORCEMENT_PROVIDER_REQUIRED`: kiểm tra deployment, migration và provider; không fallback sang service
  allow-all.
- `TEAM_POLICY_STORE_UNAVAILABLE` / `TEAM_POLICY_STORE_INVALID`: thao tác bị chặn; khôi phục store hoặc sửa bằng migration có kiểm chứng,
  không xóa policy table.

Downgrade tự động bị từ chối để không biến project đã được quản trị thành project allow-by-owner. Rollback code/store phải có kế hoạch giữ
ranh giới quyền và audit; không chạy bản cũ không biết team policy trên dữ liệu đã chuyển sang H7A.

## Migration và cách vận hành

1. Dừng các dịch vụ dùng chung database trong cửa sổ bảo trì. Sao lưu database theo backend đang sử dụng; xác định tài khoản quản trị nền
   tảng hiện có.
2. Triển khai đồng bộ source backend/frontend và migration `h7a1b2c3d4e5` (sau `c41e8d07a9b2`) bằng cơ chế migration của backend. Không dùng
   `stamp head` để bỏ qua migration. Migration thêm schema và bốn preset; **không gán role cho tài khoản nào**.
3. Đăng nhập ADLC bằng tài khoản cá nhân. Auto-login, API key và credential của tool/agent không dùng để quản trị H7A.
4. Mở **Thành viên & quyền** trên thanh điều hướng, hoặc trang phân quyền (`http://localhost:3000/team-access/`).
5. Một tài khoản active `is_superuser` hiện có được tạo project rỗng; tài khoản đó nhận Admin của đúng project mới, có audit. H7A không có
   API tự nâng một người thành quản trị nền tảng và không tự cấp quyền cho tài khoản đang mở chat.
6. Tab **Thành viên**: nhập username ADLC đã tồn tại/đang hoạt động, chọn role và xem bước xác nhận trước khi lưu. UI không tạo tài khoản,
   gửi email hay sửa role ở project khác. Form thay role nói rõ nó thay bộ role hiện có; API hỗ trợ bộ nhiều role có cùng ràng buộc deny/độc
   lập.
7. **Vai trò & quyền**: chọn role; chỉnh Allow/Deny, xem diff và người bị ảnh hưởng rồi lưu. Admin bắt buộc giữ các quyền quản trị thiết yếu
   của project; engine vẫn kiểm tra không làm mất Admin có hiệu lực cuối cùng.
8. **Quyền hiệu lực** giải thích kết quả theo policy hiện tại: thành viên chỉ xem quyền của mình; người có quyền quản trị thành viên mới
   kiểm tra người khác.
9. **Nhật ký** hiển thị actor, revision và thời điểm; thời gian UI theo Việt Nam.

Không cần thêm biến môi trường cấp role. Factory mặc định đăng ký provider project-policy; startup kiểm tra schema/preset và từ chối thiếu
provider nếu đã có project được quản trị. Nếu cài authorization plugin thay thế, plugin phải thực hiện hợp đồng team-policy — không thể giữ
pass-through rồi chỉ bật cờ AUTHZ.

## Agent và plugin hoạt động dưới quyền nào

Không cấp một trong bốn role người dùng cho agent rồi cho dùng toàn bộ role đó. Mỗi task có **delegation** do control plane cấp, gồm tối
thiểu: principal agent/service và bên ủy quyền; task/project/run/attempt, thời hạn và trạng thái thu hồi; contract/plan/package digest cùng
action/tool được phép; repository/branch/path, memory namespace và nguồn, sandbox/network profile, testing target, ngân sách và giới hạn
side effect; approval reference khi action yêu cầu — action, tham số và kết quả được duyệt phải khớp tại thời điểm sử dụng.

Quyền thực thi là giao của **delegation còn hiệu lực**, **quyền hiện tại của bên ủy quyền**, **policy project**, **phạm vi plan/contract đã
khóa** và **giới hạn runtime**. Người khởi chạy workflow không tự động là bên ủy quyền cho mọi task: BA có thể khởi tạo một luồng rồi
Developer cấp delegation triển khai ở cổng sau.

Các chốt bắt buộc:

- Agent chỉ đề xuất; quyết định approve/reject nghiệp vụ lấy từ người đăng nhập đủ quyền. API key/agent callback không thay thế chữ ký
  người.
- Plugin khai báo permission manifest; core xác minh và thực thi. Có thể thay policy provider bằng plugin nhưng không được tháo plugin để
  mọi request thành allow.
- Mỗi tool call đi qua broker/guard; không cho raw shell/network/credential tạo đường vòng vượt grant. Sandbox và egress cần cưỡng chế thực
  tế, không chỉ prompt.
- GitHub credential ở publisher broker: agent tạo candidate/commit, không nhận token push, không có tool merge/push trực tiếp.
- Memory lọc theo scope và quyền dữ liệu ngay tại retrieval — không lấy toàn bộ context rồi chỉ lọc khi render UI. Memory không phải nguồn
  cấp quyền hay Verify.
- Webhook xác thực nguồn, không tự cấp quyền: repository phải được map vào project và trigger đã cấp trước; payload issue/label không được
  sửa policy.
- Thu hồi membership/grant chặn dispatch và action tiếp theo; cố gắng hủy công việc đang chạy, không tuyên bố đảo ngược được side effect đã
  gửi ra ngoài. Kết quả chưa chắc chắn thì reconcile receipt, không tự publish lại.

## Luồng cộng tác mục tiêu

1. **Admin thiết lập project:** thêm thành viên, chọn bốn role, cấp kết nối repository/memory/sandbox/testing, chọn người đủ quyền duyệt
   theo từng cổng.
2. **BA chuẩn bị đầu vào:** soạn requirement/contract, acceptance criteria, gửi duyệt. Revision được khóa; thay đổi sau đó là change
   request, không ghi đè.
3. **Developer lập kế hoạch:** tạo workflow từ contract được duyệt; orchestrator chia task; người đủ quyền duyệt kế hoạch kỹ thuật và phạm
   vi thực thi.
4. **Giao cho người hoặc agent:** task có assignee, người giao, brief, phạm vi, dependency và bằng chứng cần bàn giao. Agent tự soạn task
   brief nhưng không tự mở rộng contract; người làm thủ công cũng bàn giao candidate theo cùng chuẩn.
5. **Thực hiện và kiểm tra:** Developer/agent tạo candidate trong nhánh/checkout riêng; Tester dùng suite đã khóa để tái lập và đối chiếu.
   Hệ thống lưu report, môi trường, exit status, revision và digest — kết luận không dựa vào lời agent.
6. **Nghiệm thu và publish:** Tester xác nhận chất lượng; BA xác nhận nghiệp vụ nếu contract yêu cầu; người có grant publish duyệt đúng
   candidate/SHA/target; orchestrator mới được dùng broker để publish và lưu receipt.
7. **Hoàn thành:** mọi người xem cùng kết quả, quyết định, lỗi và lịch sử. Không đóng task thành công chỉ vì có một comment nói đã làm xong.

Các cổng áp dụng theo risk/policy đã khóa trước khi chạy — không thêm một loạt phê duyệt thủ công vào mọi tác vụ nhỏ. Task read-only ít rủi
ro có thể tự chạy trong grant đã cấp; thao tác có side effect cần cổng tương ứng. Team thiếu người đủ điều kiện duyệt phải được cảnh báo từ
lúc compile, không âm thầm tự duyệt.

## Thay đổi UI

Không làm bốn ứng dụng rời rạc — mọi người dùng chung dữ liệu và timeline, hiển thị theo công việc và quyền:

- **Quản trị → Thành viên & quyền:** chọn scope, gán role, ma trận quyền, nguồn cấp quyền, preview ảnh hưởng, kiểm tra quyền của một thành
  viên và audit (H7A đã có trang này tại `/team-access`).
- **Project → Nhóm làm việc**, **Công việc của tôi**, **Bảng công việc** (người + agent; trạng thái là projection từ coordinator, không tạo
  state machine cạnh tranh hay kéo cột để bypass gate), **Run Detail** (ai đang làm, chờ ai/quyền nào, lý do không có quyền, review đúng
  revision), **Harness** (cùng project/scope/identity, chỉ hiện tool được cấp, nút dừng theo quyền; không trở thành cổng phê duyệt vòng
  ngoài Run).
- Các góc nhìn BA/Developer/Tester/Admin là cùng trang project với ưu tiên khác nhau: requirement / triển khai / chất lượng / quản trị —
  không hardcode role để cấp quyền.

Project cộng tác khóa thao tác khi quyền đang tải hay lookup lỗi, có thông báo rõ để thử lại. Dùng revision/optimistic concurrency và edit
lock cho authoring; comment không thay thế approval, quyết định đóng băng hay test evidence.

## Các slice tiếp theo

### H7B — Workflow/Run dùng chung và phê duyệt theo trách nhiệm

- Lưu scope bền vững; migrate có chọn lọc plan/run/contract/artifact và event stream. Thay owner-only bằng actor-aware access, giữ
  provenance và tương thích dữ liệu cũ.
- Phê duyệt nghiệp vụ/kỹ thuật/kiểm thử/publish theo permission và revision; kiểm tra độc lập, chống stale decision/race. Candidate và suite
  có revision bất biến.
- UI: shared project, Run Detail cho cả team, hộp việc chờ duyệt, change request.
- **Đạt khi:** BA tạo đầu vào, Developer làm kế hoạch, Tester xem/đánh giá cùng run; người không đủ quyền không thể duyệt dù có URL hay là
  người tạo. Không dùng workflow live với adapter còn cố định owner.

### H7C — Agent delegation và broker thống nhất

- Agent/service principal, task grant ngắn hạn, manifest quyền plugin, per-tool check và thu hồi; không suy quyền từ model output, webhook
  hay callback. Nâng native Harness workflow adapter, sandbox, memory, Verify và GitHub broker để dùng cùng identity/project policy.
- UI: giao task cho agent, xem phạm vi/tool/ngân sách, provenance, dừng/thu hồi.
- **Đạt khi:** agent không lấy quyền người khác, không đọc project khác/secret, không tự approve, không publish sau revoke; retry/recovery
  không lặp side effect; policy nội bộ không cấp thêm quyền GitHub ngoài integration thật.

### H7D — Không gian cộng tác và kiểm chứng xuyên suốt

- Bảng công việc, task cho người/agent, bàn giao có cấu trúc, comment gắn revision, thông báo, góc nhìn theo trách nhiệm. Test hai project,
  bốn tài khoản người, agent riêng; chạy chuỗi BA → Developer + agent → Tester → người duyệt publish → orchestrator; UI E2E desktop/mobile;
  kiểm tra duplicate clicks, stale tab, membership revoke, nhiều reviewer, conflict source, restart và webhook.
- **Đạt khi:** cả team theo dõi và hoàn thành cùng công việc, có bằng chứng cho từng bước — không chỉ có menu role mà backend vẫn chạy bằng
  một tài khoản owner.

Mỗi slice có test allow/deny, migration và rollback riêng; không dồn kiểm thử bảo mật tới H7D. H7D kiểm chứng tích hợp, không thay thế các
test của H7A–H7C.

## Kiểm chứng H7A

Test dùng SQLite thật và HTTP ASGI; UI dùng React Query và response fixtures. Không gọi model, Docker, memory backend hay GitHub để chứng
minh phân quyền. Các ca gồm isolation, chống self-escalation, schema/role migration, unknown action, deny nhiều role, revision/race, audit
rollback, thu hồi giữa worker, chặn API key, owner override, danh sách/link public, scope flow giả và folder con, cùng các thao tác UI xác
nhận. Migration được thử cả trường hợp schema được tạo trước bằng metadata và trường hợp role trùng tên/ID; không chấp nhận role chưa xác
minh.

Kết quả kiểm tra ngày 16/10/2026:

| Kiểm tra | Kết quả |
| --- | --- |
| H7A + factory + guards + visibility prefilters + public access + API quản trị/lifecycle | 232 test backend đạt |
| Trang phân quyền và API client | 13 test đạt (2 suite) |
| Ruff trên các module H7A và các guard/list/public đã sửa | Đạt |
| Biome trên 4 file UI/client/test mới | Đạt |
| TypeScript semantic check cho page/client H7A | 0 lỗi trong phạm vi H7A |

Không coi đây là toàn bộ repository/build đã xanh: kiểm tra TypeScript còn 13 diagnostic ở dependency/source ngoài H7A; một số test
authorization cũ còn trỏ vào đường dẫn `base/langflow` không tồn tại trong cấu trúc repo hiện tại; chưa chạy E2E trình duyệt với database
triển khai thật. Không tự chạy migration hay gán quyền trên database người dùng đang dùng trong lượt triển khai source này. Chưa chứng minh
chạy chung nhiều role trên luồng Harness live — đó là acceptance của H7B/H7C, không phải H7A.

## Giả định và giới hạn

- Bắt đầu với một tổ chức, nhiều project; không xây multi-tenant/SSO/SCIM đầy đủ trong H7. Nếu dùng chức năng IdP đã có thì phải giữ
  provenance grant và kiểm tra revocation — không coi xóa manual grant là đã thu hồi mọi nguồn.
- Không cần broker/repository/token mới để lập kế hoạch hay làm H7A. Test live nhiều người và publish chỉ làm sau khi có tài khoản thử và
  xác nhận phù hợp.
- Không chạy migration quyền trên môi trường đang dùng trước khi preview mapping, sao lưu và xác định Admin bootstrap. Rollback giữ
  private/deny cho phần chưa xác minh; không tắt enforcement để chữa lỗi quyền.
- GitHub/backend memory vẫn cưỡng chế quyền riêng của chúng. ADLC chỉ sử dụng integration được cấp, không thay thế quyền của hệ thống bên
  ngoài.

Nguyên tắc quyền tối thiểu, deny-by-default, kiểm tra phía server và theo tài nguyên được đối chiếu với [OWASP Authorization Cheat
Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html); phân tách agent proposal khỏi authority, giới hạn
tool và ràng buộc approval vào action cụ thể được đối chiếu với [OWASP AI Agent Security Cheat
Sheet](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html).

## Nguồn tổng hợp

Tài liệu lõi này gộp và biên tập gọn từ hai file cũ trong `docs/` (đã tiếng Việt, hiện lưu trên nhánh git `agentHarness`, xem bằng `git show
agentHarness:docs/<file>`):

- `docs/adlc-team-roles-plan.md` — H7 — Team Collaboration & Access Control (15/10/2026; kế hoạch tổng H7A–H7D)
- `docs/harness-milestone-h7a.md` — H7A — Nền tảng quyền theo project và quản trị bốn role (16/10/2026; foundation đã triển khai)

Milestone trước: `harness-h6.md` (bằng chứng độc lập H6A–H6D); chuỗi H4–H5: `harness-h4-h5.md`.
