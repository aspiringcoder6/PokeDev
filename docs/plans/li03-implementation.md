# LI-03: nhóm, thread và định tuyến lời bổ sung

Ngày: 26/11/2026. Baseline đã kiểm chứng: `8fc0426` (LI-02). Đây là phần tiếp theo của kế hoạch Lark hiện có, không tạo một framework đặc tả mới. Tài liệu `inputTakingNotes.md` tiếp tục là nguồn thiết kế; chỉ dùng các nguyên tắc nguồn gốc, quyền và ranh giới tiếp nhận/readiness.

## Hành vi cần đạt

- DM gốc vẫn tạo hồ sơ riêng. Reply vào tin gốc hoặc biên nhận đã theo dõi chỉ bổ sung vào đúng hồ sơ đó.
- Nhóm phải được cấu hình tường minh với một project hoặc bản nháp chưa gắn project. Chỉ người dùng đã liên kết được tạo/bổ sung; không tự cấp quyền cho thành viên nhóm.
- Giữ riêng message/root/parent/thread ID native. Hai thread trong một nhóm không dùng chung hồ sơ; không chọn hồ sơ mới nhất để đoán đích.
- Nếu đích thiếu hoặc mâu thuẫn, yêu cầu chọn bằng `/intake <UUID> <nội dung>`. Lệnh này là thao tác liên kết tường minh, vẫn kiểm tra owner và quyền project. `/new <nội dung>` tạo hồ sơ mới khi người dùng chủ động yêu cầu.
- Lời bổ sung được lưu như nguồn hội thoại, hiển thị trong hồ sơ riêng trên web; chưa tự sửa brief, trả lời câu hỏi agent hay phê duyệt yêu cầu.
- Biên nhận nhóm chỉ xác nhận thao tác, không trích nội dung hoặc liệt kê hồ sơ/project riêng. Mặc định yêu cầu @bot khi reply; chỉ bật nhận không @ theo từng nhóm sau khi thấy event thật.

## Phạm vi ảnh hưởng trước thay đổi

| Khu vực | Thay đổi và bằng chứng phụ thuộc |
|---|---|
| Contract | Thêm module wire v2 trong package dùng chung; giữ model/endpoint v1. Connector và backend đang import cùng `pokedev_lark_contracts` |
| Database | Thêm binding hội thoại, alias message và route outbox; migration nối LI-02, backfill DM cũ từ inbox/request/outbox đã có |
| Backend | API v2, giải quyết root/parent, lựa chọn UUID tường minh, kiểm tra quyền ở ingress và claim; API đọc nguồn hội thoại theo `intake.owned` |
| Connector | Normalizer v2, mention đúng bot ID, giữ thread ID, journal hỗ trợ cả v1/v2, gửi reply trong thread nhóm; không gọi model |
| Desktop | Dòng thời gian nguồn hội thoại và lệnh chọn đúng hồ sơ; các đường tạo/sửa LI-01 giữ hợp đồng |
| Deployment | Feature flag hội thoại và nhóm tắt mặc định, allowlist nhóm/project, bot open ID; cài backend trước connector |
| Documentation | ADR 0024, runbook LI-03, trạng thái slice và regression ledger |

## Kiểm chứng có ý nghĩa

- LI03-01: hai root/two thread trong cùng chat tạo hai hồ sơ; reply chỉ xuất hiện dưới đúng hồ sơ, kể cả reply tới biên nhận bot.
- LI03-02: root/parent trỏ khác hồ sơ hoặc reply ngoài binding không được đoán; chọn UUID được kiểm tra quyền, không liên kết chéo ngoài ý muốn.
- LI03-03: group chưa cấu hình, mention người/bot khác, tin bot, actor chưa liên kết/khác owner, project bị thu hồi và hồ sơ đã hủy không ghi lời bổ sung.
- LI03-04: chống lặp event/message, ghi inbox/binding/outbox nguyên tử, race đồng thời và receipt replay không tạo hai alias hoặc hai hồ sơ.
- LI03-05: v1 journal/receipt cũ tiếp tục đối soát; connector v1 không claim delivery dành cho v2. Không tự gửi lại tin chưa rõ kết quả.
- LI03-06: migration SQLite và PostgreSQL, adoption schema và backfill cả message gốc/biên nhận LI-02. Không sửa nội dung/historic receipt cũ.
- LI03-07: web chỉ chủ hồ sơ có quyền project đọc được nguồn; hiển thị reply dưới đúng request, đổi request không giữ tin cũ.
- LI03-08: thử thật hai root nhóm, reply có @, reply tới biên nhận bot, DM reply và khả năng nhận không @. Chỉ công bố phần thực sự quan sát được.

Lệnh và các downstream cần chạy nằm trong [regression ledger](../REGRESSION.md). Không gọi model có phí trong bộ kiểm tra.

## Triển khai, tương thích và rollback

Triển khai contract/backend/migration trước, sau đó connector v2; bật hội thoại DM riêng và nhóm đã được người dùng cho phép. Endpoint v1 và payload đã ghi trong journal giữ nguyên. Tắt flag rồi khởi động lại backend/connector để dừng đường mới; giữ intake, nguồn, binding và receipt. Không downgrade bằng xóa lịch sử, không reset UNCONFIRMED thành PENDING. App image Docker cần build lại nếu chọn chạy Docker; pilot native dùng database độc lập của PokeDev.

Chưa xác minh trước triển khai: event nhóm/reply thật và hành vi không @ của tenant. Ba quyền pilot LI-02 chưa đồng nghĩa nhận mọi reply; không tự cấp thêm quyền đọc toàn bộ nhóm.

Quyết định: [ADR 0024](../adr/0024-explicit-lark-conversation-routing.md).

## Đối chiếu sau triển khai

Diff đúng các khu vực đã dự kiến: wire v2 riêng, ba model/migration mới, source routing/API, connector, desktop và tài liệu. Contract/endpoint v1 giữ nguyên; brief LI-01 không bị sửa bởi lời bổ sung. Không thêm phụ thuộc Workloop hoặc lời gọi agent/model. Input notes gốc không bị sửa.

Đã đạt 316 kiểm tra backend, 34 connector/probe, 12 UI, PostgreSQL và build. SQLite và PostgreSQL đều có bài thử backfill ID native, message gốc và biên nhận; native database thật cũng đã backfill thành công. Hai root nhóm và reply có @ đã qua pilot thật, bốn biên nhận nghiệp vụ nhóm đều DELIVERED. Trong DM thật, chọn hồ sơ bằng `/intake` và Reply vào biên nhận bot LI-02 đều APPENDED vào đúng hồ sơ cũ, hai biên nhận DELIVERED và không tạo hồ sơ mới. Browser hiển thị hai nguồn riêng của A/B và ba nguồn của DM; brief cả ba giữ revision 1. Reply không @ chưa có bằng chứng event được nhận và vẫn tắt; kiểm tra tự động còn bảo đảm rằng nếu bật thì chỉ reply có binding mới được nhận. Biên bản chi tiết và rollback: [runbook LI-03](../operations/lark-li03.md).
