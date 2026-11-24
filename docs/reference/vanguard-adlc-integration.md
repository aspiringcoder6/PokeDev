# Đánh giá tích hợp Vanguard ↔ ADLC

> Tài liệu tham chiếu tổng hợp/dịch từ văn bản gốc trên nhánh `agentHarness`. Các bảng đánh giá, bảng so sánh, bảng trạng thái và các điểm neo nguồn (source anchors) được giữ nguyên như bản gốc.

Ngày review: 2026-10-08. Phạm vi: cây làm việc hiện tại, gồm cả công việc hợp đồng H5 chưa commit có sẵn.

## Khuyến nghị

Triển khai Vanguard như một **mẫu workflow nhà máy phần mềm** (software-factory workflow template) tái sử dụng, dùng Blueprint compiler, coordinator, phê duyệt và ranh giới thực thi Harness của ADLC. Để ADLC chịu trách nhiệm vòng đời và chính sách; trao cho Harness đúng một lần thử nhiệm vụ (task attempt) có phạm vi tại mỗi thời điểm.

Những phần bổ sung hữu ích là kết quả nhiệm vụ và bằng chứng (evidence) có cấu trúc, thực thi song song có giới hạn, bàn giao mã qua dependency (dependency code handoff), và làm lại (rework) tường minh. Một bộ lập lịch taskloop độc lập thứ hai sẽ tạo ra quyền sở hữu cạnh tranh đối với trạng thái nhiệm vụ, retry và phê duyệt.

Có hai hướng tích hợp khả dĩ:

1. **Workflow nhà máy (factory workflow):** áp dụng quy trình đã dựng nên Vanguard. Đây là điểm khớp tức thì cho ADLC.
2. **Máy quét thiết kế API (API design scanner):** sau đó đăng ký CLI Vanguard đã hoàn thành như một provider TESTING/REVIEW. Thư mục định nghĩa một linter ưu tiên Java/Spring; hỗ trợ Python/FastAPI là công việc đợt 2 (wave-2). Nó hiện không thể được coi là một máy quét đã triển khai cho backend Python của chúng ta.

## Những gì đã được đọc và kiểm tra

Đọc mọi tài liệu nguồn trong `agent-harness-server/deepseek-harness/vanguard`: README, REPORT, PROCESS, manifest, Python runner, cả bảy đặc tả workflow, và cả 41 bản tóm tắt nhiệm vụ (task brief). So sánh chúng với Blueprint models/compiler/materializer, coordinator, package registry và recipes, Harness adapter/driver/collector, contract models và chính sách thực thi, persistence, và các điểm vào UI hiện có.

Manifest có 41 nhiệm vụ, 58 cạnh dependency, bảy nhóm workflow, năm checkpoint, và **bốn checkpoint của con người**. Lịch trình topo thực tế của nó chứa **27 đợt sóng (wave)**, với tối đa bốn nhiệm vụ sẵn sàng đồng thời và mức đồng thời cấu hình là ba. Các ước tính cộng lại thành **2.055 agent-phút**; ước tính tài liệu không phải thời gian thực thi quan sát được. Mục 9 của REPORT trong checkout này vẫn chứa các kết quả thực thi chưa điền.

Một thí nghiệm tương thích in-memory đã dùng parser, registry, resolver và compiler ADLC thật. Cả 41 nhiệm vụ công việc được gán các placeholder mock `coding-agent@0.1.0` hiện có; bốn giai đoạn `approval@0.1.0` riêng biệt được chèn giữa các nhiệm vụ checkpoint của con người và các nhiệm vụ phụ thuộc chúng. Kết quả:

- `VALIDATED`, 45 nhiệm vụ kế hoạch, 62 cạnh, và việc chấp nhận kế hoạch là bắt buộc.
- Di chuyển mọi node canvas vẫn giữ nguyên digest phân giải.
- Không tạo lần chạy runtime, phiên từ xa hay lời gọi model nào.

Điều này xác lập chỉ tính tương thích cấu trúc. Nó không xác thực capability vai trò thật, bằng chứng hoàn thành, checkpoint tự động, hay việc thực thi bất kỳ tiêu chí chấp nhận nào của Vanguard. Bản xem trước cố ý bảo tồn các dependency gốc của manifest, gồm cả lỗi thứ tự CH2 dưới đây.

