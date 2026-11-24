"""Execute TNQD planning/tasks with the pinned, real Workloop DAG and native TaskLoop sessions."""
from __future__ import annotations
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[2]
path = Path(sys.argv[1]).resolve()
manifest = json.loads(path.read_text(encoding="utf8"))
directory = path.parent
runtime = ROOT / "adlc-flow/data/workloop/runtime/workloop/src"
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT / "adlc-flow"), str(runtime), str(runtime / "workloop/engine")]
os.environ["WORKLOOP_SRC"] = str(runtime)
os.environ["LANGFLOW_DATABASE_URL"] = "sqlite:///" + str(directory / "lfx.sqlite3").replace("\\", "/")
os.environ["WORKLOOP_TRACING"] = "0"
from dsh_web_sdk import DshClient, RetryConfig
from workloop.backend.processing import process
from workloop.backend.services.db import Store
from workloop.gateway.deepseek_harness.gateway import DshHarnessGateway
from workloop.engine.workloop_task import WorkloopTask
from lfx.schema.data import Data
from langflow.adlc.tnqd_plan import validate_plan, planner_prompt, digest, NATIVE_OPERATIONS
from langflow.adlc.tnqd_memory import ProjectDocumentMemory

BRIDGE = "/api/v1/pokedev-services/tnqd"
MODEL = {"provider": "netmind", "model": "zai-org/GLM-5.3-Flash"}
PROJECT = ROOT / "adlc-flow/data/tnqd-live"
MODULE = "src/app/modules/military-youth/membership-roster/components/membership-list"
snapshot = {k: manifest[k] for k in ("run_id", "scope_id", "phase")}
snapshot.update(state="PLANNING" if manifest["phase"] == "planning" else "RUNNING", nodes=[], events=[], documents=manifest.get("documents", []), checks=[], memory=[])
snapshot["started_at"] = time.time()
if (directory / "result.json").exists() and "--resume" in sys.argv:
    previous = json.loads((directory / "result.json").read_text(encoding="utf8"))
    if all(previous.get(k) == manifest[k] for k in ("run_id", "scope_id", "phase")):
        snapshot.update(previous)
        snapshot["recovered_at"] = time.time()
        snapshot["previous_error_code"] = snapshot.get("error_code")
        snapshot["error_code"] = None
        snapshot["state"] = "PLANNING" if manifest["phase"] == "planning" else "RUNNING"

def persist():
    snapshot["updated_at"] = time.time()
    temporary = directory / "result.tmp"
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf8")
    temporary.replace(directory / "result.json")

def node_update(identity, state=None, **fields):
    node = next((n for n in snapshot["nodes"] if n["id"] == identity), None)
    if node is None:
        node = {"id": identity, "state": "PENDING"}; snapshot["nodes"].append(node)
    node.update(fields)
    if state:
        node["state"] = state
        if state in {"RUNNING","DONE"}:node.pop("error_code",None);node.pop("blocked_by",None)
        snapshot["events"].append({"node": identity, "state": state, "at": time.time(), "seq": len(snapshot["events"])+1})
    persist()
    return node

class NativeGateway(DshHarnessGateway):
    def __init__(self, *args, node_id, **kwargs):
        self.node_id = node_id
        super().__init__(*args, **kwargs)
    async def _open_session(self, spec):
        ref = await super()._open_session(spec)
        node_update(self.node_id, session_id=ref.id, native_start_at=time.time())
        return ref
    async def _submit(self, spec, ref):
        await self.client.rpc("session/selectModel", {"request": {"sessionId": ref.id, **MODEL}})
        accepted = await ref.raw.prompt(self._prompt_of[spec.n])
        if accepted is not True:
            raise RuntimeError("TNQD_NATIVE_PROMPT_UNCONFIRMED")
        node_update(self.node_id, prompt_accepted_at=time.time(), prompt_digest=digest(self._prompt_of[spec.n]))

