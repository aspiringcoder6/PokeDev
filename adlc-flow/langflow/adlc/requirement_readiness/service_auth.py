import hashlib
import hmac
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ServicePrincipal:
    id: str
    projects: frozenset[str]
    purposes: frozenset[str]
    credential_digest: str = ""

    def require(self, purpose, project_id):
        if purpose not in self.purposes or project_id not in self.projects:
            raise ValueError("READINESS_FORBIDDEN")


def authenticate_bearer(header, bindings):
    if not isinstance(header, str) or not re.fullmatch(r"Bearer [A-Za-z0-9._~+/-]{16,512}=*", header):
        raise ValueError("READINESS_UNAUTHENTICATED")
    digest = hashlib.sha256(header[7:].encode()).hexdigest()
    matched = None
    for row in bindings.get("credentials", ()):
        if hmac.compare_digest(digest, row["sha256"]):
            matched = row
    if matched is None:
        raise ValueError("READINESS_UNAUTHENTICATED")
    return ServicePrincipal(
        matched["principal_id"], frozenset(matched["projects"]), frozenset(matched["purposes"]), digest
    )


def revalidate_principal(principal, bindings):
    for row in bindings.get("credentials", ()):
        if hmac.compare_digest(principal.credential_digest, row["sha256"]) and row["principal_id"] == principal.id:
            return ServicePrincipal(
                row["principal_id"], frozenset(row["projects"]), frozenset(row["purposes"]), row["sha256"]
            )
    raise ValueError("READINESS_FORBIDDEN")