## Mô hình nhà máy đáng áp dụng

Vòng lặp sản phẩm là Triage → Specification → Implementation → Review → Verification → Shipping → Monitoring. Vanguard khởi tạo nó thành:

| Nhóm | Công việc | Cách xử lý trong ADLC |
|---|---|---|
| W1 | Nghiên cứu, trinh sát kho (repository reconnaissance), charter, chiến lược test, chuẩn bị kho | Nghiên cứu fan-out, hội tụ về một đặc tả, rồi CH1 review của con người |
| W2 | Lõi độc lập ngôn ngữ, IR, discovery, rules, renderers, CLI, golden tests | Dependency nhiệm vụ có type cộng CH2 xác minh bằng mã đáng tin |
| W3 | Java parser, Spring mapping, bốn nhánh rule, test/tài liệu hợp nhất | Triển khai song song với workspace cô lập và một bước tích hợp |
| W4 | Adversarial corpus, mutation tests, hiệu năng, kiểm toán FP/FN, độ bền | Bằng chứng độc lập và CH3 review chất lượng của con người |
| W5 | Quét kho thật, so sánh độc lập bề mặt API, triage, postmortem | Artifact có phiên bản, quyết định CH4, và một chu kỳ remediation liên kết |
| W6 | Build/package, tài liệu, chuẩn bị và xác minh phát hành | Ủy quyền của con người trước khi xuất bản, theo sau là một nhiệm vụ xuất bản được kiểm soát |
| W7 | Tiếp nhận issue, telemetry, metrics, sổ đăng tự chủ (autonomy register), báo cáo cuối | Phản hồi tạo một workflow/kế hoạch đề xuất mới với dòng dõi được ghi lại |

Bảy nhóm là một lớp trình bày hữu ích. Bảo tồn dependency cấp nhiệm vụ: thay cả chương trình bằng bảy node agent lớn sẽ đánh mất các nhánh song song và các ranh giới review của nó.

## Tái sử dụng trong dự án hiện tại

| Triển khai hiện có | Nền tảng hữu ích | Phần mở rộng cần thiết |
|---|---|---|
| `blueprints/models.py`, `planning/parser.py`, `planning/compiler.py` | Model đóng, xác minh DAG, phân giải package chính xác, định danh kế hoạch xác định | Import bundle nguồn; bảo tồn khóa nhiệm vụ, nhóm, digest brief và định danh tài liệu/node đã duyệt xuyên suốt runtime |
| `planning/materializer.py` | Kế hoạch bất biến đã chấp nhận thành định nghĩa runtime | Mang chính sách/provenance factory/lần chạy đã đóng băng; tính idempotent của materialization bền vững |
| `run_service.py` | Độ sẵn sàng dependency, dispatch đồng thời, lần thử nhiệm vụ, phê duyệt, input bindings, sự kiện, retry | Giới hạn công việc hoạt động, thêm làm lại có giới hạn, thực thi chính sách bằng chứng/kết quả factory |
| `executor_router.py`, `harness_executor.py` | Port executor ổn định và các request nhiệm vụ/phiên có tương quan | Recipes theo vai trò và các executor xác minh/xuất bản xác định |
| `contract_models.py`, contract repository/bridge | Tham chiếu Roadmap/SkillTree đã duyệt chính xác và thẩm quyền | Dịch tường minh từ node nhiệm vụ đã duyệt sang giai đoạn thực thi được |
| Ranh giới thực thi H5C/H5D | Thao tác file bị giới hạn, patch thật được chụp, bằng chứng bất biến, phục hồi xác minh | Ranh giới capability factory mới riêng cho các phép test và thao tác khác |
| `run_repository.py`, `harness_attempts.py` | Lần chạy/lần thử/callback/phục hồi bền vững có phạm vi owner | Kế hoạch bền vững, định danh program/cycle, snapshot tích hợp, và bằng chứng dài hạn |
| Blueprint editor, Plan Preview, Run Detail, ContractViewer/ContractExecutionPanel | Soạn thảo, chấp nhận kế hoạch, review nguồn, kết quả, bằng chứng, phê duyệt | Tiến độ factory theo nhóm, lý do bị chặn, tính đầy đủ bằng chứng, các view làm lại và metric |

