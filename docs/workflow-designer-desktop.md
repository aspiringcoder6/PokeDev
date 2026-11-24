# Chỉnh workflow trên desktop

Mở project → **Workflow** → chọn workflow. Thay đổi được giữ trong bản nháp cho đến khi bấm **Lưu workflow**. Các lượt chạy đã bắt đầu tiếp tục dùng bản chụp cũ.

## Canvas

- Bấm hoặc kéo Developer, Tester, Reviewer, Điều kiện, Kiểm chứng, Cổng duyệt từ thanh bên vào canvas.
- Mở rộng trình thiết kế để có thêm không gian; `Esc` thu gọn. Có thể ẩn/hiện danh sách task và panel chi tiết riêng.
- Dùng **Sắp xếp task tự động**, **Vừa canvas**, **Tập trung task**, hoặc các nút phóng to/thu nhỏ. Bám lưới 20px có thể bật/tắt.
- Nhân bản task giữ nội dung nhưng tạo mã mới và bỏ phụ thuộc. Cần kiểm tra lại phạm vi file và nối task mới.
- Hoàn tác/làm lại lưu tối đa 30 thay đổi đồ thị, bao gồm vị trí, nội dung, kết nối và áp dụng mẫu. Đổi tên workflow và project không thuộc lịch sử đồ thị.

## Chi tiết task

**Nội dung** có tên, vai trò hoặc điều kiện/cổng duyệt. Các bước thực hiện và tiêu chí nghiệm thu là danh sách riêng: thêm, xóa, đổi thứ tự, hoặc nhập nhiều dòng. Mỗi mục cần ít nhất 5 ký tự, tối đa 30 mục để thực thi. Nội dung nhiều dòng trong một mục được giữ nguyên khi lưu.

**Phạm vi** có bộ chọn file tìm kiếm từ commit source đang gắn với project; có thể nhập đường dẫn file mới. Mỗi task tối đa 40 file cụ thể. Developer sửa source; Tester tạo file test mới và giữ nguyên bộ test có sẵn; Reviewer và node điều khiển chỉ đọc. UI báo đường dẫn không phù hợp và file dùng chung giữa các task; máy chủ/bộ thực thi vẫn kiểm tra quyền, bảo vệ test và xung đột ghi.

API `GET /api/v1/adlc/live/projects/{project_id}/files` kiểm tra quyền đọc project trước khi đọc Git. Kết quả chỉ chứa đường dẫn, commit và cờ giới hạn 20.000 file; không chứa nội dung hoặc đường dẫn cache nội bộ. Symlink, submodule, thư mục sinh tự động và tên file bí mật được loại bỏ.

**Kết nối** liệt kê đầu vào/ra với nhãn nhánh, hỗ trợ gỡ từng cạnh và thêm đầu vào theo task nguồn + cổng đầu ra. Có thể nối trực tiếp trên canvas. UI chặn kết nối trùng, tự nối, vòng lặp phụ thuộc và đường sửa không phù hợp; máy chủ kiểm tra đầy đủ trước khi cho chạy.

**Nâng cao** cho phép đổi mã task và cách gộp đầu vào `all`/`any`. Đổi mã cập nhật toàn bộ cạnh và tham chiếu. Cách gộp nhánh dùng đồ thị v2; các nhánh điều kiện vẫn phải khớp kết quả thực tế.

## Mẫu và JSON

Có chín mẫu: song song, tuần tự, hai nhánh phát triển, kiểm chứng + người duyệt, điều kiện + vòng sửa, Agent review + vòng sửa, Agent review rồi người duyệt, rẽ nhánh đạt/lỗi, và review song song hai góc nhìn. Áp dụng mẫu thay cấu trúc/nội dung bản nháp, có tùy chọn giữ lệnh kiểm chứng/preview/kiểm tra trình duyệt. Mỗi mẫu cần chọn phạm vi file và lệnh phù hợp với project; không tự tạo lượt chạy. Vòng sửa tối đa 3, các mẫu vòng sửa mặc định 2.

Các mẫu từ factory-wilson có nguồn tham khảo ngay trong hộp chọn. Bản chuyển đổi giữ cấu trúc khả thi của vAIPlatform: Tester độc lập, kiểm chứng thật, vòng sửa giới hạn và cổng người duyệt. Không nhập token, lệnh tạo/merge PR, deploy, TestForge, Confluence hoặc tool riêng từ YAML gốc. Cổng duyệt ở nhánh lỗi không thể làm kết quả test cuối trở thành đạt.

**JSON nâng cao** cho phép chỉnh, nhập file và xuất đồ thị. Cần áp dụng JSON vào canvas trước khi lưu. JSON chưa hợp lệ không thay đồ thị; bản nháp JSON chưa áp dụng sẽ chặn lưu và bật cảnh báo khi rời trang. Giới hạn nhập 400 KB. Tên workflow và project được quản lý riêng; cấu hình nhập vẫn cần máy chủ xác nhận khả năng thực thi.

## Tham khảo workloop

Đã đọc repo `admin/workloop` trên Gitea, nhánh `agent-docs-langflow-dag`, commit `bcf1531bdd85251b1dd36d623f31f5cbba9cc1c0`:

- `frontend/docs/ke-hoach-workflow-editor-taskcontract.md`: bố trí theo tầng, kéo task vào canvas, lịch sử chỉnh sửa, kết nối rộng hơn.
- `frontend/docs/nghien-cuu-cognee-keo-tha-workflow.md`: inspector, camera canvas và chế độ mở rộng.
- `frontend/src/workflow/WorkflowPage.tsx`: phân biệt cạnh tiến và cạnh quay lại khi sắp xếp.
- `src/workloop/modules/foreman_spawner/workflow.py`: các bước test/code/verify/PR.

Các mẫu vAIPlatform dùng hợp đồng thực thi hiện có của vAIPlatform, không nhập trực tiếp flow Langflow của workloop. Không thêm loại node hoặc tùy chọn runtime chưa được hỗ trợ. Chỉ thiết kế và kiểm tra desktop.

Đã kiểm tra thêm `admin/factory-wilson`, nhánh `main`, commit `eec813d4e4d57520ba0ebcb8d12d0c531a3618e4`. Repo có các workflow YAML thật trong `workflows/`. Tham khảo `review-cycle.spec.yaml`, `branch-review.spec.yaml`, `implement-verify-release.spec.yaml` và `skills/workloop-skill/references/playbooks.md` để xây dựng các mẫu tương thích. `artifact-chain`, `foreman-pipeline` và `epistemic-vanguard` được đọc để đối chiếu; không quảng bá khả năng truyền artifact tùy ý, vai trò động hoặc công cụ ngoài hợp đồng hiện có.
