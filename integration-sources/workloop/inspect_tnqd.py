"""Read only our TNQD receipts; optionally retry a fresh Memory health check."""
import asyncio
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sdk"))
from dotenv import dotenv_values
from dsh_web_sdk import DshClient, RetryConfig

async def main():
    env = dotenv_values(ROOT / ".env.vai-platform.local")
    async with DshClient(env["VAI_PLATFORM_URL"], env["VAI_PLATFORM_TOKEN"], retry=RetryConfig(max_attempts=1)) as client:
        if "plugins" in sys.argv:
            result=await client.http_get('/dsh-plugin-hub/installed')
            print(json.dumps({"plugins":[{"name":name,"version":result.get('versions',{}).get(name),"loaded":name in result.get('loaded',[])} for name in result.get('installed',{})]},ensure_ascii=False))
        elif "memory" in sys.argv:
            identity = str(uuid4())
            result = await client.http_post("/api/v1/pokedev-services/checks", {"check_id": identity, "service": "memory", "scope_id": "90a6bb43c0ae4883747dd0cdb02bb84acde6397235ce4faa53529128411b06ed"})
            for _ in range(15):
                if result["state"] != "RUNNING": break
                await asyncio.sleep(2)
                result = await client.http_get("/api/v1/pokedev-services/checks/"+identity)
            print(json.dumps(result, ensure_ascii=False))
        else:
            source = ROOT / "adlc-flow/data/tnqd-demo/runs/ce9de1ce-08e8-401d-b890-e322e4ad4718/planning/result.json"
            local = json.loads(source.read_text(encoding="utf8"))
            print(json.dumps({k: local.get(k) for k in ("state", "error_code", "updated_at")}, ensure_ascii=False))
            for node in local["nodes"]:
                print(json.dumps(node, ensure_ascii=False))
                if node.get("workspace"):
                    try:
                        route = "/api/taskloop/tasks?dir=" + __import__("urllib.parse", fromlist=["quote"]).quote(node["workspace"], safe="")
                        print(json.dumps(await client.http_get(route), ensure_ascii=False)[:3500])
                    except Exception as exc: print(type(exc).__name__)
                if node.get("session_id"):
                    from dsh_web_sdk.session import DshSession
                    session = DshSession(client, node["session_id"], None)
                    history = await session.history(max_messages=400)
                    final = []
                    for e in history:
                        if e.get("seq", 0) < 350 or e.get("type") not in {"assistant/message", "tool/call", "tool/result"}: continue
                        content = e.get("data", {}).get("message", {}).get("content", [])
                        selected = [{k: v for k, v in b.items() if k in {"type", "name", "toolName", "input", "text", "content", "isError"}} for b in content if b.get("type") != "reasoning"]
                        final.append({"seq": e.get("seq"), "type": e.get("type"), "blocks": selected})
                    print(json.dumps({"final_events": final[-10:]}, ensure_ascii=False)[:8000])
                    route = "/api/v1/pokedev-services/tnqd/runs/9a81c549-ede0-539a-ac6e-5fce2a6ae27d?scope_id=" + local["scope_id"] + "&node_id=" + node["id"]
                    try:
                        artifact = await client.http_get(route)
                        saved = source.parent / (node["id"]+".native-recovered.json")
                        saved.write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf8")
                        print(json.dumps({"recovered": node["id"], "keys": list(artifact["artifact"]), "sha256": artifact["sha256"]}))
                    except Exception as exc: print(type(exc).__name__)

if __name__ == "__main__": asyncio.run(main())