Metadata giai đoạn hiện sống sót trong `ResolvedNodeSpec.metadata.stage_metadata`; `PlanTask.metadata` được dựng chỉ với định danh package, và materialization không chuyển tiếp mọi metadata giai đoạn. Provenance factory cần một ánh xạ tường minh đầu-cuối.

## Các vấn đề trong runner hiện tại của Vanguard

Đây là những lý do để dùng quy trình làm đầu vào thiết kế và triển khai các bảo đảm của nó qua ADLC.

| Phát hiện | Bằng chứng / hệ quả |
|---|---|
| Đường dẫn cục bộ bị lỗi thời | `orchestrate.py:25` kỳ vọng `agent-harness-server/sdk`, thứ không tồn tại. Dòng 68/100 phân giải manifest `plans/vanguard/briefs/...` bên dưới `agent-harness-server`; cả 41 đường dẫn brief đều không có ở đó. `load_manifest()` offline thất bại ngay brief đầu tiên. |
| CH2 không tự động trong mã | `wait_gate()` tại dòng 229 không bao giờ kiểm tra `human` hay đánh giá `auto_pass`. Một lời gọi offline với fake-client của CH2 đọc các bình luận phê duyệt và đòi hỏi một bình luận `APPROVED`. |
| Phê duyệt không bị ràng buộc vào bằng chứng/lần thử | Dòng 247 chấp nhận bất kỳ bình luận nào có văn bản bắt đầu bằng `APPROVED`; nó không kiểm tra danh tính người review hay phiên bản attempt/evidence đã review. Vòng lặp cũng không triển khai chuyển tiếp làm lại/từ chối đã được tài liệu hóa. |
| Restart có thể dispatch lại công việc đã hoàn thành | `run_one()` tại dòng 198 gửi một prompt mới trước khi đọc trạng thái kết thúc. Một fake client báo cáo hợp đồng đã DONE vẫn nhận một prompt model. Không có hàng rào dispatch persistent/phục hồi session kiểu ADLC. |
| Một số lần chạy chọn lọc có thể bỏ qua điều kiện tiên quyết | `cmd_run()` tại dòng 254 lọc các sóng tĩnh bằng `--only`/`--wave`; nó không bao giờ kiểm tra kết quả điều kiện tiên quyết runtime. Một probe offline `--only w3-04` đã dispatch nhiệm vụ đó mà không kiểm tra dependency. `--wave N` nghĩa là từ N trở đi, trái với một ví dụ README mô tả một sóng duy nhất. |
| Xử lý concern mâu thuẫn với SOP | SOP cho phép một `DONE_WITH_CONCERNS` không-phủ-cổng được tiếp tục. `cmd_run()` chỉ chấp nhận DONE; probe không-phủ-cổng offline trả về exit code 2. |
| CH2 không bảo vệ điểm bắt đầu W3 | Manifest khiến `w3-01` phụ thuộc `w2-03`, trong khi sơ đồ workflow đặt nó sau `w2-07`. `w3-01` chạy ở sóng 8; CH2 và `w3-02` ở sóng 9. Sửa điều này trong một phiên bản mẫu đã review trước khi thực thi. |
| Bằng chứng và công cụ chủ yếu là chỉ dẫn | `make_contract()` gọi các công cụ là "khuyến nghị"; polling hoàn thành đọc trạng thái, không phải byte báo cáo, checksum, kết quả test hay commit đã đẩy. Cấu hình Git, sandbox và ratchet chủ yếu đi vào ngữ cảnh tài liệu/prompt. |
| Các chu kỳ phản hồi không phải cạnh thực thi được | `waves()` từ chối chu trình. W5→W3 là một chu kỳ mô tả sau này, không phải một back-edge chạy được. Hãy mô hình hóa nó như một kế hoạch/lần chạy kế nhiệm với dòng dõi tường minh. |
| Tích hợp Git đa-cha chưa được chỉ định đủ | `git merge --ff-only` tuần tự không thể kết hợp các nhánh anh em đã phân kỳ. Thêm một nhiệm vụ tích hợp đáng tin với xử lý xung đột tường minh. |
| Ký duyệt phát hành xảy ra sau khi xuất bản | `w6-04` tag/xuất bản trước `w6-05`/CH5. Chuyển thẩm quyền xuất bản lên trước tác dụng phụ trong mẫu ADLC. |

