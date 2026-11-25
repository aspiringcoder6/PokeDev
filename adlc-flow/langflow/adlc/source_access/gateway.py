from collections.abc import Mapping, Sequence

from .models import Evidence, Kind, Reader, RevisionReader, SourceError, SourceGrant, SourceRef, is_git_sha
from .policy import authorize

_ARGUMENTS_INVALID = "SOURCE_ARGUMENTS_INVALID"
_CONNECTION_UNAVAILABLE = "SOURCE_CONNECTION_UNAVAILABLE"
_CONTEXT_LIMIT = "SOURCE_CONTEXT_LIMIT"
_READ_LIMIT = "SOURCE_READ_LIMIT"
_RESPONSE_INVALID = "SOURCE_RESPONSE_INVALID"


class SourceGateway:
    def __init__(self, readers: Mapping[tuple[str, Kind], Reader]):
        self.readers = readers

    async def resolve_revision(self, grant: SourceGrant, ref: SourceRef) -> SourceRef:
        ref = ref.model_copy(deep=True)
        if ref.kind != "github_file":
            raise SourceError(_ARGUMENTS_INVALID)
        authorize(grant, ref)
        reader = self.readers.get((ref.connection_id, ref.kind))
        if not isinstance(reader, RevisionReader):
            raise SourceError(_CONNECTION_UNAVAILABLE)
        requested = "HEAD" if ref.revision is None else ref.revision
        revision = await reader.resolve_revision(ref.resource_id, requested)
        if not is_git_sha(revision):
            raise SourceError(_RESPONSE_INVALID)
        return ref.model_copy(update={"revision": revision.lower()})

    async def read(self, grant: SourceGrant, refs: Sequence[SourceRef]) -> list[Evidence]:
        # Snapshot locators before authorization so they cannot change across reader awaits.
        batch = [ref.model_copy(deep=True) for ref in refs]
        for ref in batch:
            authorize(grant, ref)
        if len(batch) > grant.max_reads:
            raise SourceError(_READ_LIMIT)

        result = []
        size = 0
        for ref in batch:
            reader = self.readers.get((ref.connection_id, ref.kind))
            if reader is None:
                raise SourceError(_CONNECTION_UNAVAILABLE)
            evidence = await reader.read(ref)
            size += len(evidence.body.encode("utf-8"))
            if size > grant.max_bytes:
                raise SourceError(_CONTEXT_LIMIT)
            result.append(evidence)

        return result
