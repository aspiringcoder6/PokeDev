from collections.abc import Mapping, Sequence

from .models import Evidence, Kind, Reader, SourceError, SourceGrant, SourceRef
from .policy import authorize


class SourceGateway:
    def __init__(self, readers: Mapping[tuple[str, Kind], Reader]):
        self.readers = readers

    async def read(self, grant: SourceGrant, refs: Sequence[SourceRef]) -> list[Evidence]:
        # Snapshot locators before authorization so they cannot change across reader awaits.
        batch = [ref.model_copy(deep=True) for ref in refs]
        for ref in batch:
            authorize(grant, ref)
        if len(batch) > grant.max_reads:
            raise SourceError("SOURCE_READ_LIMIT")

        result = []
        size = 0
        for ref in batch:
            reader = self.readers.get((ref.connection_id, ref.kind))
            if reader is None:
                raise SourceError("SOURCE_CONNECTION_UNAVAILABLE")
            evidence = await reader.read(ref)
            size += len(evidence.body.encode("utf-8"))
            if size > grant.max_bytes:
                raise SourceError("SOURCE_CONTEXT_LIMIT")
            result.append(evidence)

        return result