Còn có trôi đặc tả (specification drift): một số tài liệu W3 đòi hỏi ít nhất 21 rule trong khi yêu cầu chương trình đòi hỏi ít nhất 25. Việc import văn bản chấp nhận nên làm nổi các xung đột như vậy để review.

## Đề xuất triển khai

### 1. Import một bundle chương trình có phiên bản

Thêm một `langflow/adlc/factory/importer.py` đang đề xuất cộng các factory model có type và một hợp đồng/schema có phiên bản dưới `adlc-contracts`.

Nguồn là một bundle đã đăng ký chứa manifest và văn bản brief đã chụp. Chuẩn hóa các đường dẫn legacy của nó một cách tường minh; từ chối các tham chiếu tuyệt đối/đi ra ngoài thư mục/thiếu. Không đi theo các đường dẫn hệ thống file hay URL do caller chọn tùy ý. Đóng băng digest manifest/brief, khóa nhiệm vụ ngoài ổn định, các nhóm workflow, và ánh xạ package chính xác đã chọn.

Dịch sang biểu diễn Blueprint được đánh dấu hiện có. Dùng UUID xác định giới hạn trong định danh workflow đã lưu, một giai đoạn cho mỗi nhiệm vụ, và các slot đầu vào/đầu ra có type. Coi `wf` như metadata nhóm. Nhúng nội dung brief vào snapshot yêu cầu bất biến; một đường dẫn file có thể thay đổi là không đủ. Tham chiếu kho, route model, callback và vault phải là các lựa chọn thuộc sở hữu deployment/package thay vì các mặc định sao chép theo máy.

Bắt đầu với import manifest. Sau đó cung cấp một adapter Roadmap/SkillTree đã duyệt: các node TASK trở thành các giai đoạn công việc, các quan hệ MILESTONE/CONTAINS cung cấp nhóm, và các quan hệ REQUIRES cung cấp dependency sau khi hướng của chúng được xác minh. Đòi hỏi một ánh xạ executor/package tường minh. Đóng băng tham chiếu đã duyệt bốn-trường cộng định danh node được chọn; không bao giờ đoán executor từ một tiêu đề hay dùng ngầm phiên bản tài liệu mới nhất.

Chính sách thực thi tài-liệu-đã-duyệt hiện tại áp các vị từ trên các tiêu chí tài liệu; nó không dịch SkillTree thành một kế hoạch thực thi đa-nhiệm-vụ hay chứng nhận thứ tự thời gian nhiệm vụ. Adapter này là công việc mới.

### 2. Định nghĩa kết quả nhiệm vụ và bằng chứng đáng tin

Thêm một hợp đồng kết quả factory có phiên bản với một kết quả nghiệp vụ (business outcome), các deliverables, tham chiếu bằng chứng, concerns, yêu cầu blocker/quyết định, và ngữ cảnh bàn giao. Giữ cái này tách biệt với các trạng thái truyền kết thúc hiện có.

Diễn giải đề xuất:

| Kết quả Vanguard | Ý nghĩa ADLC đề xuất |
|---|---|
| DONE | SUCCEEDED chỉ sau khi các kiểm tra bằng chứng cấu hình ĐẠT |
| DONE_WITH_CONCERNS | Kết quả mang concern tường minh; chỉ tiếp tục dưới một chính sách được tuyên bố; các checkpoint nghiêm ngặt vẫn bị chặn |
| NEEDS_CONTEXT | Tương tác chờ có type trong khi session vẫn có thể tiếp tục, hoặc một bước quyết định tường minh |
| BLOCKED | Blocker có type với bên chịu trách nhiệm; dùng hành vi thất bại/tạm dừng hiện có trước, với retry tường minh sau khi giải quyết |
| TIMEOUT | Thất bại timeout có cấu trúc; không tự động khởi chạy một lượt model không chắc chắn khác |

ADLC hiện không có trạng thái nhiệm vụ BLOCKED/NEEDS_CONTEXT/DONE_WITH_CONCERNS, và cạnh chỉ hỗ trợ ON_SUCCESS. Bắt đầu với thành công nghiêm ngặt và các quyết định tường minh. Routing có điều kiện theo kết quả đòi hỏi một phần mở rộng schema/runtime có chủ đích.

