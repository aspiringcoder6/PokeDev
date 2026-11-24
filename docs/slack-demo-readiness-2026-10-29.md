# Kiểm chứng demo Slack → vAIPlatform, 29/10/2026

## Phạm vi

Mục tiêu là nghiệm thu hành trình sản phẩm dùng được với nhiều yêu cầu.
Kịch bản thống kê đoàn viên chỉ là ví dụ quay video, không phải một bản
triển khai tính năng BE thủ công. Kiểm tra giao diện desktop; không làm mobile.

Yêu cầu đã chốt: GET `/api/v1/youth-union-stats?year=2026`, đếm đang hoạt
động/đã rời theo đơn vị có quyền xem; lọc theo năm của `joinDate`, giữ schema;
thiếu/sai `year` trả 400; chỉ BE API và unit test, không sửa frontend.

## Cập nhật kiểm chứng lúc 21:21 GMT+7

- Máy đã khởi động lại lúc 19:17. Ứng dụng được mở lại; kiểm tra HTTP của
  `/health`, `/login`, JS và CSS đều trả 200. API đăng nhập bằng thông tin đã
  lưu thành công. Phiên trình duyệt sau khởi động lại có thể cần đăng nhập lại.
- Trang `3014667` hiện **phiên bản 9**, nội dung 140 ký tự là dòng thông báo
  đang cập nhật. Người dùng xác nhận đang chỉnh sửa và yêu cầu giữ nguyên.
  Không khôi phục bản 8, không gửi thêm lượt sửa vào trang này trong lúc chờ.
- vAIPlatform đọc được bản 9, hiển thị `CHANGED`, không có quyết định duyệt
  hoặc run. Lượt sửa `ag-095930-8f555e` vẫn `FAILED`; việc trang có phiên bản
  mới không bị nhận nhầm là lượt bot đã hoàn tất.
- Workloop và MCP đang truy cập được, Slack đã đăng ký. Cờ health
  `connector=false` thuộc bộ nhận webhook phụ; mã nguồn Workloop tắt bộ nhận
  này khi bot Socket Mode riêng xử lý hội thoại. Cờ đó không đủ để kết luận
  bot đang ngắt hoặc cần cài lại. Giao diện chỉ báo đã có cấu hình và yêu cầu
  kiểm chứng phản hồi bằng hội thoại thật.
- Main BE vẫn cùng commit `8300bb5024cd4f89563989cf4d3e32b4427fe7fa`
  đã chạy baseline, nên biên nhận 80 test/5 failure vẫn áp dụng cho source này.
- `deploy/start.ps1` dùng cấu hình đã lưu; chỉ cấu hình lại khi chưa có file
  hoặc gọi `-Reconfigure` lúc ứng dụng đã dừng. Lệnh kiểm tra lại không đổi
  `.env.remote` và không tạo server thứ hai. Cách mở nền dùng launcher cùng
  tài khoản, tách khỏi phiên công cụ, để ngắt phiên kiểm tra không dừng web.

Bằng chứng mới: `demo-readiness-document-3.json`,
`startup-saved-config-verification.json`, `be-source-head-verification.json`.
Chạy `deploy/verify_demo_readiness.py` bằng Python trong `.venv` để kiểm tra
lại; script chỉ đọc trạng thái, không duyệt, gửi tin hoặc khởi chạy agent.

## Kết quả hiện có

