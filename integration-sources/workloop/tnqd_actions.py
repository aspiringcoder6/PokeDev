"""Bounded actions for the TNQD DAG. Agent proposals never become check results."""
from __future__ import annotations
import asyncio
import base64
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import zipfile
from uuid import UUID, uuid5, uuid4

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "adlc-flow/data/tnqd-live/tcct-fe-base"
MODULE = "src/app/modules/military-youth/membership-roster/components/membership-list"
NODE = Path("D:/Node/node.exe")
PROFILE = ROOT / "integration-sources/workloop/tnqd"
TS, HTML, SCSS = ("membership-list.component."+s for s in ("ts", "html", "scss"))

def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()

EXPECTED = {
    "test.pagination": {"AC01": {"expected_page": 0}, "AC02": {"expected_page": 0}, "AC03": {"expected_page": 1}, "AC04": {"expected_size": 10}, "AC09": {"expected_page": 0}, "AC10": {"expected_page": 0}},
    "test.race": {"AC06-HTTP": {"expected_name": "DEMO-BINH", "expected_total": 4}, "AC06-PERMISSION": {"expected_name": "DEMO-BINH", "expected_total": 4}, "AC05-CURRENT-LOADING": {}},
    "test.states": {"AC05": {}, "AC07": {}, "AC08": {}, "AC11": {}, "AC12-BROWSER": {}},
}

def configure_profile(workspace):
    shutil.copyfile(PROFILE/"pokedev-demo.ts",workspace/"src/pokedev-demo.ts")
    config_path=workspace/"angular.json"
    config=json.loads(config_path.read_text(encoding="utf8"))
    project=next(iter(config["projects"].values()))
    target=project.get("architect",project.get("targets"))["build"]
    target["configurations"]["pokedev-demo"]={"browser":"src/pokedev-demo.ts","outputPath":"dist/pokedev-tnqd","optimization":True,"sourceMap":False,"extractLicenses":False,"budgets":[]}
    target["configurations"]["pokedev-demo"]["assets"]=[
        {"glob":"**/*","input":"src/assets/icons","output":"/assets/icons"},
        {"glob":"**/*.css","input":"src/assets/style-theme","output":"/assets/style-theme"},
        {"glob":"**/*.css","input":"src/assets/styles","output":"/assets/styles"},
        *[{"glob":name,"input":"src/assets/images","output":"/assets/images"} for name in ("noData-table.png","logo-favico-2.png")],
    ]
    config_path.write_text(json.dumps(config),encoding="utf8")
    index=(BASE/"src/index.html").read_text(encoding="utf8")
    index=re.sub(r'<script\s+src=[\"\']assets/env.js[\"\']></script>',"",index)
    index=re.sub(r'<link\s+href="https://fonts.googleapis.com/[^>]+>',"",index)
    index=index.replace('<html lang="en">','<html lang="vi">').replace('<title>TCCTWeb</title>','<title>TNQD · Demo PokeDev</title>')
    index=index.replace("<head>","<head><script>window.__env={API_URL:'/api',production:false};</script>",1)
    (workspace/"src/index.html").write_text(index,encoding="utf8")

def package_artifact(build_dir,archive):
    files=[p for p in build_dir.iterdir() if p.is_file() and p.suffix in {".html",".js",".css",".ico"}]
    for name in ("media","assets/icons","assets/style-theme","assets/styles"):
        folder=build_dir/name
        if folder.exists():files.extend(p for p in folder.rglob("*") if p.is_file())
    files.extend(p for name in ("noData-table.png","logo-favico-2.png") if (p:=build_dir/"assets/images"/name).is_file())
    if len(files)>12000 or sum(p.stat().st_size for p in files)>120000000:raise RuntimeError("TNQD_ARTIFACT_PROFILE_TOO_LARGE")
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
        for p in sorted(set(files)):z.write(p,p.relative_to(build_dir).as_posix())
    return {"files":len(files),"bytes":archive.stat().st_size,"sha256":sha(archive.read_bytes())}

