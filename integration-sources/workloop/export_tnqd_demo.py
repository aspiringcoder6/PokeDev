"""Export only a completed, hash-consistent TNQD demo and its real evidence."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"adlc-flow"),str(ROOT/"integration-sources/workloop")]
from langflow.adlc.tnqd_plan import digest
from langflow.adlc.tnqd_memory import ProjectDocumentMemory
from tnqd_actions import Actions,MODULE,TS,HTML,SCSS,BASE
RUN="ce9de1ce-08e8-401d-b890-e322e4ad4718"
DIRECTORY=ROOT/"adlc-flow/data/tnqd-demo/runs"/RUN/"execution"
OUT=ROOT/"docs/report/tnqd-demo-20261022"

def sha(body):return hashlib.sha256(body).hexdigest()

def main():
    result=json.loads((DIRECTORY/"result.json").read_text(encoding="utf8"))
    planning=json.loads((DIRECTORY.parent/"planning/result.json").read_text(encoding="utf8"))
    assert result["state"]=="SUCCEEDED", "Demo chưa hoàn tất; không xuất báo cáo đạt."
    assert all(n["state"]=="DONE" for n in result["nodes"])
    plan=planning["plan"]
    assert digest({k:v for k,v in plan.items() if k!="digest"})==plan["digest"]
    groups={g["id"]:g for g in result["checks"]}
    assert (groups["baseline"]["passed"],groups["baseline"]["total"])==(6,13)
    assert (groups["candidate"]["passed"],groups["candidate"]["total"])==(13,13)
    assert (groups["testforge-attempt-1"]["passed"],groups["testforge-attempt-1"]["total"])==(6,7)
    assert (groups["testforge"]["passed"],groups["testforge"]["total"])==(7,7)
    assert result["preview"]["binding_verified"] and result["parallel"]["verified"]
    archive=DIRECTORY/"tnqd-candidate.zip"
    artifact=sha(archive.read_bytes())
    assert artifact==result["preview"]["artifact_sha256"]==result["preview"]["testforge"]["artifact_sha256"]
    candidate=ROOT/"adlc-flow/data/tnqd-live"/("c-"+RUN.replace("-","")[:12])
    actual={p:sha((candidate/MODULE/p).read_bytes()) for p in (TS,HTML,SCSS)}
    build=json.loads((DIRECTORY/"T14-B1.artifact.json").read_text(encoding="utf8"))
    assert build["source_hashes"]==actual and build["artifact_sha256"]==artifact
    assert actual[TS]==groups["candidate"]["source_sha256"]
    suite=sha((DIRECTORY/"frozen-cases.json").read_bytes())
    assert suite==result["handover"]["test_suite_digest"]
    before=json.loads((ROOT/"integration-sources/plugin-releases/vai-pokedev-services/0.5.2/release.json").read_text())
    after=json.loads((ROOT/"integration-sources/plugin-releases/vai-pokedev-services/0.5.3/release.json").read_text())
    script="lib/tnqd-testforge.py"
    assert before["files"][script]==after["files"][script], "Không được thay test giữa hai lần."
    OUT.mkdir(parents=True,exist_ok=True)
    memory=ProjectDocumentMemory(ROOT/"adlc-flow/data/tnqd-demo/project-memory.sqlite3")
    reads=[]
    for document in result["documents"]:
        fetched=memory.read(result["scope_id"],document["id"],document["revision"],"handover-independent-client-"+RUN)
        assert fetched["sha256"]==document["sha256"]==sha(document["body"].encode())
        assert document["body"].startswith(document["previous_body"]+"\n\n")
        reads.append({k:v for k,v in fetched.items() if k!="body"})
        (OUT/(document["id"]+"-verified.md")).write_text(document["body"],encoding="utf8",newline="\n")
        (OUT/(document["id"]+"-spec.md")).write_text(document["previous_body"],encoding="utf8",newline="\n")
    actions=object.__new__(Actions);actions.candidate=candidate
    patch=actions.diff()
    (OUT/"tnqd-workspace.patch").write_text(patch,encoding="utf8",newline="\n")
    sut_patch=patch.replace("a/"+MODULE,"a/FE/military-youth-develop/membership-roster/components/membership-list").replace("b/"+MODULE,"b/FE/military-youth-develop/membership-roster/components/membership-list")
    (OUT/"tnqd-sut.patch").write_text(sut_patch,encoding="utf8",newline="\n")
    check=ROOT/"adlc-flow/data/tnqd-live/pc"/RUN[:8]
    target=check/"FE/military-youth-develop/membership-roster/components/membership-list"
    target.mkdir(parents=True,exist_ok=True)
    for name in (TS,HTML,SCSS):shutil.copyfile(BASE/MODULE/name,target/name)
    subprocess.run(["git","init","--quiet",str(check)],check=True,capture_output=True)
    subprocess.run(["git","-C",str(check),"-c","core.autocrlf=false","apply","--check",str(OUT/"tnqd-sut.patch")],check=True,capture_output=True)
    changes=OUT/"candidate";changes.mkdir(exist_ok=True)
    for name in (TS,HTML,SCSS):shutil.copyfile(candidate/MODULE/name,changes/name)
    for name in ("baseline-checks.json","candidate-checks.json","frozen-cases.json","parallel-samples.json","T12.artifact.json","T14-T1.artifact.json"):
        shutil.copyfile(DIRECTORY/name,OUT/name)
    capsule={"run_id":RUN,"state":result["state"],"engine_status":result.get("engine_status"),"plan_digest":plan["digest"],"spec_digest":planning["spec_digest"],"source_hashes":actual,"artifact_sha256":artifact,"test_suite_sha256":suite,"testforge_script_sha256":after["files"][script],"testforge_script_unchanged":True,"parallel":result["parallel"],"tasks":plan["tasks"],"followup_tasks":result.get("followup_tasks",[]),"nodes":[{k:v for k,v in n.items() if k not in {"workspace","context_receipt"}} for n in result["nodes"]],"checks":result["checks"],"memory_readback":reads,"preview":{k:v for k,v in result["preview"].items() if k!="scope_id"},"plugin_revision":after["revision"],"patch_apply_check":"PASS","exported_at":datetime.now(timezone.utc).isoformat()}
    (OUT/"evidence.json").write_text(json.dumps(capsule,ensure_ascii=False,indent=2),encoding="utf8")
    parallel=result["parallel"]
    rows="\n".join(f"| {t['id']} | {t['title']} | {', '.join(t['depends_on']) or '—'} |" for t in plan["tasks"]+result.get("followup_tasks",[]))
    report=f"""# Demo TNQD: Memory → Planner → Workloop → TaskLoop → Sandbox → TestForge