Một báo cáo nên chứa deliverables, bằng chứng thực thi thực tế, artifact/checksum, định danh snapshot/commit nguồn khi áp dụng, các trở ngại, và hướng dẫn bàn giao. Tường thuật do tác giả viết vẫn chỉ là một tuyên bố. Các executor/collector đáng tin sẽ tạo (mint) các bản ghi test, artifact và provenance gắn với cùng lần chạy/nhiệm vụ/attempt và byte nguồn.

Giới thiệu một kho bằng chứng có giới hạn cho các byte báo cáo, JSON/SARIF, log test và screenshot với các lượt đọc có xác thực, giới hạn kích thước, checksum, và chính sách lưu giữ tường minh. Import Harness hiện tại chủ yếu giữ các byte SOURCE_PATCH đã chụp: 512 KiB, 128 file, tối đa 24 giờ. Điều đó không đủ làm kho lưu bằng chứng duy nhất cho một chương trình được mô tả là kéo dài nhiều ngày. Không âm thầm gia hạn các artifact đã cấp hay tái dùng một URI workspace làm bằng chứng.

### 3. Thực thi capability vai trò qua các recipe mới

Tạo các recipe researcher, implementer, reviewer, documenter và verifier có phạm vi hẹp khi cần. Đăng ký các phiên bản package/plugin chính xác, các schema đầu ra được hỗ trợ, route model, các quyền capability, và chính sách sandbox. Cài đặt các kiểm tra dispatch, thay vì dựa vào danh sách tên công cụ trong prompt.

H5C/H5D cung cấp các công cụ context/list/read/write và từ chối shell, network, subagents, commit, push, deploy, và các test tùy ý. Các check được hỗ trợ của nó chứng minh một patch không rỗng, không thay đổi, hoặc cú pháp JSON thay đổi ĐẠT. Các recipe đó không thể chạy các nhiệm vụ build/mutation/benchmark/phát hành của Vanguard. Bảo tồn các byte/lock đã phát hành của chúng và thêm các bản phát hành factory bật-tùy-riêng.

Dùng các executor TESTING/REVIEW xác định cho các lệnh và metric được khai báo. Schema node-kind hiện tại cho phép điều này, nhưng một provider/route thật là bắt buộc. Xác minh nên đánh giá snapshot ứng viên thực tế, thực thi giới hạn tài nguyên/thời gian, và phân biệt thất bại test với thất bại hạ tầng. Các vai trò nghiên cứu và test cần các capability được ủy quyền riêng.

### 4. Thêm lập lịch có giới hạn và bàn giao mã

`run_service.py:867` dispatch mọi nhiệm vụ sẵn sàng bằng `asyncio.gather()` và không có giới hạn đồng thời kiểu manifest. Đóng băng một chính sách lần chạy được hỗ trợ, ban đầu tối đa ba nhiệm vụ worker hoạt động, và thực thi nó xuyên suốt dispatch và phục hồi. Lưu nó cùng lần chạy. Không coi một mục trong từ điển `resources` tùy ý là chính sách được thực thi nếu không có hỗ trợ từ scheduler.

Coordinator đã gửi các đầu ra thượng nguồn, input bindings, và tham chiếu artifact. Git collector độc lập clone HEAD đã commit của kho đã cấu hình cho mỗi session mới. Gửi một URI báo cáo hay patch của nhiệm vụ tiền nhiệm không đưa mã của nó vào lần checkout tiếp theo.

Thêm một dịch vụ tích hợp/snapshot đáng tin:

1. Đọc các artifact tiền nhiệm đã chấp nhận và xác minh owner, attempt, checksum, và định danh base.
2. Tổ hợp các thay đổi dependency được khai báo trong một workspace cô lập có giới hạn.
3. Dừng tại các thay đổi xung đột/mơ hồ và yêu cầu một quyết định được ghi lại.
4. Tạo một snapshot ứng viên bất biến với provenance.
5. Bắt đầu coding/testing hạ nguồn trên đúng snapshot đó; chỉ thu thập delta của chính nó.

