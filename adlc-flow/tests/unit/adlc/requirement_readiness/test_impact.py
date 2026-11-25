import asyncio

import pytest

from langflow.adlc.requirement_readiness.impact import DualImpact, validate_impact_pair


def test_impact_agents_share_inputs_and_preserve_full_reports():
    async def scenario():
        calls = []

        class Catalog:
            def check_role(self, role):
                return type("Ready", (), {"ready": True})()

        class Agents:
            async def ask(self, role, snapshot, payload, operation_id):
                calls.append((snapshot, payload, operation_id))
                while len(calls) < 2:
                    await asyncio.sleep(0)
                return {
                    "analyst": "code" if role == "impact-code" else "requirements",
                    "snapshot_digest": "d",
                    "status": "complete",
                    "body": "Full native report\n| row | evidence |",
                    "evidence_ids": [],
                    "affected_items": [],
                    "blocking_findings": [],
                    "material_uncertainties": [],
                    "requires_authorization": False,
                }

        snapshot = {"run_id": "r", "digest": "d", "evidence": []}
        pair = await asyncio.wait_for(DualImpact(Agents(), Catalog()).analyze(snapshot, []), 1)
        assert calls[0][:2] == calls[1][:2]
        assert calls[0][2] != calls[1][2]
        assert pair[0].body == "Full native report\n| row | evidence |"
        with pytest.raises(ValueError, match="READINESS_IMPACT_INCOMPLETE"):
            validate_impact_pair(snapshot, (pair[0].model_copy(update={"status": "incomplete"}), pair[1]))

    asyncio.run(scenario())