| Bước | Kết quả có bằng chứng | Giới hạn |
| --- | --- | --- |
| Đăng nhập vAIPlatform | Người dùng đã đăng nhập, giao diện `/work` và tệp JS tải được | Giữ database và khóa mã hóa khi khôi phục |
| Tiếp nhận tài liệu Slack | Hộp yêu cầu tự cập nhật; đã thấy 13 bản ghi lúc 17:43 | Bản ghi `generated` thiếu link chưa phải tài liệu thành công |
| Gắn project | Yêu cầu #3 gắn `admin/tcct-be-military-youth`, có chỉ dẫn joinDate/không sửa FE | Chưa duyệt bản tài liệu còn sai nghĩa của year |
| Góp ý từ web | Lưu biên nhận Spec thật; đối soát được thành công/lỗi, chặn thao tác trùng | Hai lượt sửa thật đều thất bại; v9 hiện do người dùng cập nhật, chưa tính là sửa thành công |
| Thông báo Slack | Có tin thật được đọc lại đúng bot/thread; nút mở đúng thông báo trên web | Tin mất ACK được giữ chưa xác nhận, không tự gửi lại |
| Bot tra cứu tiến độ | Báo cáo riêng đã đồng bộ trên Confluence, ràng buộc lifecycle/thread | Báo cáo #3 hiện chưa có run; không suy ra hoàn tất từ tài liệu |
| Môi trường BE | Java 21, thư viện riêng và biên dịch source/test chạy thật | 80 test: 5 failure, 0 error; chưa đạt baseline xanh |
| Vòng thực hiện đầy đủ | Cơ chế kế hoạch/task/HITL/test/bàn giao đã có trong sản phẩm | Chưa có lượt BE của yêu cầu #3 đi trọn đến API chạy + test + PR |

## Hội thoại và tài liệu dùng để đối chiếu

- Yêu cầu #3: <http://127.0.0.1:7861/work?view=requests&document=3>
- Thread gốc ở **#bug-report**, channel `C0CARF9SRKP`, thread
  `1793074062.301049`, lifecycle `lc-F9SRKP-4062301049`.
