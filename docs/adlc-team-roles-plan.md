# H7 — Team Collaboration & Access Control

Ngày soạn: 15/10/2026. Trạng thái: **H7A và H7B đã có source; chưa áp dụng quyền mới vào database đang chạy**.

Cập nhật 16/10/2026: đã triển khai foundation H7A trong source; xem
[phạm vi, UI, migration và cách vận hành](harness-milestone-h7a.md).
Cập nhật 18/10/2026: đã triển khai H7B — scope dữ liệu dùng chung, authoring,
review độc lập, import lịch sử có xác nhận và UI cho team; xem
[phạm vi và hướng dẫn H7B](harness-milestone-h7b.md).
Chưa áp dụng quyền mới vào dữ liệu đang dùng; H7C–H7D vẫn là kế hoạch.
Shared run mới chỉ được chuẩn bị, không gọi agent hoặc merge/push GitHub.

## 1. Kết quả cần đạt

ADLC trở thành không gian làm việc chung của con người và agent trong cùng một
project: có yêu cầu, contract, công việc được giao, kế hoạch, thực thi, bằng chứng,
phê duyệt và kết quả bàn giao. Không tạo một hệ thống task riêng bên cạnh workflow.

Bốn role trên giao diện: **Admin, Developer, Business Analyst, Tester**. Admin
quyết định ai được làm gì, với tài nguyên nào và trong project nào. Agent có danh
tính thực thi riêng, nhận phạm vi giao việc cụ thể; không đóng giả tài khoản người.

Phạm vi giai đoạn này là phân quyền và cộng tác. Nó không tự cấp quyền GitHub,
không mở quyền ghi `main`, không đổi provider/model hoặc chạy workflow trả phí.

## 2. Nền tảng hiện có và khoảng trống

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

- `LangflowAuthorizationService` mặc định là pass-through. Chỉ bật cờ AUTHZ không
  chứng minh đã có policy enforcement. Cần xác minh provider được đăng ký và có
  kiểm tra allow/deny thực tế. Đây là nhận xét về source mặc định, không phải kết
  luận rằng môi trường đang chạy đã đăng ký hoặc chưa đăng ký một plugin khác.
- Guard hiện có owner override; UI có fallback cho phép khi thiếu dữ liệu quyền.
  Hai hành vi tương thích legacy này không được trở thành đường vòng trong project
  đã bật cộng tác. Backend là nơi quyết định, không phải việc ẩn nút trên UI.

## 3. Mô hình quyền đề xuất

### 3.1. Role + project + hành động + điều kiện

Role là preset dễ hiểu, không phải thứ bậc `BA < Tester < Developer < Admin`.
Một người có thể là Developer ở project A và Tester ở project B.

Quyết định truy cập gồm:

1. Danh tính đã xác thực và loại actor: USER, AGENT hoặc SERVICE.
2. Membership còn hiệu lực trong project chứa tài nguyên.
3. Quyền hành động được cấp cho role ở đúng scope.
4. Điều kiện của tài nguyên, contract và approval: revision, digest, trạng thái,
   người soạn, người duyệt, target repository/branch và môi trường.

Quyền từ nhiều role được hợp nhất, sau đó áp dụng deny và các ràng buộc bắt buộc.
Có hai role không cho phép một người vượt chốt không tự duyệt công việc của mình.

### 3.2. Hai phạm vi quản trị, vẫn chỉ bốn tên role

- Admin toàn hệ thống quản lý người dùng, project và chính sách nền tảng.
- Admin project chỉ quản lý thành viên, quyền và kết nối trong project được giao;
  không được tự cấp Admin toàn hệ thống hoặc can thiệp project khác.
- `is_superuser` hiện tại là cơ chế bootstrap/vận hành, không tự động đồng nghĩa
  với mọi quyền nghiệp vụ của mọi project. Không dùng bypass superuser để hợp
  thức hóa phê duyệt contract, sửa bằng chứng hoặc publish ngoài phạm vi.
