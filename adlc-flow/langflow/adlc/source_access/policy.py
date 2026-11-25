from .models import SourceError, SourceGrant, SourceRef


def authorize(grant: SourceGrant, ref: SourceRef) -> None:
    if ref.resource_id not in grant.resources.get(ref.connection_id, frozenset()):
        raise SourceError("SOURCE_SCOPE_DENIED")
    if any(key in ref.locator for key in ("token", "base_url", "authorization")):
        raise SourceError("SOURCE_ARGUMENTS_INVALID")
    key = ref.connection_id + ":" + ref.resource_id
    for locator_key, allowed in grant.locator_allowlists.get(key, {}).items():
        if ref.locator.get(locator_key) not in allowed:
            raise SourceError("SOURCE_SCOPE_DENIED")
