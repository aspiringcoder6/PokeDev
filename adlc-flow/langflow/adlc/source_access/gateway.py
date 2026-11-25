from collections.abc import Mapping, Sequence

from .models import (
    Evidence,
    Kind,
    Reader,
    ReferenceResolver,
    RevisionReader,
    ScopedReader,
    SourceError,
    SourceGrant,
    SourceRef,
    is_git_sha,
    make_evidence,
)
from .policy import authorize

_ARGUMENTS_INVALID = "SOURCE_ARGUMENTS_INVALID"
_CONNECTION_UNAVAILABLE = "SOURCE_CONNECTION_UNAVAILABLE"
_CONTEXT_LIMIT = "SOURCE_CONTEXT_LIMIT"
_READ_LIMIT = "SOURCE_READ_LIMIT"
_RESPONSE_INVALID = "SOURCE_RESPONSE_INVALID"


class SourceGateway:
    def __init__(self, readers: Mapping[tuple[str, Kind], Reader], *, clients=()):
        self.readers = readers
        self._clients = tuple(clients)

    async def aclose(self):
        for client in self._clients:
            await client.aclose()

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
            registered = reader
            if isinstance(reader, ScopedReader):
                reader = reader.start_read()
            actual = ref
            if isinstance(reader, ReferenceResolver):
                actual = await reader.resolve_ref(ref.model_copy(deep=True))
                if not isinstance(actual, SourceRef):
                    raise SourceError(_RESPONSE_INVALID)
                actual = actual.model_copy(deep=True)
                authorize(grant, actual)
                target = self.readers.get((actual.connection_id, actual.kind))
                if target is None:
                    raise SourceError(_CONNECTION_UNAVAILABLE)
                if target is not registered:
                    reader = target.start_read() if isinstance(target, ScopedReader) else target
            evidence = await reader.read(actual)
            size += len(evidence.body.encode("utf-8"))
            if size > grant.max_bytes:
                raise SourceError(_CONTEXT_LIMIT)
            if actual != ref:
                if evidence.source != actual:
                    raise SourceError(_RESPONSE_INVALID)
                evidence = make_evidence(
                    actual,
                    evidence.body,
                    evidence.version,
                    complete=evidence.complete,
                    requested_source=ref,
                    pending_refs=evidence.pending_refs,
                    incomplete_reasons=evidence.incomplete_reasons,
                ).model_copy(update={"fetched_at": evidence.fetched_at})
            result.append(evidence)

        return result
