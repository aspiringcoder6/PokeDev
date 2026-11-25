from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .models import Closed, ConnectionId

_NonemptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_InstallationId = Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]


class ConnectionSettings(Closed):
    """Backend-owned identity and references to app credentials."""

    connection_id: ConnectionId
    provider: Literal["github", "lark"]
    app_id: _NonemptyString
    installation_id: _InstallationId | None = None
    tenant_id: _NonemptyString | None = None
    private_key_secret_ref: _NonemptyString | None = None
    app_secret_ref: _NonemptyString | None = None

    @model_validator(mode="after")
    def check_provider_credentials(self) -> ConnectionSettings:
        if self.provider == "github":
            if self.installation_id is None or self.private_key_secret_ref is None:
                msg = "GitHub connections require installation_id and private_key_secret_ref"
                raise ValueError(msg)
            if self.tenant_id is not None or self.app_secret_ref is not None:
                msg = "GitHub connections cannot specify Lark credentials"
                raise ValueError(msg)
        else:
            if self.tenant_id is None or self.app_secret_ref is None:
                msg = "Lark connections require tenant_id and app_secret_ref"
                raise ValueError(msg)
            if self.installation_id is not None or self.private_key_secret_ref is not None:
                msg = "Lark connections cannot specify GitHub credentials"
                raise ValueError(msg)
        return self