Giữ tích hợp ứng viên tách biệt với việc merge/push nhánh chính của dự án. Các nhiệm vụ rule song song có thể dùng chung một base nhưng phải có workspace cô lập. Các nhiệm vụ đa-cha tiêu thụ một snapshot tích hợp thay vì cố một chuỗi fast-forward bất khả thi. Bằng chứng cũ/hết hạn fail closed.

### 5. Làm checkpoint và làm lại tường minh

Dùng các giai đoạn điều khiển `approval@0.1.0` hay chính sách AFTER_TASK hiện có cho các checkpoint của con người. CH2 nên là một phán quyết test đáng tin. Ràng buộc mỗi quyết định vào phiên bản kết quả/evidence đã review và bảo tồn actor và lý do được ghi lại.

Phê duyệt hợp đồng, chấp nhận kế hoạch, yêu cầu thông tin Harness, gửi kết quả thủ công, và phê duyệt vòng đời vẫn là các thao tác khác nhau. Triển khai phê duyệt hiện tại hỗ trợ đúng một phê duyệt vòng đời chặn đang chờ cho mỗi lần chạy; mẫu ban đầu nên tuần tự hóa các checkpoint của con người tương ứng. Chỉ metadata vai trò yêu cầu không nên được trình bày như bằng chứng của một triển khai ủy quyền vai trò hoàn chỉnh.

Từ chối hiện tại chấm dứt một lần chạy với trạng thái FAILED; retry chỉ chấp nhận một nhiệm vụ FAILED trong một lần chạy PAUSED. Thêm một hành động Yêu cầu bản chỉnh sửa (Request revision) riêng biệt. Nó nên định danh (các) nhiệm vụ cần xem lại, bảo tồn các quyết định/kết quả gốc, giới hạn việc làm lại, và vô hiệu các ứng viên hạ nguồn bị ảnh hưởng. Ban đầu tạo một kế hoạch/lần chạy kế nhiệm liên kết; không đột biến các nhiệm vụ lịch sử đã thành công hay tạo các cạnh v0.1 có chu trình.

Với shipping: chuẩn bị artifact → xác minh ứng viên → phê duyệt xuất bản của con người → executor xuất bản đáng tin → các kiểm tra hậu phát hành. Phê duyệt một kết quả không tự nó merge, push hay deploy.

### 6. Hoàn thiện persistence và quan sátability

Các lần chạy và Harness attempts bền vững qua các kho SQLite hiện tại. Kế hoạch và tính idempotent của materialization vẫn là các từ điển nằm trong tiến trình trong `ExecutionPlanService` và `ExecutionPlanMaterializer`. Lưu các snapshot kế hoạch đã chấp nhận, dòng dõi, và ánh xạ owner/plan/idempotency-key→run trước khi dựa vào một factory có thể restart. Tái dùng một idempotency key không bao giờ được khởi động một chương trình trùng lặp sau restart.

Thêm định danh program/cycle và chính sách/provenance đóng băng vào các snapshot runtime. Giữ ràng buộc single-coordinator hiện tại cho đến khi quyền sở hữu worker giao dịch/lease được thiết kế. Phục hồi nên gắn lại các session đã biết hay đối chiếu bằng chứng gốc; thực thi không chắc chắn đòi hỏi một lần thử mới tường minh.

Dựng metrics từ các sự kiện giữ lại và bằng chứng đáng tin: thời gian nhiệm vụ/chờ, tỷ lệ hoàn thành lần đầu, làm lại, tỷ lệ concern, các quyết định checkpoint, kết quả test/chất lượng, và phiên bản nguồn/evidence. Không suy ra chất lượng chỉ từ trạng thái agent.

Sổ đăng tự chủ nên đề xuất thay đổi chính sách dựa trên các metric có phiên bản và một quyết định tường minh. Thăng cấp ảnh hưởng đến các kế hoạch mới chấp nhận; nó không được loại một checkpoint khỏi một lần chạy đang diễn ra. Bắt đầu với một view khuyến nghị chỉ đọc trước khi thêm thăng cấp hay xuất bản tự động.

## Thứ tự triển khai và chấp nhận

