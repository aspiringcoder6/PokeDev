import pytest
from pydantic import ValidationError

from langflow.adlc.requirement_readiness.models import ContextSnapshot, NormalizedInput, PipelineConfig


@pytest.mark.parametrize("value", [0, -1, True, 3.5, "3"])
def test_invalid_round_configuration(value):
    with pytest.raises(ValidationError):
        PipelineConfig(max_context_rounds=value)


def test_snapshot_rejects_forged_digest():
    request = NormalizedInput(request_id="q", project_id="p", requirement="Read inputs")
    snapshot = ContextSnapshot.from_input(request, [])
    with pytest.raises(ValidationError):
        ContextSnapshot.model_validate(snapshot.model_dump() | {"digest": "forged"})