Ngày nghiệm thu: 22–23/10/2026. Lượt chạy `{RUN}` đã hoàn tất, có thay đổi source và kết quả trình duyệt thật.

## Kết quả đã kiểm chứng

| Phép kiểm tra | Kết quả |
|---|---|
| Planner từ tài liệu BA | 17 task cụ thể, có bước làm, input/output, tiêu chí và dependency |
| TaskLoop xử lý phát hiện | 5 task phát sinh: sửa HTML → Verify → build → deploy → TestForge |
| Baseline, cùng bộ test khóa | 6/13 đạt; tái hiện 7 vấn đề trước cải tiến |
| Candidate sau sửa | 13/13 kiểm tra phương thức component đạt |
| TestForge lần đầu | 6/7; phát hiện mất tổng số khi danh sách rỗng |
| TestForge sau TaskLoop | 7/7; giữ nguyên script và expected result |
| Chạy song song | {parallel['tasks'][0]} + {parallel['tasks'][1]}, chồng {parallel['overlap_seconds']:.3f} giây, {parallel['simultaneous_samples']} mẫu quan sát |
| Tài liệu | 3 tài liệu có nguồn, sau đó 3 phiên bản bổ sung bằng chứng và đọc lại đúng SHA |
| Bàn giao source | 3 file; patch áp dụng được trên source baseline bằng `git apply --check` |

## Mở để trình diễn

