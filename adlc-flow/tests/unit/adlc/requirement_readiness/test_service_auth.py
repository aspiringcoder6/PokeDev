import hashlib

import pytest

from langflow.adlc.requirement_readiness.service_auth import authenticate_bearer, revalidate_principal


def test_same_identity_credentials_do_not_share_projects_or_purposes():
    submit = "submit-token-123456789"
    select = "select-token-987654321"
    bindings = {
        "credentials": [
            {
                "sha256": hashlib.sha256(submit.encode()).hexdigest(),
                "principal_id": "svc",
                "projects": ["p1"],
                "purposes": ["submit"],
            },
            {
                "sha256": hashlib.sha256(select.encode()).hexdigest(),
                "principal_id": "svc",
                "projects": ["p2"],
                "purposes": ["select"],
            },
        ]
    }
    principal = revalidate_principal(authenticate_bearer("Bearer " + submit, bindings), bindings)
    principal.require("submit", "p1")
    with pytest.raises(ValueError, match="READINESS_FORBIDDEN"):
        principal.require("select", "p1")
    with pytest.raises(ValueError, match="READINESS_FORBIDDEN"):
        principal.require("submit", "p2")
    bindings["credentials"] = bindings["credentials"][1:]
    with pytest.raises(ValueError, match="READINESS_FORBIDDEN"):
        revalidate_principal(principal, bindings)