| Slice | Phạm vi | Bằng chứng hoàn thành |
|---|---|---|
| A: Bản xem trước factory | Schema/importer bundle, provenance, bảy nhóm trực quan, 41 giai đoạn nhiệm vụ, bốn giai đoạn cổng của con người, sửa dependency CH2 đã review | Kế hoạch xác định; dep không rõ/ID trùng/chu trình/đi ra ngoài đường dẫn bị từ chối; chỉnh sửa brief làm đổi digest; không có tác dụng phụ từ xa |
| B: Hành vi coordinator | Kế hoạch/khóa materialization persistent, đồng thời đóng băng, kết quả/bằng chứng thí điểm, các cổng tường minh | Restart bảo tồn ID/quyết định; tối đa ba worker xuyên suốt dispatch/phục hồi đồng thời; không có lần chạy/dispatch model trùng; bằng chứng cổng stale bị từ chối |
| C: Thí điểm nhiệm vụ/bằng chứng live | Các recipe có phạm vi mới, chụp artifact báo cáo/test, tích hợp ứng viên đáng tin | Một thay đổi tiền nhiệm có mặt trong workspace cô lập tiếp theo; hai thay đổi anh em tích hợp; xung đột chặn; các tuyên bố thành công/test bịa đặt thất bại |
| D: Làm lại và chất lượng | Hành động chỉnh sửa, dòng dõi kế nhiệm, các provider xác minh thật, metrics chương trình | Chỉnh sửa hướng bởi con người tạo các lần thử/dòng dõi snapshot mới; các kết quả lịch sử vẫn đọc được; các kiểm tra cổng tự động kiểm tra đúng ứng viên đã test |
| E: Shipping và phản hồi | Executor xuất bản đã duyệt, tiếp nhận issue có ký/deduplicated, các khuyến nghị tự chủ | Không xuất bản trước phê duyệt của nó; webhook trùng tạo đúng một đề xuất; phản hồi liên kết một chu kỳ mới mà không âm thầm đổi một kế hoạch đã chấp nhận |

Thí điểm live đầu tiên nên nhỏ: trinh sát có phạm vi song song → đặc tả → review của con người → một nhiệm vụ triển khai → xác minh đáng tin → review cuối. Rèn luyện quy trình kiểu W1 trước. Một lần chạy đầy đủ 41 nhiệm vụ nên theo sau khi bàn giao snapshot, lưu giữ bằng chứng, và hành vi restart đã được chứng minh.

Dùng Blueprint editor, Plan Preview và Run Detail hiện có cho thí điểm này. Thêm tiến độ nhóm, blocker hiện tại, liên kết bằng chứng, và Yêu cầu chỉnh sửa vào đó trước khi giới thiệu một dashboard factory riêng biệt.

## Các điểm neo nguồn

- Vanguard runner: `agent-harness-server/deepseek-harness/vanguard/orchestrate.py:24`, `:58`, `:155`, `:198`, `:229`, `:254`.
- Checkpoint và dependency manifest: `agent-harness-server/deepseek-harness/vanguard/vanguard.manifest.json:36`, `:90`, `:94`.
- Blueprint graph/task models: `adlc-flow/langflow/adlc/blueprints/models.py:284`, `:311`, `:412`.
- Compiler và materializer: `adlc-flow/langflow/adlc/planning/compiler.py:208`, `planning/materializer.py:278`.
- Lập lịch, retry/từ chối, phê duyệt, và bàn giao đầu vào: `adlc-flow/langflow/adlc/run_service.py:556`, `:670`, `:867`, `:1194`, `:1278`.
- Lưu kế hoạch/idempotency: `adlc-flow/langflow/adlc/planning/service.py:33`, `planning/materializer.py:58`.
- Snapshot nguồn đã commit: `agent-harness-server/deepseek-harness/plugins/vai-adlc-artifacts-git/lib/collector.js:162`.
- Thực thi hợp đồng đã duyệt được hỗ trợ: `adlc-flow/langflow/adlc/contract_execution.py:25`, `:98`; ADR 0014 và 0015; các README plugin H5C/H5D.

Đánh giá này chỉ bổ sung tài liệu. Ứng dụng và các byte plugin/package đã phát hành không bị thay đổi, và không có lần thực thi live hay triển khai nào được thực hiện.

## Nguồn tổng hợp

Tài liệu này được dịch và tổng hợp từ file sau (lưu trữ trên nhánh git `agentHarness`, đọc bằng `git show agentHarness:docs/<file>`):

- `docs/vanguard-adlc-integration.md` — Vanguard integration assessment for ADLC