- Cần chốt người bootstrap và bảo vệ Admin cuối cùng trước khi bật enforcement;
  đây không phải một hành động cấp quyền được thực hiện bởi tài liệu này.

### 3.3. Admin điều chỉnh được gì

Màn hình ma trận quyền cho từng project, gồm:

- Thành viên nào nhận role nào.
- Với mỗi phần: xem, tạo/sửa bản nháp, gửi duyệt, duyệt, thực thi, quản trị.
- Package/plugin/tool nào được dùng; loại sandbox, nguồn memory, repository,
  môi trường và ngân sách thực thi nào được phép.
- Ai đủ điều kiện nhận cổng duyệt nghiệp vụ, kỹ thuật, kiểm thử, publish.

Admin xem trước thay đổi, danh sách người bị ảnh hưởng và quyền hiệu lực trước
khi lưu. Mỗi lần lưu tạo revision và audit. Không chỉ lưu checkbox ở frontend.

Các preset ADLC dùng định danh riêng, ví dụ `adlc.business_analyst`, tránh thay
nghĩa các role legacy. Preset gốc có phiên bản; tùy chỉnh theo scope được lưu riêng
và vẫn được tính bởi cùng dịch vụ authorization, không tạo policy engine thứ hai.

Admin không được tắt các bất biến: không đọc/export secret thô, không sửa bằng
chứng Verify, không sửa contract đã khóa tại chỗ, không cho agent ký phê duyệt
thay người, không bỏ chốt phê duyệt bắt buộc bằng cách cấp quyền rộng hơn.

## 4. Ma trận mặc định để bắt đầu

Đây là baseline đề xuất, Admin có thể thu hẹp hoặc mở rộng trong giới hạn an toàn.
Mọi quyền trong bảng chỉ có hiệu lực ở project được giao và với dữ liệu được phép xem.

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

- Admin là người quản trị quyền; không mặc định là reviewer nghiệp vụ, kỹ thuật
  và kiểm thử cùng lúc. Quyền thực hiện các việc đó phải rõ ràng.
- Duyệt nghiệp vụ khác duyệt kế hoạch thực thi; duyệt Verify khác sửa kết quả
  Verify. Người chạy máy kiểm thử cũng không được tự ghi report PASS.
- Tester chỉ sửa test trước khi suite được đóng băng hoặc tạo revision mới.
  Agent triển khai không được sửa protected tests rồi dùng chúng để tự chứng nhận.
- Với code được agent viết, người giao/điều khiển task là bên chịu trách nhiệm
  author; không coi agent ID khác user ID là đã đáp ứng tính độc lập của reviewer.
- Khởi chạy template nghiệp vụ không đồng nghĩa được chạy package coding tùy ý.
  Compiler và dispatcher cùng kiểm tra package/capability được cấp.
- Merge vào nhánh bảo vệ/production là quyền và policy riêng, mặc định tắt trong
  giai đoạn này. Luồng GitHub hiện tại vẫn chỉ publish nhánh làm việc mới.

## 5. Luồng cộng tác mục tiêu

1. **Admin thiết lập project:** thêm thành viên, chọn bốn role và cấp kết nối
   repository, memory, sandbox, testing. Chọn người đủ quyền duyệt theo từng cổng.
2. **BA chuẩn bị đầu vào:** soạn requirement/contract, acceptance criteria và
   gửi duyệt. Revision được khóa; thay đổi sau đó là change request, không ghi đè.
3. **Developer lập kế hoạch:** tạo workflow từ contract được duyệt; orchestrator
   chia task. Người đủ quyền duyệt kế hoạch kỹ thuật và phạm vi thực thi.
4. **Giao cho người hoặc agent:** task có assignee, người giao, brief, phạm vi,
   dependency và bằng chứng cần bàn giao. Agent tự soạn task brief nhưng không tự
   mở rộng contract. Người làm thủ công cũng bàn giao candidate theo cùng chuẩn.
