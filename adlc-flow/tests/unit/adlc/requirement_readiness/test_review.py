import asyncio

from langflow.adlc.requirement_readiness.review import DualReview, review_gate


class Catalog:
    def check_route(self, route):
        return type("Prereq", (), {"ready": True})()
    def validate_receipts(self,*args):
        return False


def test_concurrent_reviews_and_minority_blocker():
    async def scenario():
        seen=[]
        release=asyncio.Event()
        class Agent:
            async def ask(self,role,snapshot,payload,operation_id):
                seen.append((role,snapshot,operation_id))
                if len(seen)==2:
                    release.set()
                await asyncio.wait_for(release.wait(),1)
                return {"reviewer_id":role[-1],"snapshot_digest":"d","route":"openspec",
                        "status":"ready_for_spec" if role.endswith("a") else "needs_context","route_reason":"existing"}
        snapshot={"run_id":"r","digest":"d","evidence":[]}
        reports=await DualReview(Agent(),Catalog()).assess(snapshot)
        assert review_gate(snapshot,reports,Catalog())=="needs_context"
        assert seen[0][1]==seen[1][1]
        assert seen[0][2]!=seen[1][2]
        forged=reports[0].model_copy(update={"evidence":("invented",)})
        assert review_gate(snapshot,(forged,reports[1]),Catalog())=="blocked"
    asyncio.run(scenario())
