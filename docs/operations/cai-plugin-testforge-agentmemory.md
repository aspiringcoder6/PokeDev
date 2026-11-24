# Cài plugin TestForge và AgentMemory cho Harness của project

Cập nhật: **19/10/2026**. Hai plugin đã được tải và cài bằng CLI DSH có sẵn vào profile `web` thuộc **project ADLC**, không phải profile cá nhân tại `C:/Users/lenovo/.dsh`.

**Kiểm tra runtime/UI sau khi cài, cập nhật sau VPN:** Harness Docker `0.1.5-rc.2` nạp cả hai plugin với trạng thái Enabled / Running. Sau khi người dùng bật VPN, `testforge_health` và `memory_health` đều trả `status: ok` trong phiên thật; UI hiển thị được JSON và tóm tắt tiếng Việt. Lỗi kết nối trước VPN được giữ lại trong lịch sử. PokeDev vẫn báo `testforge_ready: false`, chưa kiểm chứng job TestForge hay dữ liệu memory trong luồng ADLC. Xem [kết quả kiểm tra trong ứng dụng](kiem-tra-plugin-testforge-agentmemory-ui-20261019.md). Trạng thái Docker tắt ở phần dưới thuộc lượt cài ban đầu.

## Kết quả

| Plugin | Phiên bản | Revision đã cài | Kiểm tra |
| --- | --- | --- | --- |
| `vai_testforge` | `1.0.0` | `f9120a741a7fc28b3c1ef292de0542d83aec881e` | Đăng ký 10 tool; `testforge_health` đạt |
| `vai_agentmemory` | `1.0.0` | `65a84337aec82b9aa5166f0712e56428f7734355` | Đăng ký 6 tool; `memory_health` đạt, Cognee `0.5.6` |

TestForge mới là repository riêng `vai_testforge`, không ghi đè nguồn tham chiếu cũ `vai-testforce`. AgentMemory trùng revision của bản tham chiếu đã tải trước đây, nhưng lần này được cài vào profile web.

Thư mục profile:

```text
D:/coding/ADLC/agent-harness-server/deepseek-harness/workspace/.dsh/profiles/web/
```

Hai package nằm trong `node_modules/vai_testforge` và `node_modules/vai_agentmemory`; `package.json` đã có dependency pin commit và tên của cả hai trong `dsh.profile.bundles`. `patchReload: live` và hai bundle nền được giữ nguyên. Cách cài hoisted tạo thư mục package thật, không đưa junction trỏ về đường dẫn Windows vào các package của container.

Checkout tham chiếu mới nằm dưới `integration-sources/harness-plugins/incoming-20261019/`. [Khóa nguồn](../../integration-sources/harness-plugins/source-lock-20261019.json) ghi revision, file, checksum và phạm vi kiểm tra.

## Địa chỉ và cú pháp đúng

Dòng AgentMemory được cung cấp ban đầu ghép nhầm `github.com/` trước URL Gitea và có hai đuôi `.git`. Hai lệnh đúng, khi chạy trong đúng môi trường Harness, là:

```powershell
dsh plugin --profile web add git+http://10.0.10.195:3000/admin/vai_testforge.git
dsh plugin --profile web add git+http://10.0.10.195:3000/admin/vai_agentmemory.git
```

**Không cần cài lại sau lượt này.** Khi dùng CLI từ Windows, `DSH_HOME` phải trỏ tới thư mục `workspace/.dsh` của project để tránh cài nhầm vào profile cá nhân. Trong container hiện có, `HOME=/app/workspace` đã trỏ tới đúng nơi. Lần cài này pin commit cụ thể, không tự nâng phiên bản runtime và không chạy script cài đặt thượng nguồn.

## Kiểm tra trong lượt cài ban đầu

- Hai repo nội bộ truy cập được; revision và file đã cài được đối chiếu với nguồn.
- Hai điểm vào JavaScript vượt qua kiểm tra cú pháp.
- Dùng `defineTool` thật của bản DSH cục bộ `0.1.1-rc.2` để khởi tạo các định nghĩa, thu đăng ký đủ 10 và 6 tool. Đây là kiểm tra tải/đăng ký có kiểm soát, chưa phải boot toàn bộ container DSH được pin riêng trong Dockerfile.
- Chỉ gọi `testforge_health` và `memory_health`; TestForge trả `status: ok`, Cognee trả `status: ok` và phiên bản `0.5.6`. Không chạy job test, gọi model, hỏi GraphRAG, ghi hay xóa memory.
- Đối chiếu SHA-256 xác nhận **383 tệp có sẵn được bảo vệ không thay đổi**, gồm plugin đang dùng, patch, lock, `.env`, cấu hình dịch vụ và thông tin xác thực. Bản sao profile cùng kết quả kiểm tra nằm trong thư mục riêng tư `adlc-flow/data/plugin-install-20261019/`.
- Docker engine chưa chạy. Container Harness chưa được khởi động/restart trong lượt cài; chưa xác nhận tool hiện trong Web UI hoặc tương thích end-to-end với image Docker. Hai bundle sẽ được nạp khi profile web đó được khởi động bình thường.

Peer dependency do host DSH cung cấp; cảnh báo peer khi cài profile riêng không được xử lý bằng cách tự nâng hoặc cài một runtime DSH thứ hai.

## Backend và quyền sử dụng

Plugin là bộ tool kết nối dịch vụ, không chứa toàn bộ backend:

| Plugin | Backend mặc định | Cấu hình chính |
| --- | --- | --- |
| TestForge | `http://10.0.10.195:9099` | `TESTFORGE_BROKER_URL`, `TESTFORGE_BROKER_TOKEN` trong Settings → Secrets khi backend yêu cầu |
| AgentMemory | `http://10.0.10.195:8011/mcp` | `AGENT_MEMORY_MCP_URL`, `AGENT_MEMORY_TENANT_ID` hoặc cấu hình plugin |

Không tự thay endpoint bằng các broker Docker cục bộ, không sao chép token, không thay model/provider hay kích hoạt dịch vụ khác.

AgentMemory thượng nguồn có cả đọc, tổng hợp, ghi và xóa; mặc định dùng tenant `opencode@local`. Đăng ký plugin không chứng minh cô lập project hoặc quyền ghi/xóa đã phù hợp. Các tool thô chỉ được dùng trong phạm vi mà chính sách phiên cho phép. Tích hợp tự động với workflow ADLC vẫn phải giữ [ranh giới project memory](../adr/0019-advisory-project-memory-and-protected-readonly-gateway.md), [ranh giới kiểm chứng](../adr/0018-frozen-http-replay-and-testforge-readiness.md) và các recipe/approval hiện có. Health đạt chưa xác nhận chất lượng test, ingestion/retrieval, tenancy hay Verify đầy đủ.

## Gỡ khi cần

Trong đúng môi trường/profile Harness, hai thao tác độc lập là:

```powershell
dsh plugin --profile web remove vai_testforge
dsh plugin --profile web remove vai_agentmemory
```

Gỡ plugin không được dùng để xóa dữ liệu Cognee, báo cáo TestForge hoặc lịch sử ADLC. Chưa thực hiện thao tác gỡ nào.
