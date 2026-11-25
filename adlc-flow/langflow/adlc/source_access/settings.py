from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from .models import Closed, ConnectionId, SourceError, SourceGrant

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


def resolve_project_grant(principal_id, project_id, run_id, settings):
    row = settings.get("projects", {}).get(project_id)
    if row is None:
        msg = "SOURCE_SCOPE_DENIED"
        raise SourceError(msg)
    principals = row.get("principals")
    resources = row.get("resources", {})
    limits = row.get("locator_allowlists", {})
    if (
        not isinstance(principals, (list, tuple))
        or any(not isinstance(p, str) for p in principals)
        or not isinstance(resources, dict)
        or any(not isinstance(values, (list, tuple, set, frozenset)) for values in resources.values())
        or not isinstance(limits, dict)
        or any(
            key not in {f"{conn}:{resource}" for conn, values in resources.items() for resource in values}
            for key in limits
        )
        or any(not isinstance(values, dict) for values in limits.values())
    ):
        msg = "SOURCE_CONFIGURATION_INVALID"
        raise SourceError(msg)
    if principal_id not in principals:
        msg = "SOURCE_SCOPE_DENIED"
        raise SourceError(msg)
    if any(key != "table_id" for values in limits.values() for key in values):
        msg = "SOURCE_FIELD_SCOPE_UNSUPPORTED"
        raise SourceError(msg)
    return SourceGrant(
        project_id=project_id,
        run_id=run_id,
        principal_id=principal_id,
        resources=row.get("resources", {}),
        locator_allowlists=limits,
        max_reads=row.get("max_reads", 24),
        max_bytes=row.get("max_bytes", 500_000),
    )


def build_source_gateway(settings, secret_resolver, http_factory=None):
    import httpx

    from .credentials import GitHubAppTokens, LarkTenantTokens
    from .gateway import SourceGateway
    from .github import GitHubReader
    from .lark_base import LarkBaseReader
    from .lark_messages import LarkMessageReader

    factory = http_factory or httpx.AsyncClient
    readers, clients = {}, []
    try:
        # Validate and resolve everything before allocating any client.
        connections = [ConnectionSettings.model_validate(row) for row in settings.get("connections", ())]
        if len({row.connection_id for row in connections}) != len(connections):
            msg = "duplicate connection"
            raise ValueError(msg)
        secrets = [secret_resolver(row.private_key_secret_ref or row.app_secret_ref) for row in connections]
        if any(not isinstance(secret, str) or not secret for secret in secrets):
            msg = "missing secret"
            raise ValueError(msg)
        for row, secret in zip(connections, secrets, strict=True):
            origin = "https://api.github.com" if row.provider == "github" else "https://open.larksuite.com"
            client = factory(base_url=origin, timeout=15, follow_redirects=False, trust_env=False)
            clients.append(client)
            if row.provider == "github":
                tokens = GitHubAppTokens(client, row.app_id, secret, row.installation_id)
                reader = GitHubReader(client, tokens)
                for kind in ("github_file", "github_issue", "github_related_work"):
                    readers[row.connection_id, kind] = reader
            else:
                tokens = LarkTenantTokens(client, row.app_id, secret)
                readers[row.connection_id, "lark_thread"] = LarkMessageReader(client, tokens)
                reader = LarkBaseReader(client, tokens)
                for kind in ("lark_base_record", "lark_document"):
                    readers[row.connection_id, kind] = reader
    except Exception:
        msg = "SOURCE_CONNECTION_UNAVAILABLE"
        raise SourceError(msg) from None
    return SourceGateway(readers, clients=clients)