- [Mở đúng tin đã kiểm chứng từ API Slack](https://adlcfactory.slack.com/archives/C0CARF9SRKP/p1793265861825169?thread_ts=1793074062.301049&cid=C0CARF9SRKP).
- Bản yêu cầu Confluence `3014667`, phiên bản 8 đã lưu trước đó. Nội dung nguồn mà
  Workloop/MCP trả về dừng ở mục 4.1.2.2.4; mục lục có các phần phía sau
  nhưng phần thân nhận được chưa có. Giao diện không cắt đoạn cuối nguồn này.
- Yêu cầu #10 có tài liệu 26.003 ký tự nhưng còn khác nghĩa year đã chốt;
  không tự thay thế/duyệt cho #3. #13 chưa có link Confluence.

## Các điểm còn cản một video thành công từ đầu đến cuối

1. **Sửa tài liệu thật chưa thành công.** Lượt cũ `ag-033034-dbb664` lỗi.
   Lượt có biên nhận `ag-095930-8f555e` đọc trang thành công rồi nhận hai
   phản hồi rỗng, `outputTokens=0`, từ route `netmind / zai-org/GLM-5.3-Flash`.
   Hai lượt hội thoại ngắn và một phép thử công cụ chỉ đọc phản hồi ngắn
   vẫn chạy được cùng model. Chưa đủ bằng chứng quy lỗi cho toàn bộ kết nối
   Netmind, VPN hoặc quyền Confluence. Không gửi thêm lượt sửa mù hoặc dùng
   bản ghi `generated` để báo thành công. Hiện giữ nguyên bản 9 theo yêu cầu
   người dùng trong lúc nhóm hoàn thiện tài liệu.
2. **Baseline source BE còn 5 failure.** Biên nhận môi trường
   `3bd3feb7-ee78-48f7-8a59-ba69661d7873`, commit source
   `8300bb5024cd4f89563989cf4d3e32b4427fe7fa`. Có lỗi so sánh enum/số trong
   `DefenseDiplomacyServiceCalculateTest` và kỳ vọng `createdBy` trong
   `YouthUnionMapperTest`. Log là nguồn đầy đủ cho các failure còn lại;
   không bỏ test hoặc đổi nghiệp vụ để tạo màn hình xanh giả.
3. **Cần nghiệm thu một run BE thật.** Sau khi tài liệu chính xác được xem
   và duyệt: lập kế hoạch, duyệt task/phạm vi, thực hiện, trả lời một điểm
   cần người xử lý, xem test/diff/PR và hỏi tiến độ trong đúng thread Slack.
   Những run cũ của project khác không thay thế bằng chứng này.
4. **Chưa có API preview với database và phân quyền thật.** Unit test khác
   với chứng minh API khởi động, trả 200/400 và giới hạn dữ liệu theo quyền.
   Cần cấu hình dữ liệu thử tách biệt và nghiệm thu riêng trước khi quay đoạn đó.
5. **Tài liệu dài cần chia phạm vi.** Đọc được tối đa 60.000 ký tự nhưng
   tổng yêu cầu đưa vào một kế hoạch hiện giới hạn 20.000 theo contract.
   Không cắt âm thầm hoặc bấm duyệt bản dài rồi coi đã chạy.

## Trình tự quay sau khi gỡ các điểm cản

1. Gửi yêu cầu mới trong một thread Slack với đúng quy tắc joinDate.
2. Mở hộp yêu cầu trên vAIPlatform, chờ tài liệu tự xuất hiện; không nhập link tay.
3. Gắn project BE, đọc phiên bản, gửi một góp ý cụ thể trên web; quay phản hồi
   Slack và phiên bản Confluence mới. Xem lại rồi duyệt tài liệu trên web.
4. Lập kế hoạch, xem sơ đồ task và phạm vi BE/test; duyệt thực hiện.
5. Theo dõi trạng thái task và vòng review; xử lý câu hỏi/cổng duyệt ngay trên web.
6. Mở kết quả test, API thử và diff/PR; đối chiếu cùng run ID.
7. Quay thông báo bot chủ động, hỏi tiến độ trong thread gốc, mở link về cùng run.

## Bằng chứng và khôi phục

Thư mục `adlc-flow/data/slack-actions-check/`:

- `verified-slack-message.json`: đã đọc lại tin thật, đúng bot/thread, không còn trang tiếp theo.
- `tracked-revision-command-3.json`, `tracked-revision-result-3.json`: thao tác và biên nhận sửa tài liệu.
- `spec-session-details.json`: nhật ký được lọc của đúng invocation, không khởi chạy agent mới.
- `model-connection-check.json`, `model-tool-connection-check.json`: chẩn đoán chỉ đọc cùng model.
- `be-current-baseline.json`: biên nhận biên dịch/test thật, trạng thái `FAILED` được giữ nguyên.
- `ui-restored-verification.json`: trang và assets trả về sau khởi động lại.
- `slack-notice-proof.jpg`: ảnh thông báo thật trong thread Slack gốc lúc kiểm chứng.

58 kiểm thử backend của intake/revision/progress/Slack đã qua, gồm lỗi mạng,
gửi trùng, quyền, nguồn thay đổi và đồng thời sửa trang. 19 kiểm thử giao diện
và bản build production trước đó đã qua. Chưa tuyên bố toàn bộ kiểm tra kiểu
của repo đạt. Bộ kiểm thử giả lập không thay bằng chứng Slack/Confluence thật.

Giữ database, source, cấu hình kín và khóa mã hóa; không đưa token vào Git.
Build frontend qua `deploy/build_frontend.ps1`: build trong thư mục staging,
kiểm tra assets rồi thay `index.html` cuối cùng, giữ assets cũ cho tab đang mở.
`deploy/test_frontend_publication.ps1` đã kiểm tra xuất bản thiếu assets không
làm hỏng bản đang phục vụ.

VPN hiện hoạt động bình thường. Nếu chỉ Harness/Gitea còn truy cập được mà
Slack/Confluence timeout, kiểm tra kết nối trước khi thay token; không tự sửa
route VPN. Ghi chú này đã lưu trong `AGENTS.md`.
