"""Control the owned demo through normal authenticated PokeDev APIs."""
from pathlib import Path
import json
import sys
import httpx
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[2]
def main():
    record=json.loads((ROOT/"adlc-flow/data/tnqd-live/demo-session.json").read_text(encoding="utf8"))
    env=dotenv_values(ROOT/".env.pokedev-login")
    with httpx.Client(base_url="http://127.0.0.1:7860",trust_env=False,timeout=60) as client:
        login=client.post("/api/v1/login",data={"username":env["POKE_DEV_USERNAME"],"password":env["POKE_DEV_PASSWORD"]});login.raise_for_status()
        client.headers["Authorization"]="Bearer "+login.json()["access_token"]
        path="/api/v1/adlc/deliveries/"+record["delivery_id"]+"/tnqd-demo"
        response=client.get(path,params={"cycle_id":record["cycle_id"]});response.raise_for_status()
        row=next(r for r in response.json()["runs"] if r["run_id"]==record["run_id"])
        if "execute" in sys.argv:
            response=client.post(path+"/execute",json={"cycle_id":record["cycle_id"],"run_id":record["run_id"],"plan_digest":row["plan"]["digest"]});response.raise_for_status();row=response.json()
        if "resume" in sys.argv:
            response=client.post(path+"/resume",json={"cycle_id":record["cycle_id"],"run_id":record["run_id"]});response.raise_for_status();row=response.json()
        (ROOT/"adlc-flow/data/tnqd-live/latest-ui-receipt.json").write_text(json.dumps(row,ensure_ascii=False),encoding="utf8")
        print(json.dumps({"state":row["state"],"phase":row["phase"],"nodes":[{k:n.get(k) for k in ("id","state","session_id","error_code")} for n in row["nodes"]],"parallel":row.get("parallel"),"checks":[{k:c.get(k) for k in ("id","total","passed")} for c in row.get("checks",[])],"preview":{k:row.get("preview",{}).get(k) for k in ("state","phase","url","uploaded_chunks","error_code")},"error_code":row.get("error_code")},ensure_ascii=False))
if __name__=="__main__":main()
