# Phân loại issue và duyệt theo rủi ro

Tính năng A và B được người dùng duyệt ngày 26/10/2026. Phần giao diện tập trung vào máy tính. C và D trong bản đánh giá tích hợp vẫn là các đề xuất riêng.

## Cách dùng

Mở PokeDev, chọn project rồi vào **Issue Gitea**. Mỗi đề xuất có kết quả phân loại, lý do, mức rủi ro và lịch sử quyết định.

- **Đủ rõ để lập kế hoạch:** có thể chọn Lập kế hoạch, hoặc để chính sách tự động tiếp tục.
- **Cần bạn bổ sung thông tin:** trả lời mục tiêu, phạm vi và tiêu chí nghiệm thu ngay trong thẻ issue.
- **Cần chốt đặc tả:** bổ sung ba thông tin trên và có thể chọn viết đặc tả trước khi phân rã công việc.

Câu trả lời được lưu trong PokeDev và đưa vào yêu cầu của lượt chạy. Issue thay đổi nội dung sẽ được phân loại lại; thông tin của bản cũ được giữ trong lịch sử. Khi một lượt đã bắt đầu lập kế hoạch, phần yêu cầu của lượt đó được giữ nguyên.

Phân loại ban đầu dùng quy tắc có giải thích, không phát sinh lời gọi mô hình riêng. Netmind tiếp tục thực hiện lập đặc tả, lập kế hoạch và các công việc qua Harness như trước.

## Cài đặt cho từng project

**Chờ tôi duyệt** là mặc định. Việc cài tính năng này không bật tự động cho project hiện có.

**Tự làm việc ít rủi ro** tự lập kế hoạch cho issue đã rõ và tự duyệt khi kế hoạch đạt điều kiện R0–R1, mọi file sửa nằm trong phạm vi cho phép, và lệnh kiểm chứng phù hợp.

**Tự duyệt và thực hiện** dùng các kiểm tra phân loại, rủi ro, lệnh và ngân sách chung, với phạm vi file rộng hơn chế độ ít rủi ro. R2–R3 vẫn cần người duyệt.

Trong Cài đặt có thể chọn:

- Nhãn issue bắt buộc và workflow đã lưu của project.
- File chính xác, ví dụ `app.js`, hoặc thư mục kèm `/**`, ví dụ `src/components/**`. Phạm vi mặc định của chế độ ít rủi ro là `docs/**` và `tests/**`.
- Tối đa **3 lượt tự động trong 24 giờ gần nhất** theo mặc định; có thể chọn 1–50. Một lượt đã nhận được tính kể cả khi chuẩn bị hoặc thực hiện bị lỗi. Lượt do người dùng chủ động lập kế hoạch không tiêu thụ hạn mức tự động.
- Tối đa **20 phút làm việc cho một lượt** theo mặc định; có thể chọn 5–60. Tính tổng thời gian lập kế hoạch và thực hiện, tạm dừng khi chờ người dùng trả lời. Thời gian được cập nhật theo nhịp kiểm tra của ứng dụng.

Mọi thay đổi bật chế độ tự động cần xác nhận trong form. Đổi cài đặt dùng kiểm tra phiên bản để tránh ghi đè lựa chọn được lưu ở cửa sổ khác.

## Các mức rủi ro

| Mức | Ý nghĩa | Xử lý tự động |
| --- | --- | --- |
| R0 | Chỉ đọc hoặc phân tích, chưa có thay đổi file | Có thể tiếp tục lập kế hoạch; đánh giá lại khi kế hoạch có thay đổi file |
| R1 | Thay đổi trong bản làm việc có thể xem và hoàn tác | Có thể tự duyệt trong phạm vi và giới hạn đã chọn |
| R2 | Cấu hình, phụ thuộc, dữ liệu hoặc hệ thống dùng chung; phạm vi lớn; lệnh cần kiểm tra | Chờ người xem và duyệt |
| R3 | Quyền, danh tính, bí mật, dữ liệu/tài chính nhạy cảm, môi trường vận hành hoặc công bố ra ngoài | Chờ người xem và duyệt |

Mức cuối là yếu tố cao nhất. Hệ thống kiểm tra lại **đường dẫn file và lệnh thực tế trong kế hoạch**, kể cả khi mô tả issue có vẻ ít rủi ro. Các đường dẫn nhạy cảm được kiểm tra riêng với danh sách file cho phép.

Lệnh tự động hiện hỗ trợ các trình chạy kiểm thử tường minh: `python -m unittest`, `python -m pytest`, `node --test`. Lệnh tùy ý, script npm, cài phụ thuộc hoặc khởi chạy dịch vụ được đưa về cho người xem trước khi duyệt. Chọn **Xem công việc → Duyệt & thực hiện** để chủ động xử lý một kế hoạch cần người duyệt.

## Giữ dấu vết và xử lý gián đoạn

- Kết quả phân loại, các yếu tố rủi ro, câu trả lời, chính sách, lượt đã nhận và quyết định duyệt được lưu bền vững trong cơ sở dữ liệu hiện có. Giao diện hiển thị 50 sự kiện gần nhất cho đề xuất và chính sách project.
- Việc nhận hạn mức và duyệt đúng kế hoạch được kiểm tra trong giao dịch dữ liệu. Đổi chính sách, sửa issue hoặc thay thông tin phân loại sẽ chặn việc tự duyệt kế hoạch cũ.
- Khởi động lại giữ nguyên hạn mức 24 giờ. Lượt lỗi không được tự chạy lại vô hạn. Lượt chưa có native run được phục hồi bằng định danh cố định; lượt native đã có không bị phát lại.
- Hết thời gian làm việc sẽ dừng xử lý cục bộ và yêu cầu hủy các session đang chạy thuộc đúng lượt đó. Nếu Harness chưa xác nhận dừng, trạng thái chuyển thành cần đối soát và project chờ xử lý trước lượt tiếp theo.
- Tắt chế độ tự động ngăn lần khởi chạy tiếp theo. Công việc đã bắt đầu tiếp tục theo vòng đời và giới hạn đã được gắn với lượt đó.
- Câu hỏi và quyền công cụ trong lúc chạy vẫn do người dùng phản hồi qua thông báo. Xuất bản kết quả giữ bước duyệt hiện có.

## Nguồn ý tưởng

Phần tích hợp dùng mô hình dữ liệu và luồng thực thi của PokeDev, dựa trên ý tưởng triage/gate trong workloop `d4370ca8ec38648175d74b50b862e48b8676392c` và phân tầng R0–R3 trong factory-wilson `bb5cb561d06fd9845f87044f045b6c241a77c01a`. Chi tiết nguồn nằm trong [bản đánh giá ban đầu](gitea-integration-review-2026-10-26.md).