5. **Thực hiện và kiểm tra:** Developer/agent tạo candidate trong nhánh/checkout
   riêng. Tester dùng suite đã khóa để tái hiện và đối chiếu. Hệ thống lưu report,
   môi trường, exit status, revision và digest; kết luận không dựa vào lời agent.
6. **Nghiệm thu và publish:** Tester xác nhận chất lượng; BA xác nhận nghiệp vụ
   nếu contract yêu cầu; người có grant publish duyệt đúng candidate/SHA/target.
   Orchestrator mới được dùng broker để publish và lưu receipt.
7. **Hoàn thành:** mọi người xem cùng kết quả, quyết định, lỗi và lịch sử. Không
   đóng task thành công chỉ vì có một comment nói đã làm xong.

Các cổng áp dụng theo risk/policy đã khóa trước khi chạy; không thêm một loạt
phê duyệt thủ công vào mọi tác vụ nhỏ. Task read-only ít rủi ro có thể tự chạy
trong grant đã cấp; thao tác có side effect cần cổng tương ứng. Team thiếu người
đủ điều kiện duyệt phải được cảnh báo từ lúc compile, không âm thầm tự duyệt.

## 6. Agent và plugin hoạt động dưới quyền nào

Không cấp một trong bốn role người dùng cho agent rồi cho dùng toàn bộ role đó.
Mỗi task có delegation do control plane cấp, gồm tối thiểu:

- Principal agent/service, người hoặc service được ủy quyền giao task, project,
  run/task/attempt, thời hạn và trạng thái thu hồi.
- Contract/plan/package digest; action và tool được phép.
- Repository/branch/path, memory namespace và nguồn, sandbox/network profile,
  testing target, ngân sách và giới hạn side effect.
- Approval reference khi action yêu cầu; action, tham số và kết quả được duyệt
  phải khớp tại thời điểm sử dụng.

Quyền thực thi là giao của **delegation còn hiệu lực**, **quyền hiện tại của bên
ủy quyền**, **policy project**, **phạm vi plan/contract đã khóa**, và **giới hạn
runtime**. Người khởi chạy workflow không tự động là bên ủy quyền cho mọi task:
BA có thể khởi tạo một luồng rồi Developer cấp delegation triển khai ở cổng sau.

Các chốt bắt buộc:

- Agent chỉ đề xuất; quyết định approve/reject nghiệp vụ lấy từ người đăng nhập
  đủ quyền. API key/agent callback không thay thế chữ ký người.
- Plugin khai báo permission manifest; core xác minh và thực thi. Có thể thay
  policy provider bằng plugin nhưng không được tháo plugin để mọi request thành allow.
- Mỗi tool call đi qua broker/guard. Không cho raw shell/network/credential tạo
  đường vòng vượt grant. Sandbox và egress cần cưỡng chế thực tế, không chỉ prompt.
- GitHub credential ở publisher broker; agent tạo candidate/commit, không nhận
  token push và không có tool merge/push trực tiếp.
- Memory lọc theo scope và quyền dữ liệu ngay tại retrieval; không lấy toàn bộ
  context rồi chỉ lọc khi render UI. Memory không phải nguồn cấp quyền hay Verify.
- Webhook xác thực nguồn, không tự cấp quyền: repository phải được map vào
  project và trigger đã cấp trước; payload issue/label không được sửa policy.
- Thu hồi membership/grant chặn dispatch và action tiếp theo. Cố gắng hủy công
  việc đang chạy; không tuyên bố đảo ngược được side effect đã gửi tới bên ngoài.
  Nếu kết quả chưa chắc chắn, reconcile receipt thay vì tự publish lại.

## 7. Cách tích hợp vào kiến trúc hiện có

### 7.1. Một nguồn quyết định quyền

