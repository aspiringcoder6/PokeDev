from types import SimpleNamespace

import pytest

from langflow.adlc.requirement_readiness.assessment import effective_mode


def test_required_is_never_relaxed_and_uncertainty_vetoes_auto():
    clean=SimpleNamespace(status="complete",blocking_findings=(),material_uncertainties=(),requires_authorization=False)
    assessment=SimpleNamespace(material_disagreement=False,questions=())
    assert effective_mode(SimpleNamespace(mode="required"),assessment,(clean,clean))=="required"
    assert effective_mode(SimpleNamespace(mode="auto"),assessment,(clean,clean))=="auto"
    uncertain=SimpleNamespace(status="complete",blocking_findings=(),material_uncertainties=("unknown recovery",),requires_authorization=False)
    assert effective_mode(SimpleNamespace(mode="auto"),assessment,(clean,uncertain))=="required"
    blocker=SimpleNamespace(status="complete",blocking_findings=("missing essential context",))
    with pytest.raises(ValueError,match="READINESS_IMPACT_BLOCKED"):
        effective_mode(SimpleNamespace(mode="auto"),assessment,(clean,blocker))