class Driver:
    def __init__(self, client):
        self.client = client
        self.contracts = {}
        self.outputs = {}
        self.native = []
        self.lanes = {"developer": asyncio.Semaphore(1), "tester": asyncio.Semaphore(1)}
        self.capacity = asyncio.Semaphore(2)
        self.context = ""
        self.document_memory = ProjectDocumentMemory(ROOT / "adlc-flow/data/tnqd-demo/project-memory.sqlite3")
        self.harness_memory_available = None
        self.spec_digest = manifest.get("spec_digest")
        self.bridge_id = str(uuid5(UUID(manifest["run_id"]), manifest["phase"]))
        self.activity_samples = []
        self.activity_seen = {}
        self.monitor_task = None
        self.heartbeat_task = None
    async def pending_approvals(self): return []
    async def close_all(self):
        if self.heartbeat_task:
            self.heartbeat_task.cancel();await asyncio.gather(self.heartbeat_task,return_exceptions=True)
            self.heartbeat_task=None
        if self.monitor_task:
            self.monitor_task.cancel()
            await asyncio.gather(self.monitor_task,return_exceptions=True)
            self.monitor_task=None
        for gateway in self.native:
            await gateway.close_all()
    async def heartbeat(self):
        while True:
            snapshot["worker_alive_at"]=time.time();snapshot["worker_pid"]=os.getpid();persist()
            await asyncio.sleep(5)
    async def monitor(self):
        from dsh_web_sdk.session import DshSession
        while True:
            try:
                rows={s["sessionId"]:s for s in await self.client.list_sessions()}
                active=[]
                observed=time.time()
                for node in snapshot["nodes"]:
                    sid=node.get("session_id")
                    if not sid or node.get("native_end_at") or not rows.get(sid,{}).get("running"): continue
                    history=await DshSession(self.client,sid,None).history(max_messages=8)
                    tools=[e for e in history if e.get("type")=="tool/call"]
                    if tools:self.activity_seen[sid]=max(e.get("seq",0) for e in tools)
                    active.append({"task":node["id"],"session_id":sid,"tool_seq":self.activity_seen.get(sid,0),"spec_digest":node.get("spec_digest")})
                if len(active)>1:
                    sample={"at":observed,"monotonic":time.monotonic(),"sessions":active}
                    self.activity_samples.append(sample)
                    (directory/"parallel-samples.json").write_text(json.dumps(self.activity_samples),encoding="utf8")
                    eligible=[p for p in self.activity_samples if len(p["sessions"])>=2 and all(s["tool_seq"] and s["spec_digest"]==self.spec_digest for s in p["sessions"])]
                    if len(eligible)>=2:
                        pair=sorted(s["task"] for s in eligible[-1]["sessions"])
                        matching=[p for p in eligible if sorted(s["task"] for s in p["sessions"])==pair]
                        overlap=matching[-1]["monotonic"]-matching[0]["monotonic"]
                        proof={"verified":overlap>=3,"overlap_seconds":round(overlap,3),"tasks":pair,"simultaneous_samples":len(matching),"kind":"HARNESS_RUNNING_AND_TOOL_ACTIVITY_SAME_OBSERVER_CLOCK"}
                        previous=snapshot.get("parallel",{})
                        if not previous.get("verified") or proof["verified"] and proof["overlap_seconds"]>previous.get("overlap_seconds",0):snapshot["parallel"]=proof
                        persist()
            except asyncio.CancelledError: raise
            except Exception: pass
            await asyncio.sleep(3)
    async def bridge(self, route, body=None):
        if body is None:
            return await self.client.http_get(BRIDGE + route, timeout=90)
        return await self.client.http_post(BRIDGE + route, body, timeout=180)
    async def memory(self, operation, document_id, revision, body=None, source_ref="",context_id=None):
        command = {"scope_id": manifest["scope_id"], "operation": operation, "document_id": document_id,
            "revision": revision, "caller_context_id": context_id or manifest["run_id"] + ":" + manifest["phase"], "source_ref": source_ref}
        if body is not None: command["body"] = body
        # Always keep versioned project documents. A remote outage is visible and never masquerades as Cognee.
        if operation == "publish":
            local = self.document_memory.publish(manifest["scope_id"], document_id, revision, body, source_ref)
        else:
            local = self.document_memory.read(manifest["scope_id"], document_id, revision, command["caller_context_id"])
        if self.harness_memory_available is not False:
            try:
                result = await self.bridge("/memory", command)
                self.harness_memory_available = True
            except Exception:
                self.harness_memory_available = False
                result = {**local, "harness_state": "UNAVAILABLE", "harness_error": "COGNEE_CONNECTION_UNAVAILABLE"}
        else:
            result = {**local, "harness_state": "UNAVAILABLE", "harness_error": "COGNEE_CONNECTION_UNAVAILABLE"}
        snapshot["memory_backend"] = result["mode"]
        if result.get("content_verified") is not True or hashlib.sha256(result["body"].encode()).hexdigest() != result["sha256"]:
            raise RuntimeError("TNQD_MEMORY_CONTENT_INVALID")
        snapshot["memory"].append({k: v for k, v in result.items() if k != "body"})
        persist()
        return result
    async def native_task(self, task, instructions, inputs):
        identity = task["id"]
        lane = self.lanes["tester" if task.get("operation", "").startswith("test.") else "developer"]
        node_update(identity, "WAITING_SLOT")
        async with lane, self.capacity:
            node_update(identity, "RUNNING", started_at=time.time(), spec_digest=self.spec_digest)
            prepared = await self.bridge("/runs", {"run_id": self.bridge_id, "scope_id": manifest["scope_id"], "nodes": [{"id": identity, "inputs": inputs}]})
            binding = next(n for n in prepared["nodes"] if n["id"] == identity)
            node_update(identity, workspace=binding["workspace"], context_receipt=binding["inputs"])
            gateway = NativeGateway(os.environ["DSH_URL"], os.environ["DSH_TOKEN"], root_workspace=binding["workspace"],
                node_id=identity, provider=MODEL["provider"], model=MODEL["model"], timeout_s=600, stall_s=600,
                max_rearms=0, workflow_name="tnqd", run_tag=manifest["run_id"][-8:])
            gateway.client.retry = RetryConfig(max_attempts=1)
            self.native.append(gateway)
            common = "\nĐọc inputs/context.md trước khi làm. Chỉ dùng thư mục task này; không subagent, không commit/push, không truy cập secret hoặc sửa dịch vụ khác. Viết JSON thuần vào outputs/result.json bằng tool filesystem, không chỉ in trong chat. Không sửa inputs. Cuối cùng hoàn tất contract TaskLoop."
            try:
                contract = await gateway.run_contract_task(name=identity, n="1", role=task.get("role", "coder"), brief=instructions+common, model=MODEL["model"])
                self.contracts[identity] = contract
                if contract.status not in {"DONE", "DONE_WITH_CONCERNS"}:
                    raise RuntimeError("TNQD_NATIVE_TASK_NOT_DONE")
                artifact = await self.bridge("/runs/" + self.bridge_id + "?scope_id=" + manifest["scope_id"] + "&node_id=" + identity)
                node_update(identity, native_end_at=time.time(), native_status=contract.status, artifact_digest=artifact["sha256"])
                return artifact["artifact"]
            finally:
                await gateway.close_all()
    async def plan_task(self, identity):
        source_dir = PROJECT / "tcct-fe-base" / MODULE
        source = {name: (source_dir/name).read_text(encoding="utf8") for name in ("membership-list.component.ts", "membership-list.component.html")}
        if identity == "P01":
            seed = (ROOT / "docs/demos/tnqd-memory-spec/phan_tich_yeu_cau.md").read_text(encoding="utf8")
            seed += "\n\nYêu cầu chủ project đã cho phép triển khai demo:\n" + manifest["requirement"]
            seed += "\n\nNguồn mã: tnqd-sut@791910a9d11c5884e057cf09cc07bd62c2175558. GET /military-youth/youths/filter; pageIndex khởi tạo 0, pageSize 20; debounce chưa reset trang; template loading=false; bước tải quyền dùng Promise. Đây là quan sát source, cần test baseline."
            seed_revision="seed-"+hashlib.sha256(seed.encode()).hexdigest()[:16]
            await self.memory("publish", "TNQD_BUSINESS", seed_revision, seed, "tnqd-sut@791910a9d11c5884e057cf09cc07bd62c2175558 + user-approved-demo")
            fetched = await self.memory("read", "TNQD_BUSINESS", seed_revision)
            inputs = {"context.md": "Memory backend: " + fetched["mode"] + "; graph verified: false\n\n" + fetched["body"], **source}
            for doc_id in ("TNQD_PTYC","TNQD_TKCT","TNQD_CSDL"):
                prior=self.document_memory.latest(manifest["scope_id"],doc_id,manifest["run_id"]+":BA-prior-context",verified_only=True)
                if prior:
                    inputs["context.md"]+="\n\n# Tài liệu đã bổ sung từ lượt trước (candidate chưa merge, chỉ làm context)\n"+prior["revision"]+"\nSHA: "+prior["sha256"]+"\n"+prior["body"]
                    snapshot["memory"].append({k:v for k,v in prior.items() if k!="body"})
            for name in ("phan_tich_yeu_cau", "thiet_ke_chi_tiet", "thiet_ke_csdl"):
                inputs[name+".md"] = (ROOT / "docs/demos/memoryTestDocs" / (name+".md")).read_text(encoding="utf8")
            instructions = """Bạn là BA. Dùng ngữ cảnh thực vừa đọc lại từ Memory theo backend ghi trong inputs/context.md và source để điền ba mẫu tài liệu inputs/*.md. Không gọi bộ nhớ project local là Cognee/GraphRAG.
Tạo outputs/result.json dạng {"documents":[{"id":"TNQD_PTYC","title":"Phân tích yêu cầu","body":"Markdown đầy đủ..."},{"id":"TNQD_TKCT","title":"Thiết kế chi tiết","body":"..."},{"id":"TNQD_CSDL","title":"Thiết kế CSDL","body":"..."}]}.
Giữ cấu trúc chính của mẫu, điền nghiệp vụ tìm kiếm nhân sự cụ thể, AC01–AC12, luồng chính/phụ và thiết kế response race cả Promise quyền.
Phân biệt quan sát source, yêu cầu cải tiến và nội dung chưa xác nhận. Không bịa tên bảng CSDL, quyền backend hoặc kết quả test.
Phạm vi demo build component Angular thật với API fixture 45 hồ sơ, không chứng nhận backend Java/CSDL. Tài liệu phải có nguồn commit, ngữ cảnh Memory và phần thiếu.
Mỗi tài liệu 1200–7000 ký tự, ưu tiên rõ ràng và đủ mục; body phải là nội dung đã điền chứ không chép dàn ý trống."""
            recovered = directory / "P01.native-recovered.json"
            if recovered.exists() and "--resume" in sys.argv:
                # Recover only a bound artifact already produced by this run's BA.
                record = json.loads(recovered.read_text(encoding="utf8"))
                live = await self.bridge("/runs/"+self.bridge_id+"?scope_id="+manifest["scope_id"]+"&node_id=P01")
                if record["sha256"] != live["sha256"] or not live["inputs_intact"]:
                    raise RuntimeError("TNQD_RECOVERY_ARTIFACT_CHANGED")
                result = live["artifact"]
                node_update(identity, "RUNNING", native_status="DONE", recovery_kind="BOUND_ARTIFACT_AND_NATIVE_TASKLOOP_TOOL_RECEIPT", artifact_digest=live["sha256"])
            else:
                result = await self.native_task({"id": identity, "role": "researcher"}, instructions, inputs)
            docs = result.get("documents", [])
            if len(docs) != 3 or {d.get("id") for d in docs} != {"TNQD_PTYC", "TNQD_TKCT", "TNQD_CSDL"}:
                raise RuntimeError("TNQD_DOCUMENT_BUNDLE_INVALID")
            for doc in docs:
                if not isinstance(doc.get("body"), str) or not 1000 < len(doc["body"]) <= 14000:
                    raise RuntimeError("TNQD_DOCUMENT_CONTENT_INVALID")
                doc.update(revision="spec-"+manifest["run_id"][:8], sha256=hashlib.sha256(doc["body"].encode()).hexdigest())
                await self.memory("publish", doc["id"], doc["revision"], doc["body"], "native-BA:"+manifest["run_id"])
            snapshot["documents"] = docs
            self.context = "\n\n".join(d["title"]+"\n"+d["body"] for d in docs)
            self.spec_digest = digest(docs)
            snapshot["spec_digest"] = self.spec_digest
            return {"document_ids": [d["id"] for d in docs], "spec_digest": self.spec_digest}
        inputs = {"context.md": self.context, **source}
        recovered = directory / "P02.native-recovered.json"
        if recovered.exists() and "--resume" in sys.argv:
            record = json.loads(recovered.read_text(encoding="utf8"))
            live = await self.bridge("/runs/"+self.bridge_id+"?scope_id="+manifest["scope_id"]+"&node_id=P02")
            if record["sha256"] != live["sha256"] or not live["inputs_intact"]: raise RuntimeError("TNQD_RECOVERY_ARTIFACT_CHANGED")
            result = live["artifact"]
            node_update(identity,"RUNNING",native_status="DONE",recovery_kind="BOUND_ARTIFACT_FROM_COMPLETED_NATIVE_CONTRACT",artifact_digest=live["sha256"])
        else:
            result = await self.native_task({"id": identity, "role": "researcher"}, planner_prompt(), inputs)
        plan = validate_plan(result)
        snapshot["plan"] = plan
        return {"plan_digest": plan["digest"], "task_count": len(plan["tasks"])}
    async def execute_task(self, task):
        identity = task["id"]
        try:
            missing = [p for p in task["depends_on"] if p not in self.outputs]
            if missing: raise RuntimeError("TNQD_REQUIRED_ARTIFACT_MISSING")
            if manifest["phase"] == "planning":
                result = await self.plan_task(identity)
            else:
                from tnqd_actions import Actions
                if not hasattr(self, "actions"):
                    self.actions = Actions(self, manifest, snapshot, directory, node_update, persist)
                cached=directory/(identity+".artifact.json")
                prior=next(n for n in snapshot["nodes"] if n["id"]==identity)
                if "--resume" in sys.argv and prior.get("state")=="DONE" and cached.exists():
                    result=json.loads(cached.read_text(encoding="utf8"))
                    if digest(result)!=prior.get("output_digest"):raise RuntimeError("TNQD_RECOVERY_OUTPUT_CHANGED")
                    self.outputs[identity]=result
                    self.actions.restore(task,result)
                    self.contracts.setdefault(identity,SimpleNamespace(status="DONE"))
                    return Data(data={"task":identity,"status":"DONE","artifact_digest":digest(result),"recovered":True})
                if task["operation"] not in NATIVE_OPERATIONS:
                    node_update(identity, "RUNNING", started_at=time.time(), input_tasks=task["depends_on"])
                result = await self.actions.perform(task)
            self.outputs[identity] = result
            (directory / (identity+".artifact.json")).write_text(json.dumps(result, ensure_ascii=False), encoding="utf8")
            node_update(identity, "DONE", completed_at=time.time(), summary=str(result.get("summary", "Đã nhận artifact và đối chiếu điều kiện hoàn tất.")), output_digest=digest(result))
            self.contracts.setdefault(identity, SimpleNamespace(status="DONE"))
            return Data(data={"task": identity, "status": "DONE", "artifact_digest": digest(result)})
        except Exception as error:
            code = str(error) if str(error).startswith("TNQD_") else "TNQD_TASK_FAILED_"+type(error).__name__
            node_update(identity, "FAILED", completed_at=time.time(), error_code=code)
            for descendant in self.definitions.values():
                if identity in descendant["depends_on"]:
                    node_update(descendant["id"], "BLOCKED", blocked_by=identity)
            raise

