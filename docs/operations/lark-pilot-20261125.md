# Cấu hình pilot Lark cho PokeDev

Ngày 25/11/2026. Bot PokeDev 0.1.0 đã phát hành cho một thành viên pilot. WebSocket được Developer Console xác nhận Connected; DM thật đã vào journal và một biên nhận từ bot đã xuất hiện trong cùng cuộc trò chuyện trên Lark Web. Đây là kiểm chứng transport; DM chưa được chuyển thành hồ sơ intake và chưa gọi agent.

## Cấu hình đã áp dụng

Custom App riêng tên PokeDev, bật Bot. Phạm vi sử dụng là Selected members với một người được chọn; không mở cho toàn bộ tenant. Phiên bản 0.1.0 có trạng thái Released và review result Approved.

Ba quyền tenant đã được người dùng xác nhận và thêm vào app:

| Quyền | Phạm vi |
|---|---|
| `im:message.p2p_msg:readonly` | Nhận DM gửi tới bot |
| `im:message.group_at_msg:readonly` | Nhận @mention trong nhóm |
| `im:message:send_as_bot` | Gửi tin dưới tên bot |

Chỉ đăng ký `im.message.receive_v1` bằng tenant token, nhận qua persistent connection. Chưa xin quyền đọc mọi tin nhắn trong nhóm hoặc quyền Doc/Wiki/Base. Việc cấu hình card callback và thử reply không @mention vẫn thuộc phần kiểm chứng tiếp theo.

Credential được lấy từ app PokeDev mới và lưu trong `.env` của PokeDev, được Git bỏ qua. Không sao chép credential hoặc runtime của ADLC. App Secret không xuất hiện trong báo cáo, ảnh minh chứng hay log thử.

## Chạy bộ nhận thử

Từ thư mục gốc repository, với môi trường SDK đã cài theo [hướng dẫn connector](../../services/lark-connector/README.md):

```powershell
services/lark-connector/.venv/Scripts/python.exe services/lark-connector/probe.py --listen
```

Probe chỉ nhận và commit vào `adlc-flow/data/local/lark-probe/events.sqlite3` trước khi callback trả về. Không tự trả lời, gọi agent hoặc tạo hồ sơ intake. Dừng bằng Ctrl+C; journal được giữ để đối soát. Kết nối là outbound WebSocket tới LarkSuite quốc tế; không cấu hình cổng public, tunnel hoặc đổi VPN.

## Kết quả và phần đang chờ

| Bài kiểm tra | Kết quả |
|---|---|
| Credential riêng của app mới và khởi động probe | Đạt |
| Xác minh WebSocket từ console | Connected |
| Lưu mode persistent connection | Đạt |
| Thêm sự kiện `im.message.receive_v1` | Đạt |
| Phát hành 0.1.0 trong phạm vi một thành viên | Released / Approved |
| DM thật vào journal | Đạt: một event `im.message.receive_v1`, text/p2p, sender user, đúng app và nội dung thử |
| Gửi biên nhận vào DM thử | Đạt: provider trả thành công, chat ID khớp nguồn, trạng thái DELIVERED; đã đối chiếu Lark Web |
| @mention, card/form, tài liệu và redelivery | Chưa chạy |

Người dùng đã gửi "Kiểm tra kết nối PokeDev". Journal ghi nhận lúc 23:25:48 ngày 25/11/2026 (Asia/Saigon), có event ID, tenant, message ID và chat ID. Callback báo thời gian ghi journal 15 ms; con số này không phải độ trễ ACK hoặc thời gian phản hồi đầu cuối. Chưa mô phỏng redelivery từ server Lark trong bài thử live này.

Biên nhận thử được gọi riêng sau khi người dùng xác nhận đã gửi tin, không phải phản hồi tự động của probe. API reply trả thành công lúc 23:27:53 cùng ngày, với message ID và chat ID đúng DM nguồn. Trước khi gửi đã lưu send intent và UUID ổn định; sau thành công lưu receipt DELIVERED trong `adlc-flow/data/local/lark-probe/test-dm-receipt.json`. Không gửi lại hoặc tự retry một kết quả chưa xác nhận. Tin của bot đã được nhìn thấy trong Lark Web.

Biên nhận chỉ xác nhận kết nối và nêu rõ vòng hỏi–đáp với agent sẽ được nối ở bước tiếp theo. Không dùng kết quả thử này làm bằng chứng LI-02 hoặc LI-04 đã hoàn tất.

Ảnh minh chứng local nằm trong `adlc-flow/data/local/evidence/`: `lark-bot-scopes.jpg`, `lark-pilot-released.jpg` và `lark-dm-roundtrip.jpg`. Ảnh, journal và receipt thử không được đưa vào Git.