Mở rộng authorization port hiện có với ngữ cảnh project/resource đáng tin cậy.
Điểm kiểm tra được dùng thống nhất ở API, compiler, coordinator, scheduler,
plugin/tool broker, callback và publisher. UI nhận quyền hiệu lực từ cùng policy.

Action catalog bổ sung các nhóm nghiệp vụ, ví dụ:

- `requirement:write`, `contract:submit`, `contract:approve`
- `flow:write`, `flow:execute`, `plan:approve`
- `task:assign`, `task:submit`, `candidate:review`
- `verification:execute`, `verification:accept`
- `publication:approve`, `publication:execute`
- `integration:use`, `integration:manage`, `membership:manage`, `policy:manage`

Catalog có schema, mô tả, resource type và điểm enforce; không nhận action string
tùy ý từ plugin hoặc gán quyền chỉ theo URL/menu. Giữ aliases của API legacy ở
adapter để không có hai cách diễn giải cùng một action.

Tái sử dụng role/assignment/team/share/audit hiện có. Bổ sung có migration những
record thực sự thiếu: policy revision theo scope, principal/delegation của agent,
resource scope binding, assignee/participant và approval requirement có cấu trúc.
PackageAccessPolicy trở thành adapter của nguồn policy này, không còn bộ grant
process-local riêng cho project cộng tác.

### 7.2. Chuyển từ owner sang project mà không impersonate

- Run mới lưu `project_id`, người tạo, initiator và scope binding bất biến từ
  nguồn đã xác minh. Không lấy `project_id`/`owner_id` trong payload làm bằng chứng.
- `owner_id` cũ vẫn dùng cho storage/provenance tương thích, không tự cấp mọi
  quyền trong project cộng tác. Không truyền owner của người khác vào service
  thay cho identity của actor để vượt các hàm `_owned_*`.
- Run, plan, contract, candidate, source patch, test evidence, interaction,
  download và event stream đều phải có scope và check tương ứng. Chỉ sửa API list
  run là chưa đủ. Lọc pagination/search/count ở phía server, tránh lộ metadata.
- Membership bị thu hồi thì mất quyền đọc project, kể cả link cũ; dữ liệu/audit
  vẫn được giữ theo retention. Thu hồi quyền execute đơn lẻ không tự xóa quyền
  read nếu thành viên vẫn còn grant read.
- Không suy scope của run cũ từ folder hiện tại của flow: flow có thể đã được
  chuyển project. Nếu không xác minh được lịch sử, giữ private đến khi được migrate.

### 7.3. Approval và thay đổi policy

`required_role: maintainer` hiện tại được chuyển theo phiên bản sang requirement
quyền cụ thể, kèm stage, project, điều kiện độc lập, digest và expiry. Server tra
quyền, không tin role hay `approved=true` do client gửi. Tính độc lập là trên
user/nhóm chịu trách nhiệm của candidate, không chỉ so sánh role name.

Quyết định ghi người thực sự duyệt, policy revision, tài nguyên/revision/digest và
action. Trước side effect, recheck quyền hiện tại, trạng thái tài nguyên và consume
approval/intent nguyên tử để chống race/replay. Audit/ledger không ghi được thì
không phát lệnh rủi ro ra ngoài.

Policy rộng hơn không mở rộng plan đã khóa. Policy hẹp hơn có thể chặn run đang
chờ. Contract/candidate/target thay đổi phải tạo revision và phê duyệt mới; không
tái sử dụng quyết định cho digest khác. Hai reviewer cùng bấm chỉ có một quyết
định thắng; conflict trả lại trạng thái mới thay vì chạy hai lần.

## 8. Thay đổi UI

Không làm bốn ứng dụng rời rạc. Mọi người dùng chung dữ liệu và timeline, với
mặc định hiển thị theo công việc và quyền:

- **Quản trị → Thành viên & quyền:** chọn scope, gán role, ma trận quyền, nguồn
  cấp quyền, preview ảnh hưởng, kiểm tra quyền của một thành viên và audit.