async def main():
    driver = None
    persist()
    try:
        definitions = ([{"id": "P01", "title": "Lấy nghiệp vụ từ Memory và soạn ba tài liệu TNQD", "role": "researcher", "depends_on": []},
                        {"id": "P02", "title": "Phân rã spec thành 17 task và dependency cụ thể", "role": "researcher", "depends_on": ["P01"]}]
                       if manifest["phase"] == "planning" else manifest["plan"]["tasks"])
        if len(definitions) > 24: raise RuntimeError("TNQD_NODE_LIMIT")
        async with DshClient(os.environ["DSH_URL"], os.environ["DSH_TOKEN"], timeout=60, retry=RetryConfig(max_attempts=1)) as client:
            driver = Driver(client)
            driver.heartbeat_task=asyncio.create_task(driver.heartbeat())
            if manifest["phase"]=="execution":driver.monitor_task=asyncio.create_task(driver.monitor())
            driver.definitions = {t["id"]: t for t in definitions}
            class Task(WorkloopTask):
                async def report_output(self):
                    return await driver.execute_task(driver.definitions[self._id])
            process.WorkloopTask = Task
            process.make_gateway = lambda *args, **kwargs: driver
            wf = {"name": "tnqd-"+manifest["phase"], "nodes": {t["id"]: "WorkloopTask" for t in definitions},
                  "config": {t["id"]: {"role": t["role"], "brief": t["title"]} for t in definitions},
                  "edges": [{"source_id": p, "source_output": "report", "target_id": t["id"], "target_input": "context"} for t in definitions for p in t["depends_on"]]}
            for task in definitions:
                prior=next((n for n in snapshot["nodes"] if n["id"]==task["id"]),{})
                state="PENDING" if "--resume" in sys.argv and prior.get("state")!="DONE" else None
                node_update(task["id"],state,title=task["title"], depends_on=task["depends_on"], operation=task.get("operation"), role=task["role"])
            store = Store(str(directory / "workloop.sqlite3"))
            runner = process.WorkflowRunner(store)
            job = store.create_job(wf["name"], 1, {"source": "PokeDev-TNQD", "run_id": manifest["run_id"]})
            snapshot["job_id"] = job; persist()
            await asyncio.wait_for(runner.run(job, wf, {"harness": {"kind": "tnqd-owned"}, "defaults": {"max_parallel": 2}, "model": MODEL}), timeout=3500)
            snapshot["engine_status"] = store.get_job(job)["status"]
            if len(driver.outputs) != len(definitions) or any(n["state"] != "DONE" for n in snapshot["nodes"]):
                raise RuntimeError("TNQD_INCOMPLETE_DAG")
            snapshot["state"] = "PLAN_READY" if manifest["phase"] == "planning" else "SUCCEEDED"
    except Exception as error:
        snapshot["state"] = "FAILED"
        snapshot["error_code"] = str(error) if str(error).startswith("TNQD_") else "TNQD_WORKFLOW_FAILED_"+type(error).__name__
        print(type(error).__name__, str(error)[:700], flush=True)
        import traceback
        traceback.print_exc()
    finally:
        if driver: await driver.close_all()
        snapshot["completed_at"] = time.time(); persist()

if __name__ == "__main__":
    asyncio.run(main())