[Mở công việc TNQD trong PokeDev](http://127.0.0.1:7860/work/d81cadf3-399d-408b-b39c-868c2496aa57?view=results).

1. **Tài liệu & Memory:** mở PTYC, TKCT, CSDL; xem phiên bản trước phát triển và phần bổ sung. Badge đọc lại dựa trên digest nội dung.
2. **Task & DAG:** chọn T02, T05 và T08. Nhánh code/test độc lập; T03 chờ T02 vì cùng sửa component; T08 chờ đủ sáu artifact.
3. **Chạy song song:** xem thời gian thực từ backend và hai session có hoạt động tool cùng lúc, cùng spec digest. Không suy ra song song chỉ từ trạng thái trên UI.
4. **Test & Verify:** xem 6/13 → 13/13 và 6/7 → 7/7. Mở phát hiện AC07 của TestForge lần đầu.
5. **TaskLoop:** mở năm task phát sinh từ phát hiện; xem phạm vi HTML và bằng chứng Verify/build/deploy lại.
6. **Ứng dụng:** mở Sandbox, bấm Đăng nhập nhanh Dev; từ trang 3 tìm DEMO-AN, kết quả về trang đầu và đúng 3 hồ sơ. DEMO-BINH có 4; DEMO-KHONG-CO hiện rỗng và tổng 0; DEMO-ERROR hiện lỗi và có thể tìm lại.
7. **Bàn giao:** xem ba file thay đổi và giới hạn nghiệm thu. Mở lại tài liệu đã bổ sung sau phát triển.

Đây là hướng dẫn trình bày lượt chạy đã hoàn tất. Thời gian tạo mới gồm model, build và cấp Sandbox; không giả định toàn bộ lượt chạy lạnh hoàn tất trong thời lượng trình bày.

## Task và phụ thuộc

| Mã | Công việc | Phụ thuộc |
|---|---|---|
{rows}

Năm task phát sinh thuộc vòng TaskLoop của T14, lấy phát hiện lần đầu làm input; DAG 17 task đã duyệt được giữ nguyên. T15 chỉ chạy sau khi vòng sửa và TestForge lại đạt.

## Source, test và Memory

Source TNQD: `tnqd-sut@791910a9d11c5884e057cf09cc07bd62c2175558`; workspace shell: `tcct-fe-base@ded8387e93cf3f93e61f677789014e9aa29717ed`. Bootstrap lấy source đầy đủ từ Gitea, build component thật cùng thư viện VTS.

- [Patch cho tnqd-sut](tnqd-demo-20261022/tnqd-sut.patch), [patch cho workspace đầy đủ](tnqd-demo-20261022/tnqd-workspace.patch).
- [Bằng chứng máy đọc được](tnqd-demo-20261022/evidence.json); suite SHA `{suite}`.
- Artifact cuối: `{artifact}`. Script TestForge không đổi giữa hai lần: `{after['files'][script]}`.
- [PTYC bổ sung](tnqd-demo-20261022/TNQD_PTYC-verified.md), [TKCT bổ sung](tnqd-demo-20261022/TNQD_TKCT-verified.md), [CSDL bổ sung](tnqd-demo-20261022/TNQD_CSDL-verified.md).

Memory đang dùng kho tài liệu theo project của PokeDev, có phiên bản, nguồn, digest và lượt đọc trong context mới. Cognee tại `10.0.10.195:8011/mcp` từ chối kết nối trong lần thử; không tuyên bố AgentMemory/Cognee hoặc GraphRAG đã đạt. Lượt tiếp theo có thể đọc lại phụ lục đã xác minh để làm context, nhưng candidate chưa merge vẫn được ghi rõ là đề xuất.

## Giới hạn và vận hành

Kiểm tra phần tích hợp: production build PokeDev thành công; 5 kiểm thử UI, 6 kiểm thử backend và 29 kiểm thử plugin đạt. Kiểm tra TypeScript toàn repo vẫn ghi nhận 285 lỗi có sẵn ngoài các file TNQD; không tuyên bố toàn repo đã sạch TypeScript.

Ứng dụng Sandbox là component Angular TNQD thật với API fixture 45 hồ sơ giả lập và profile chỉ đọc. Static assets được cache từ đúng archive đã kiểm tra SHA của bản deploy; truy vấn dữ liệu chạy trong Sandbox. TestForge chạy trình duyệt ở chính Sandbox đó. Kết quả không chứng nhận backend Java, CSDL thật, RBAC server hoặc phát hành production.

Preview có thời hạn hiển thị trong UI. Không tự merge hay thay phiên bản TNQD đang phục vụ tại cổng 3011. Hai báo cáo TestForge và tài liệu trước/sau đều được giữ lại. Mẫu gốc `memoryTestDocs` không bị sửa.

Plugin bridge đã đẩy lên Gitea và activate trên Harness: `vai-pokedev-services` 0.5.3, revision `{after['revision']}`. Workloop dùng engine thật và native TaskLoop contract, tối đa hai agent đồng thời; một số bước là runner cố định, được phân biệt trong chi tiết task.

## Ảnh nghiệm thu

![Chạy song song](tnqd-demo-20261022/01-parallel-timeline.jpg)

![DAG và phụ thuộc](tnqd-demo-20261022/02-dag-and-dependencies.jpg)

![TaskLoop xử lý phát hiện](tnqd-demo-20261022/03-taskloop-repair.jpg)

![Memory và tài liệu](tnqd-demo-20261022/04-memory-documents.jpg)

![Test và Verify](tnqd-demo-20261022/05-test-and-verify.jpg)

![Ứng dụng Sandbox](tnqd-demo-20261022/06-sandbox-desktop.jpg)

![Ứng dụng ở 390px](tnqd-demo-20261022/07-sandbox-mobile.jpg)

![Ứng dụng tương tác trong PokeDev](tnqd-demo-20261022/08-sandbox-in-pokedev.jpg)
"""
    path=ROOT/"docs/report/pokedev-tnqd-demo-20261023.md"
    path.write_text(report,encoding="utf8")
    print(json.dumps({"report":str(path),"tasks":len(result["nodes"]),"artifact_sha256":artifact,"patch_check":"PASS","new_context_reads":len(reads)},ensure_ascii=False))

if __name__=="__main__":main()