class Actions:
    def __init__(self, driver, manifest, snapshot, directory, update, persist):
        self.driver, self.m, self.s, self.directory = driver, manifest, snapshot, directory
        self.update, self.persist = update, persist
        # Keep the checkout short enough for Windows paths in the upstream repo.
        self.candidate = ROOT / "adlc-flow/data/tnqd-live" / ("c-"+manifest["run_id"].replace("-", "")[:12])
        self.spec = "\n\n".join(d["title"]+"\n"+d["body"] for d in manifest["documents"])
        self.suites = {}
        self.build_dir = self.candidate / "dist/pokedev-tnqd/browser"
        self.preview_generation=snapshot.get("preview_generation","")

    def restore(self,task,result):
        if task["operation"].startswith("test."):self.suites[task["operation"]]=result["cases"]
        if task["operation"]=="verify.merge" and sha((self.directory/"frozen-cases.json").read_bytes())!=result["suite_digest"]:raise RuntimeError("TNQD_RECOVERY_SUITE_CHANGED")
        if task["operation"]=="verify.candidate" and self.source_hashes()[TS]!=result["source_sha256"]:raise RuntimeError("TNQD_RECOVERY_SOURCE_CHANGED")

    def source_hashes(self):
        return {name:sha((self.candidate/MODULE/name).read_bytes()) for name in (TS,HTML,SCSS)}

    def sources(self, base=False):
        folder = (BASE if base else self.candidate) / MODULE
        return {name: (folder/name).read_text(encoding="utf8") for name in (TS, HTML, SCSS)}

    def context(self, task):
        return ("# Context từ tài liệu Memory đã đóng băng\nSpec SHA: "+self.m["spec_digest"]+
                "\n\n"+self.spec+"\n\n# Task Planner\n"+json.dumps(task, ensure_ascii=False)+
                "\n\nKhông coi Memory là bằng chứng test. Fixture chỉ đọc; không sửa test/expected result để xanh.")

    async def followup(self,task,action):
        from langflow.adlc.tnqd_plan import digest
        cached=self.directory/(task["id"]+".artifact.json")
        prior=next((n for n in self.s["nodes"] if n["id"]==task["id"]),{})
        if prior.get("state")=="DONE" and cached.exists():
            result=json.loads(cached.read_text(encoding="utf8"))
            if digest(result)!=prior.get("output_digest"):raise RuntimeError("TNQD_FOLLOWUP_OUTPUT_CHANGED")
            return result
        self.update(task["id"],"RUNNING",started_at=time.time(),title=task["title"],role=task["role"],depends_on=task["depends_on"],operation=task["operation"],parent_task="T14")
        try:
            result=await action()
            cached.write_text(json.dumps(result,ensure_ascii=False),encoding="utf8")
            summary=result.get("summary")
            self.update(task["id"],"DONE",completed_at=time.time(),summary=summary if isinstance(summary,str) else "Đã nhận artifact thực thi.",output_digest=digest(result))
            return result
        except Exception:
            self.update(task["id"],"FAILED",completed_at=time.time(),error_code="TNQD_FOLLOWUP_FAILED")
            raise

    async def browser_report(self):
        identity=self.s["preview"]["preview_id"]
        receipt=await self.driver.bridge("/previews/"+identity+"?scope_id="+self.m["scope_id"])
        if not receipt.get("testforge"):
            receipt=await self.driver.bridge("/previews/"+identity+"/test",{"scope_id":self.m["scope_id"]})
        for _ in range(180):
            if receipt.get("testforge",{}).get("state") in {"SUCCEEDED","FAILED","UNCONFIRMED"}:break
            await asyncio.sleep(2)
            receipt=await self.driver.bridge("/previews/"+identity+"?scope_id="+self.m["scope_id"])
        self.s["preview"]=receipt;self.persist()
        return receipt.get("testforge",{})

    def browser_group(self,report,identity="testforge",title="TestForge · trình duyệt trên Sandbox"):
        return {"id":identity,"title":title,"kind":"TestForge TraceRecorder · Angular thật + API fixture","total":report.get("total",0),"passed":report.get("passed",0),"tests":report.get("tests",[])}

    async def repair_browser(self,parent,first):
        if "first_testforge_report" not in self.s:self.s["first_testforge_report"]=first
        first=self.s["first_testforge_report"]
        failure=self.browser_group(first,"testforge-attempt-1","TestForge · lần đầu phát hiện lỗi")
        self.s["checks"]=[g for g in self.s["checks"] if g["id"] not in {"testforge","testforge-attempt-1"}]+[failure]
        specs=[
            ("R1","patch.empty","developer","Sửa trạng thái rỗng của danh sách TNQD để giữ tổng số bằng 0",["T13"],[HTML]),
            ("V1","verify.candidate","verifier","Chạy lại 13 testcase đã khóa sau phản hồi TestForge",[parent["id"]+"-R1"],[]),
            ("B1","build","builder","Build lại Angular từ bản sửa đã qua kiểm tra component",[parent["id"]+"-V1"],[]),
            ("D1","deploy","coordinator","Triển khai artifact mới vào Sandbox để kiểm chứng độc lập",[parent["id"]+"-B1"],[]),
            ("T1","testforge.recheck","tester","Chạy lại bảy bước TestForge trên desktop và viewport 390px",[parent["id"]+"-D1"],[]),
        ]
        tasks=[{"id":parent["id"]+"-"+suffix,"operation":operation,"role":role,"title":title,"depends_on":deps,"steps":["Đọc phát hiện TestForge gắn đúng artifact và đối chiếu PTYC AC07.","Thực hiện công việc trong phạm vi đã duyệt, giữ nguyên expected result của bộ test.","Xuất artifact có digest và kiểm tra trước khi chuyển bước tiếp theo."],"inputs":["Phát hiện T14 lần đầu: danh sách rỗng chưa hiện tổng 0","Spec đóng băng "+self.m["spec_digest"]],"outputs":[title+" · artifact có SHA"],"acceptance":["Bộ test gốc được giữ nguyên digest","Kết quả gắn với source và Sandbox đúng phiên bản"],"requirements":["AC07","AC05","AC12"],"write_paths":paths,"executor":"NATIVE_TASKLOOP" if paths else "FIXED_RUNNER","parent_task":parent["id"]} for suffix,operation,role,title,deps,paths in specs]
        steps={
            "patch.empty":["Đối chiếu screenshot TestForge AC07: nhánh rỗng đã loại bỏ app-table-basic và phần tổng số.","Sửa template để giữ điều khiển bảng và tổng 0 khi không có dữ liệu; giữ loading và nút thử lại.","Trả patch HTML theo anchor duy nhất, không thay test, quyền hoặc contract API."],
            "verify.candidate":["Đối chiếu SHA của frozen-cases.json với suite trước vòng sửa từ TestForge.","Chạy 13 testcase trên phương thức TypeScript thật với cùng dependencies đã kiểm soát.","Ghi báo cáo mới kèm source SHA; chỉ chuyển build khi 13/13 đạt."],
            "build":["Build AOT component Angular với profile API fixture và quyền chỉ đọc đã duyệt.","Đóng gói JS, CSS, font và icon cần dùng, loại asset của các module không thuộc demo.","Ghi SHA của archive và ba file source để ràng buộc bản triển khai mới."],
            "deploy":["Chuyển archive theo từng phần có giới hạn, đối chiếu đúng SHA trước khi khởi động.","Khởi động Angular và API fixture trong Sandbox mới rồi kiểm tra HTTP binding.","Trả URL preview riêng, mã Sandbox và thời hạn truy cập theo artifact mới."],
            "testforge.recheck":["Chạy lại nguyên bảy bước TestForge trên đúng Sandbox và artifact mới.","Kiểm tra tìm từ trang 3, phản hồi muộn, rỗng, lỗi, chỉ đọc và viewport 390px.","Lưu TraceRecorder và ảnh; giữ kết quả 6/7 lần đầu để đối chiếu với lần sau."],
        }
        for task in tasks:task["steps"]=steps[task["operation"]]
        for task in tasks:
            if not any(n["id"]==task["id"] for n in self.s["nodes"]):self.update(task["id"],"PENDING",title=task["title"],role=task["role"],depends_on=task["depends_on"],parent_task=parent["id"])
        self.s["followup_tasks"]=tasks;self.persist()
        async def fix():
            result=await self.driver.native_task(tasks[0],"TestForge độc lập đã phát hiện lỗi thật: khi tìm không có kết quả, UI mất phần tổng số 0. Sửa HTML để trạng thái rỗng giữ tổng số 0 và cơ chế hiển thị bảng/phân trang chuẩn. Ưu tiên giữ app-table-basic luôn render (nó có trạng thái no-result và tổng số sẵn), chỉ thêm nút Thử lại nếu cần. Không tạo phần tử giả chỉ để khớp selector; không thay testcase hoặc expected result. Không sửa TypeScript, API, quyền hay thao tác ghi. Trả JSON {\"edits\":[{\"path\":\"membership-list.component.html\",\"old\":\"đoạn nguyên văn duy nhất\",\"new\":\"đoạn mới\"}],\"summary\":\"...\"}.",{"context.md":self.context(tasks[0]),"testforge-finding.json":json.dumps(first,ensure_ascii=False),**self.sources()})
            return self.apply(result,[HTML])
        await self.followup(tasks[0],fix)
        async def verify():
            report=await self.verify()
            if report["passed"]!=report["total"]:raise RuntimeError("TNQD_REPAIR_PROTECTED_CHECKS_FAILED")
            return {"summary":"Bản sửa từ TestForge vẫn đạt 13 testcase đã khóa.",**report}
        await self.followup(tasks[1],verify)
        await self.followup(tasks[2],lambda:self.perform(tasks[2]))
        self.preview_generation="testforge-fix-1";self.s["preview_generation"]=self.preview_generation;self.persist()
        await self.followup(tasks[3],lambda:self.perform(tasks[3]))
        async def recheck():
            report=await self.browser_report()
            self.s["checks"]=[g for g in self.s["checks"] if g["id"]!="testforge"]+[self.browser_group(report,"testforge","TestForge · sau vòng TaskLoop sửa lỗi")];self.persist()
            if report.get("state")!="SUCCEEDED" or report.get("passed")!=report.get("total"):raise RuntimeError("TNQD_BROWSER_REPAIR_NOT_VERIFIED")
            return {**report,"native_summary":report.get("summary"),"summary":f"TestForge sau sửa đạt {report['passed']}/{report['total']}; giữ nguyên các bước kiểm tra."}
        return await self.followup(tasks[4],recheck)

    async def command(self, args, logname, cwd=None, timeout=360):
        env = {k:v for k,v in os.environ.items() if k.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT", "USERPROFILE"}}
        env["PATH"] = str(NODE.parent)+os.pathsep+env.get("PATH", "")
        with (self.directory / logname).open("wb") as log:
            proc = await asyncio.create_subprocess_exec(*map(str, args), cwd=str(cwd or self.candidate), env=env, stdout=log, stderr=log)
            try: return await asyncio.wait_for(proc.wait(), timeout)
            except asyncio.TimeoutError:
                proc.kill(); await proc.wait(); raise RuntimeError("TNQD_COMMAND_TIMEOUT")

    def apply(self, result, allowed):
        edits = result.get("edits", [])
        if not isinstance(edits, list) or not edits or len(edits) > 16:
            raise RuntimeError("TNQD_PATCH_FORMAT_REQUIRED")
        working = self.sources()
        for edit in edits:
            name, old, new = edit.get("path"), edit.get("old"), edit.get("new")
            if name not in allowed or not isinstance(old, str) or not old or not isinstance(new, str) or old == new or working[name].count(old) != 1:
                raise RuntimeError("TNQD_PATCH_SCOPE_OR_ANCHOR_INVALID")
            working[name] = working[name].replace(old, new, 1)
        for name in allowed:
                (self.candidate / MODULE / name).write_text(working[name], encoding="utf8",newline="\n")
        return {"summary": result.get("summary", "Đã áp dụng đề xuất code theo phạm vi task."), "changed_files": sorted({e["path"] for e in edits}), "hashes": {p:sha(working[p]) for p in allowed}}

    async def patch(self, task):
        allowed = task["write_paths"]
        focus = {
            "patch.pagination": "Sửa search() để khi giá trị bộ lọc đổi (so với lastAppliedQuery đã chuẩn hóa), pageIndex=0; khi onPageChange với cùng bộ lọc phải giữ đúng trang. Phải đúng cả lần đầu đang ở trang 3. Chỉ sửa logic phân trang, chưa sửa race/loading.",
            "patch.race": "Sửa search() chống HTTP trả muộn VÀ Promise authz.loadObjectPermissions.then trả muộn, request cũ không ghi đè listOfData/total/error/loading. Có sequence token tăng trước khi unsubscribe cũ và guard mọi callback, kể cả finalize. Giữ tương thích OnPush và cleanup khi destroy. Không sửa test.",
            "patch.loading": "Sửa template [loading] nhận isLoading thật. Bổ sung trạng thái tải/rỗng/lỗi chỉ nếu cần với thuộc tính đang có; không tham chiếu thuộc tính component chưa tồn tại. Không đổi quyền/thao tác ghi. Giữ phong cách VTS hiện tại. Chỉ sửa HTML/SCSS.",
        }[task["operation"]]
        result = await self.driver.native_task(task, focus+"\nTrả outputs/result.json dạng {\"summary\":\"...\",\"edits\":[{\"path\":\"tên file basename\",\"old\":\"đoạn nguyên văn duy nhất trong inputs\",\"new\":\"đoạn thay thế\"}]}. Đừng ghi cả source, đừng sửa inputs. Hãy dùng đoạn old đủ dài để khớp đúng một lần; giữ chính xác dấu cách và xuống dòng.", {"context.md": self.context(task), **self.sources()})
        return self.apply(result, allowed)

    async def tests(self, task):
        operation = task["operation"]
        expected = EXPECTED[operation]
        instruction = ("Bạn là Tester độc lập, dùng spec và source baseline, không thấy code candidate. Viết case descriptors cho bộ interpreter chạy phương thức TypeScript thật. "
          "Trả outputs/result.json {\"cases\":[{\"id\":\"AC01\",\"title\":\"tình huống cụ thể tiếng Việt\",\"given\":\"điều kiện đầu\",\"when\":\"thao tác\",\"then\":\"kết quả nghiệp vụ\",...expectedfields}]}. "
          "Phải có đúng các id và expected fields sau (không tự nới expected): "+json.dumps(expected, ensure_ascii=False)+
          ". AC12-BROWSER do TestForge thực thi viewport 390px; không tự báo PASS. AC11 là profile fixture chỉ đọc, không chứng nhận RBAC backend. Mỗi title/given/when/then ít nhất 12 ký tự.")
        result = await self.driver.native_task(task, instruction, {"context.md": self.context(task), "baseline.ts": self.sources(base=True)[TS]})
        cases = result.get("cases", [])
        if len(cases) != len(expected) or {c.get("id") for c in cases} != set(expected):
            raise RuntimeError("TNQD_CASE_COVERAGE_INVALID")
        for case in cases:
            if any(not isinstance(case.get(field), str) or len(case[field].strip()) < 12 for field in ("title", "given", "when", "then")):
                raise RuntimeError("TNQD_CASE_DETAIL_REQUIRED")
            if any(case.get(key) != value for key, value in expected[case["id"]].items()):
                raise RuntimeError("TNQD_CASE_EXPECTATION_CHANGED")
        self.suites[operation] = cases
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True)
        (self.directory / (operation+".json")).write_text(encoded, encoding="utf8")
        return {"summary": f"Đã khóa {len(cases)} testcase từ yêu cầu, chưa tính là kết quả test.", "suite_digest":sha(encoded), "cases": cases}

    async def verify(self, baseline=False):
        suite = self.directory / "frozen-cases.json"
        if sha(suite.read_bytes()) != self.s["test_suite_digest"]:
            raise RuntimeError("TNQD_FROZEN_TESTS_CHANGED")
        output = self.directory / ("baseline-checks.json" if baseline else "candidate-checks.json")
        code = await self.command([NODE, PROFILE/"component-checks.cjs", BASE if baseline else self.candidate, suite, output], output.stem+".log", timeout=60)
        if code not in (0, 1) or not output.exists(): raise RuntimeError("TNQD_COMPONENT_HARNESS_FAILED")
        report = json.loads(output.read_text(encoding="utf8"))
        group = {**report, "id": "baseline" if baseline else "candidate", "title": "Baseline · tái hiện trước cải tiến" if baseline else "Candidate · cùng bộ test đã khóa"}
        self.s["checks"] = [g for g in self.s["checks"] if g["id"] != group["id"]]+[group]; self.persist()
        return report

    async def perform(self, task):
        op = task["operation"]
        if op == "fixture":
            if not (BASE/"node_modules/typescript/package.json").exists(): raise RuntimeError("TNQD_WORKSPACE_NOT_PREPARED")
            if not (self.candidate/".pokedev-prepared.json").exists():
                await asyncio.to_thread(shutil.copytree, BASE, self.candidate, dirs_exist_ok=True, ignore=shutil.ignore_patterns("node_modules", "dist", ".angular", ".git"))
                import _winapi
                if not (self.candidate/"node_modules").exists():_winapi.CreateJunction(str(BASE/"node_modules"), str(self.candidate/"node_modules"))
                (self.candidate/".pokedev-prepared.json").write_text(json.dumps({"run_id":self.m["run_id"],"spec_digest":self.m["spec_digest"]}))
            for doc in self.m["documents"]:
                readback = await self.driver.memory("read", doc["id"], doc["revision"])
                if sha(readback["body"]) != doc["sha256"]: raise RuntimeError("TNQD_SPEC_CONTEXT_CHANGED")
            return {"summary":"Đã chuẩn bị snapshot Angular và đọc lại ba tài liệu từ Memory; fixture cố định 45 hồ sơ.", "baseline": {p:sha(s) for p,s in self.sources(base=True).items()}}
        if op.startswith("patch."): return await self.patch(task)
        if op.startswith("test."): return await self.tests(task)
        if op == "verify.merge":
            cases = [c for name in EXPECTED for c in self.suites[name]]
            frozen = json.dumps({"cases":cases}, ensure_ascii=False, sort_keys=True)
            (self.directory/"frozen-cases.json").write_text(frozen, encoding="utf8")
            self.s["test_suite_digest"] = sha(frozen); self.persist()
            return {"summary":"Đã nhận đủ ba nhánh code và ba nhánh test; khóa suite trước Verify.", "case_count":len(cases),"suite_digest":sha(frozen)}
        if op == "verify.baseline":
            report = await self.verify(True)
            if report["passed"] == report["total"]: raise RuntimeError("TNQD_BASELINE_DEFECT_NOT_REPRODUCED")
            if any("not defined" in c.get("error", "") or "is not a function" in c.get("error", "") for c in report["tests"]):
                raise RuntimeError("TNQD_BASELINE_HARNESS_DEPENDENCY_ERROR")
            return {"summary":f"Baseline tái hiện {report['total']-report['passed']} lỗi trên phương thức component thật.", **report}
        if op == "verify.candidate":
            for attempt in range(3):
                report = await self.verify()
                if report["passed"] == report["total"]: return {"summary":f"Candidate đạt {report['passed']}/{report['total']} kiểm tra cùng suite baseline.", **report}
                if attempt == 2: raise RuntimeError("TNQD_CANDIDATE_CHECKS_FAILED")
                identity = task["id"]+"-repair"+str(attempt+1)
                repair = {**task,"id":identity,"role":"coder","title":"Sửa lỗi Verify trên component, giữ nguyên suite đã khóa"}
                result = await self.driver.native_task(repair, "Sửa các lỗi sau bằng code component, tuyệt đối không sửa test. Đây là vòng phản hồi Verify thật. Trả JSON {\"edits\":[{\"path\":\"...\",\"old\":\"anchor nguyên văn duy nhất\",\"new\":\"...\"}],\"summary\":\"...\"}.\n"+json.dumps(report,ensure_ascii=False), {"context.md":self.context(task),**self.sources()})
                applied = self.apply(result, [TS, HTML, SCSS])
                self.update(identity,"DONE",completed_at=time.time(),summary=applied["summary"])
        if op == "build":
            checked=next(c for c in self.s["checks"] if c["id"]=="candidate")
            if checked["passed"]!=checked["total"] or checked["source_sha256"]!=self.source_hashes()[TS]:raise RuntimeError("TNQD_BUILD_SOURCE_NOT_VERIFIED")
            configure_profile(self.candidate)
            code = await self.command([NODE,"node_modules/@angular/cli/bin/ng.js","build","--configuration","pokedev-demo"],"angular-build.log",timeout=480)
            if code != 0 or not (self.build_dir/"index.html").exists(): raise RuntimeError("TNQD_ANGULAR_BUILD_FAILED")
            archive = self.directory/"tnqd-candidate.zip"
            packaged=package_artifact(self.build_dir,archive)
            self.s["artifact_sha256"] = packaged["sha256"]; self.persist()
            return {"summary":"Đã build Angular thật, đóng gói artifact có SHA riêng.","artifact_sha256":self.s["artifact_sha256"],"bytes":archive.stat().st_size,"asset_count":packaged["files"],"source_hashes":self.source_hashes()}
        if op == "review":
            diff = self.diff()
            result = await self.driver.native_task(task,"Review độc lập diff thật và báo cáo Verify/build, không sửa code. Trả outputs/result.json {\"approved\":true|false,\"findings\":[\"...\"],\"summary\":\"...\"}. Không coi component-method test là E2E hay quyền backend đã xác minh. Nếu lỗi chặn thì approved=false.",{ "context.md":self.context(task), "changes.diff":diff,"checks.json":json.dumps(self.s["checks"],ensure_ascii=False)})
            if result.get("approved") is not True: raise RuntimeError("TNQD_REVIEW_CHANGES_REQUIRED")
            self.s["review"] = result; return result
        if op == "deploy":
            identity = str(uuid5(UUID(self.m["run_id"]),"preview"+(":"+self.preview_generation if self.preview_generation else "")))
            archive = self.directory/"tnqd-candidate.zip"
            content = base64.b64encode(archive.read_bytes()).decode()
            chunks=[content[start:start+240000] for start in range(0,len(content),240000)]
            await self.driver.bridge("/previews/upload",{"preview_id":identity,"scope_id":self.m["scope_id"],"artifact_sha256":self.s["artifact_sha256"],"chunks":len(chunks),"bytes":archive.stat().st_size})
            for index,chunk in enumerate(chunks):
                await self.driver.bridge("/previews/"+identity+"/chunks",{"scope_id":self.m["scope_id"],"index":index,"data":chunk})
            receipt=await self.driver.bridge("/previews/"+identity+"/commit",{"scope_id":self.m["scope_id"]})
            for _ in range(900):
                self.s["preview"] = receipt; self.persist()
                if receipt["state"] not in {"DEPLOYING","VERIFYING"}: break
                await asyncio.sleep(2)
                receipt = await self.driver.bridge("/previews/"+identity+"?scope_id="+self.m["scope_id"])
            if receipt["state"] != "LIVE": raise RuntimeError("TNQD_SANDBOX_DEPLOY_FAILED")
            return {"summary":"Artifact Angular đã chạy trong Sandbox và qua HTTP smoke.","preview_id":identity,"artifact_sha256":receipt["artifact_sha256"]}
        if op == "testforge":
            if self.s.get("followup_tasks"):
                first=next(g for g in self.s["checks"] if g["id"]=="testforge-attempt-1")
                return await self.repair_browser(task,first)
            report=await self.browser_report()
            self.s["checks"]=[g for g in self.s["checks"] if g["id"]!="testforge"]+[self.browser_group(report)];self.persist()
            if report.get("state")=="FAILED" and report.get("total")==7 and {t["id"] for t in report.get("tests",[]) if t["status"]!="PASS"}=={"AC07-BROWSER"}:
                return await self.repair_browser(task,report)
            if report.get("state") != "SUCCEEDED" or report.get("passed",0) < 7: raise RuntimeError("TNQD_TESTFORGE_FAILED")
            return {**report,"native_summary":report.get("summary"),"summary":f"TestForge đạt {report['passed']}/{report['total']} bước trình duyệt thật."}
        if op == "documents":
            result = await self.driver.native_task(task,"Bổ sung tài liệu từ bằng chứng đã kiểm chứng. Trả JSON {\"updates\":[{\"id\":\"TNQD_PTYC\",\"append\":\"Markdown phụ lục mới...\"},{\"id\":\"TNQD_TKCT\",\"append\":\"...\"},{\"id\":\"TNQD_CSDL\",\"append\":\"...\"}]}. Mỗi append ít nhất 400 ký tự. Giữ nguyên phần yêu cầu đóng băng, chỉ thêm phụ lục triển khai/kiểm chứng. Phải nêu hash source/suite, baseline trước/candidate sau, cả phát hiện TestForge lần đầu và kết quả sau vòng sửa, API fixture và những phần Java/CSDL/RBAC chưa xác minh. Không đổi yêu cầu để khớp code.",{ "context.md":self.context(task),"evidence.json":json.dumps({"checks":self.s["checks"],"source":self.source_hashes(),"suite":self.s["test_suite_digest"],"preview":self.s["preview"]},ensure_ascii=False)})
            updates = result.get("updates",[])
            if len(updates)!=3 or {u.get("id") for u in updates}!={d["id"] for d in self.m["documents"]}: raise RuntimeError("TNQD_DOCUMENT_UPDATE_INVALID")
            docs=[]
            for original in self.m["documents"]:
                append = next(u["append"] for u in updates if u["id"]==original["id"])
                if not isinstance(append,str) or not 400<len(append)<10000: raise RuntimeError("TNQD_DOCUMENT_UPDATE_TOO_SHORT")
                body=original["body"]+"\n\n"+append
                docs.append({**original,"previous_body":original["body"],"body":body,"sha256":sha(body),"revision":"verified-"+self.m["run_id"][:8]})
            self.s["documents"]=docs; self.persist()
            return {"summary":"Đã bổ sung ba tài liệu bằng phụ lục triển khai và bằng chứng thật.","documents":[d["id"] for d in docs]}
        if op == "memory":
            self.driver.harness_memory_available=None
            for doc in self.s["documents"]:
                await self.driver.memory("publish",doc["id"],doc["revision"],doc["body"],"verified-workloop:"+self.m["run_id"])
                readback=await self.driver.memory("read",doc["id"],doc["revision"],context_id="new-agent-context:"+str(uuid4()))
                if sha(readback["body"])!=doc["sha256"]: raise RuntimeError("TNQD_UPDATED_MEMORY_READBACK_FAILED")
            return {"summary":"Đã lưu phiên bản tài liệu mới và đọc lại đúng nội dung trong context mới.","backend":self.s.get("memory_backend")}
        if op == "handover":
            if not self.s.get("parallel",{}).get("verified"): raise RuntimeError("TNQD_PARALLEL_EVIDENCE_REQUIRED")
            changes=[p for p,v in self.sources().items() if v!=self.sources(base=True)[p]]
            if not changes: raise RuntimeError("TNQD_PRODUCT_CHANGE_REQUIRED")
            diff=self.diff(); (self.directory/"tnqd-candidate.patch").write_text(diff,encoding="utf8")
            receipt={"summary":"Đã có bản cải tiến TNQD, kiểm thử trước/sau, Sandbox và tài liệu Memory cập nhật; chờ duyệt bàn giao.","changed_files":changes,"source_digest":sha(json.dumps(self.sources(),sort_keys=True)),"test_suite_digest":self.s["test_suite_digest"],"limitations":["Demo dùng 45 hồ sơ giả lập và quyền chỉ đọc; chưa nghiệm thu backend Java/CSDL/RBAC.","Cognee trên Harness chỉ được xác nhận nếu có receipt đọc lại; kho tài liệu PokeDev được ghi rõ riêng.","Chưa merge hoặc phát hành vào hệ thống TNQD đang dùng."]}
            self.s["handover"]=receipt;self.persist();return receipt
        raise RuntimeError("TNQD_OPERATION_UNSUPPORTED")

    def diff(self):
        patches=[]
        for name,current in self.sources().items():
            lines=difflib.unified_diff(self.sources(base=True)[name].splitlines(True),current.splitlines(True),fromfile="a/"+MODULE+"/"+name,tofile="b/"+MODULE+"/"+name)
            patches.append("".join(line if line.endswith("\n") else line+"\n\\ No newline at end of file\n" for line in lines))
        return "\n".join(patches)
