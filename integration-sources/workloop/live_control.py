"""Inspect the acceptance run through the same authenticated PokeDev API used by the UI."""
from pathlib import Path
import json
import sys
from uuid import uuid4

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]


def main():
    record = json.loads((ROOT / "tmp/live-ui-run.json").read_text(encoding="utf8"))
    config = dotenv_values(ROOT / ".env.pokedev-login")
    with httpx.Client(base_url="http://127.0.0.1:7861", trust_env=False, timeout=60) as client:
        response = client.post("/api/v1/login", data={"username": config["POKE_DEV_USERNAME"], "password": config["POKE_DEV_PASSWORD"]})
        response.raise_for_status()
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        path = "/api/v1/adlc/live/runs/" + record["run_id"]
        response = client.get(path); response.raise_for_status(); row = response.json()
        if "reconcile" in sys.argv:
            response = client.post(path + "/reconcile")
            response.raise_for_status(); row = response.json()
        if "retry" in sys.argv:
            run_id = record.get("retry_run_id") or str(uuid4())
            record["retry_run_id"] = run_id
            (ROOT / "tmp/live-ui-run.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf8")
            response = client.post(path + "/retry", json={"run_id": run_id})
            response.raise_for_status(); row = response.json()
            record.setdefault("previous_run_ids", []).append(record["run_id"])
            record.update(run_id=row["run_id"], url="http://127.0.0.1:7861/work?project=" + row["project_id"] + "&run=" + row["run_id"])
            record.pop("retry_run_id", None)
            (ROOT / "tmp/live-ui-run.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf8")
        if "execute" in sys.argv:
            response = client.post(path + "/execute", json={"plan_digest": row["plan"]["digest"]})
            response.raise_for_status(); row = response.json()
        if "publish" in sys.argv:
            response = client.post(path + "/publish"); response.raise_for_status()
            print(json.dumps(response.json(), ensure_ascii=False)); return
        output = ROOT / "tmp/live-latest.json"
        output.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf8")
        print(json.dumps({"run_id": row["run_id"], "state": row["state"], "phase": row["phase"], "nodes": [{k: n.get(k) for k in ("id", "state", "session_id", "error_code")} for n in row["nodes"]], "error_code": row.get("error_code"), "parallel": row.get("parallel"), "checks": [{"title": g["title"], "passed": sum(t.get("passed") is True for t in g["tests"]), "total": len(g["tests"])} for g in row.get("checks", [])], "preview": row.get("preview"), "changed_files": row.get("changed_files", [])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