- **Project → Nhóm làm việc:** thành viên, người phụ trách, kết nối được phép,
  chính sách duyệt và giới hạn agent.
- **Công việc của tôi:** task được giao, việc chờ mình duyệt, request cần phản hồi.
- **Bảng công việc:** cả người và agent; assignee, dependency, brief, candidate,
  Verify và bàn giao. Trạng thái là projection từ coordinator, không tạo state
  machine cạnh tranh hoặc thao tác kéo cột để bypass gate.
- **Run Detail:** ai đang làm, đang chờ role/người nào, lý do không có quyền, dữ
  liệu review đúng revision và các quyết định đã lưu.
- **Harness:** cùng project/scope/identity, chỉ hiện tool được cấp, nút dừng theo
  quyền; không trở thành cổng phê duyệt vòng ngoài Run.
- **Các góc nhìn BA/Developer/Tester/Admin:** cùng trang project, ưu tiên
  requirement / triển khai / chất lượng / quản trị; không hardcode role để cấp quyền.

Project cộng tác khóa thao tác khi quyền đang tải hoặc lookup lỗi, có thông báo
rõ để thử lại. Dùng revision/optimistic concurrency và edit lock cho authoring;
comment không thay thế approval, quyết định đóng băng hoặc test evidence.

## 9. Các slice triển khai

### H7A — Nền tảng quyền và quản trị

- Chốt action catalog, bốn preset, scope, deny/override semantics và bootstrap.
- Cài policy enforcement thật qua port hiện có; team mode không khởi động với
  pass-through hoặc thiếu policy store. Giữ legacy private mode tách biệt rõ.
- API quản trị có transaction, audit, kiểm tra không tự nâng quyền/vượt scope,
  không xóa Admin cuối cùng; policy revision và cache invalidation đa worker.
- UI đầu tiên: thành viên, bốn role, ma trận quyền và quyền hiệu lực.
- **Đạt khi:** hai project cách ly; cả UI và gọi API trực tiếp đều tuân policy;
  lookup lỗi không mở quyền. Chưa mở shared live execution khi các cổng sau chưa có.

### H7B — Workflow/Run dùng chung và phê duyệt theo trách nhiệm

- Lưu scope bền vững; migrate có chọn lọc plan/run/contract/artifact và event stream.
- Thay owner-only bằng actor-aware access; giữ provenance và tương thích dữ liệu cũ.
- Phê duyệt nghiệp vụ/kỹ thuật/kiểm thử theo permission và revision; kiểm
  tra độc lập, chống stale decision/race. Candidate và suite có revision bất biến.
- Publication approval gắn broker/delegation được giữ ở H7C theo action catalog;
  H7B không cấp một quyết định có thể dùng để push qua adapter owner-only cũ.
- UI: shared project, Run Detail cho cả team, hộp việc chờ duyệt, change request.
- **Đạt khi:** BA tạo đầu vào, Developer làm kế hoạch, Tester xem/đánh giá cùng run;
  người không đủ quyền không thể duyệt dù có URL hoặc là người tạo. Không dùng
  workflow live với adapter còn cố định owner cho tới khi được nâng cấp tương ứng.

### H7C — Agent delegation và broker thống nhất

- Agent/service principal, task grant ngắn hạn, manifest quyền plugin, per-tool
  check và thu hồi. Không suy quyền từ model output, webhook hoặc callback.
- Nâng native Harness workflow adapter, sandbox, memory, Verify và GitHub broker
  để dùng cùng identity/project policy. Không bỏ pin owner cũ chỉ để chạy đa user.
- Mở publication approval theo actor/project, khóa đúng commit/target và receipt;
  không tái dùng các quyết định authoring H7B làm quyền push.
- UI: giao task cho agent, xem phạm vi/tool/ngân sách, provenance, dừng/thu hồi.
- **Đạt khi:** agent không lấy quyền người khác, không đọc project khác/secret,
  không tự approve và không publish sau revoke. Tác vụ retry/recovery không lặp
  side effect. Policy nội bộ không cấp thêm quyền GitHub ngoài integration thật.

### H7D — Không gian cộng tác và kiểm chứng xuyên suốt

- Bảng công việc, task cho người/agent, bàn giao có cấu trúc, comment gắn revision,
  thông báo và các góc nhìn theo trách nhiệm.
- Test hai project, bốn tài khoản người, agent riêng; chạy chuỗi BA → Developer
  + agent → Tester → người duyệt publish → orchestrator, kiểm tra remote receipt.
- UI E2E desktop/mobile; kiểm tra duplicate clicks, stale tab, membership revoke,
  nhiều reviewer, conflict source, restart và luồng webhook đã cấp.
- **Đạt khi:** cả team theo dõi và hoàn thành cùng công việc, có bằng chứng cho
  từng bước; không chỉ có menu role mà backend vẫn chạy bằng một tài khoản owner.

Mỗi slice có test allow/deny, migration và rollback riêng; không dồn kiểm thử bảo
mật tới H7D. H7D kiểm chứng tích hợp, không thay thế các test của H7A–H7C.

## 10. Bộ tiêu chí nghiệm thu tối thiểu

1. Admin cấp/thu hồi quyền đúng project; không thể sửa quyền project ngoài scope.
2. BA không đổi graph/payload để chạy coding hoặc tự publish khi chưa được cấp.
3. Developer không đổi contract/suite đã khóa hoặc tự duyệt phần triển khai mình chịu trách nhiệm.
4. Tester không sửa production source/secret; report Verify không sửa được kể cả bởi Admin.
5. Một người nhiều role vẫn bị ràng buộc độc lập; không còn reviewer hợp lệ thì
   compile/approval báo rõ, không mở cơ chế tự duyệt.
6. Không vượt quyền bằng API trực tiếp, service call, artifact URL, event stream,
   MCP, interaction response, callback hoặc webhook.
7. Revoke có hiệu lực trên các worker và trước action mới; token cũ không giữ
   quyền vô hạn. Không replay publish sau restart hoặc intent không rõ kết quả.
8. Sửa revision/digest/target làm phê duyệt cũ không còn dùng được.
9. Agent và người cùng có task brief/candidate/evidence; action ghi đúng actor,
   người giao, người duyệt, policy revision và receipt, không log secret.
10. Luồng private cũ vẫn hoạt động theo chế độ tương thích đã xác định; không
    tự chia sẻ lịch sử, memory hoặc source của người tạo cho toàn team.

## 11. Giả định và giới hạn

- Bắt đầu với một tổ chức, nhiều project; không xây multi-tenant/SSO/SCIM đầy đủ
  trong H7. Nếu dùng các chức năng IdP đã có thì phải giữ provenance grant và
  kiểm tra revocation, không coi xóa manual grant là đã thu hồi mọi nguồn.
- Không cần broker/repository/token mới để lập kế hoạch hoặc làm H7A. Test live
  nhiều người và publish chỉ làm sau khi có tài khoản thử và xác nhận phù hợp.
- Không chạy migration quyền trên môi trường đang dùng trước khi preview mapping,
  sao lưu và xác định Admin bootstrap. Rollback giữ private/deny cho phần chưa
  xác minh; không tắt enforcement để chữa lỗi quyền.
- GitHub/backend memory vẫn cưỡng chế quyền riêng của chúng. ADLC chỉ sử dụng
  integration được cấp, không thay thế quyền của hệ thống bên ngoài.

## 12. Nguồn đối chiếu

Đề xuất riêng cho ADLC ở trên dựa trên kiểm tra source hiện tại. Các nguyên tắc
quyền tối thiểu, deny-by-default, kiểm tra phía server và theo tài nguyên được
đối chiếu với [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html).
Phân tách agent proposal khỏi authority, giới hạn tool và ràng buộc approval vào
action cụ thể được đối chiếu với [OWASP AI Agent Security](https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html).
