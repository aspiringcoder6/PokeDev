import re

from .http import INVALID, LarkRead, LarkReader, canonical, decode_json, identifier, lark_evidence, obj, provider_id
from .models import Evidence, SourceError, SourceRef

_RESPONSE_INVALID = "SOURCE_RESPONSE_INVALID"
_OPERATORS = {
    "is",
    "isNot",
    "contains",
    "doesNotContain",
    "isEmpty",
    "isNotEmpty",
    "isGreater",
    "isLess",
    "isGreaterEqual",
    "isLessEqual",
}
_LAST_TEXT_BLOCK = 17
_SCOPE_DENIED = "SOURCE_SCOPE_DENIED"
_UNSUPPORTED_CONTENT = "SOURCE_UNSUPPORTED_CONTENT"
_ATTACHMENT = 17
_HYPERLINK = 15
_MAX_FILTER = 8192
_MAX_CONDITIONS = 20
_MAX_VALUES = 50
_MAX_VALUE = 512


def _filter(serialized: str) -> dict:
    if len(serialized) > _MAX_FILTER:
        raise SourceError(INVALID)
    parsed = decode_json(serialized, error_code=INVALID)
    if not isinstance(parsed, dict) or parsed.keys() != {"conjunction", "conditions"}:
        raise SourceError(INVALID)
    conditions = parsed["conditions"]
    if (
        parsed["conjunction"] not in ("and", "or")
        or not isinstance(conditions, list)
        or not 1 <= len(conditions) <= _MAX_CONDITIONS
    ):
        raise SourceError(INVALID)
    for condition in conditions:
        if not isinstance(condition, dict) or condition.keys() != {"field_name", "operator", "value"}:
            raise SourceError(INVALID)
        name, operator, values = condition["field_name"], condition["operator"], condition["value"]
        if (
            not isinstance(name, str)
            or not name
            or len(name) > _MAX_VALUE
            or not isinstance(operator, str)
            or operator not in _OPERATORS
            or not isinstance(values, list)
            or len(values) > _MAX_VALUES
            or any(not isinstance(v, str) or len(v) > _MAX_VALUE for v in values)
        ):
            raise SourceError(INVALID)
        if bool(values) == (operator in {"isEmpty", "isNotEmpty"}):
            raise SourceError(INVALID)
    return parsed


def _schema(fields: list[dict]) -> dict[str, dict]:
    result = {}
    field_ids = set()
    for field in fields:
        fid = provider_id(field.get("field_id"))
        name = field.get("field_name")
        if (
            not isinstance(name, str)
            or not name
            or name in result
            or fid in field_ids
            or type(field.get("type")) is not int
        ):
            raise SourceError(_RESPONSE_INVALID)
        field_ids.add(fid)
        result[name] = {"field_name": name, "field_id": fid, "type": field["type"]}
    return result


async def _attachments(read: LarkRead, cell: object, record: str, table: str, field: str, findings: list[str]) -> list:
    if not isinstance(cell, list):
        findings.append("attachment_metadata_unavailable")
        return []
    result = []
    for item in cell:
        attachment = obj(item)
        metadata = {k: attachment[k] for k in ("file_token", "name", "size", "type") if k in attachment}
        metadata.update({"kind": "base_attachment", "table_id": table, "record_id": record, "field_id": field})
        if not attachment.get("file_token"):
            findings.append("attachment_metadata_unavailable")
            result.append(metadata)
            continue
        token = provider_id(attachment["file_token"])
        binding = {"bitablePerm": {"tableId": table, "attachments": {field: {record: [token]}}}}
        mime = attachment.get("type")
        is_text = mime in ("text/plain", "text/markdown", "text/csv") or (
            mime in (None, "", "application/octet-stream")
            and str(attachment.get("name", "")).lower().endswith((".txt", ".md", ".csv"))
        )
        result.append(
            await read.attachment(
                f"drive/v1/medias/{token}/download",
                {"extra": canonical(binding)},
                is_text=is_text,
                metadata=metadata,
                findings=findings,
            )
        )
    return result


_DOCUMENT_LINK = re.compile(
    r"https://(?:[A-Za-z0-9-]+\.)+(?:larksuite\.com|feishu\.cn)/(docx|wiki)/([A-Za-z0-9_-]{1,256})/?(?:[?#][^\s]*)?"
)


def _linked_documents(cell: object, connection: str) -> list[SourceRef]:
    result = []
    for item in cell if isinstance(cell, list) else [cell]:
        url = item.get("link") if isinstance(item, dict) else item
        match = _DOCUMENT_LINK.fullmatch(url) if isinstance(url, str) else None
        if match:
            kind, resource = match.groups()
            result.append(
                SourceRef(
                    kind="lark_document",
                    connection_id=connection,
                    resource_id=resource,
                    locator={"wiki": "1"} if kind == "wiki" else {},
                )
            )
    return result


async def _record(
    read: LarkRead, item: dict, schema: dict, ref: SourceRef, findings: list[str], pending: list[SourceRef]
) -> dict:
    record = provider_id(item.get("record_id"))
    result = {
        k: item[k]
        for k in ("record_id", "created_by", "created_time", "last_modified_by", "last_modified_time", "revision")
        if k in item
    }
    result["fields"] = cells = {}
    if not isinstance(item.get("fields"), dict):
        findings.append("record_fields_unavailable")
        return result
    for name, cell in item["fields"].items():
        field = schema.get(name)
        if field is None:
            findings.append("unknown_record_field")
            continue
        if cell is not None and field["type"] == _ATTACHMENT:
            cells[name] = await _attachments(read, cell, record, ref.locator["table_id"], field["field_id"], findings)
        else:
            cells[name] = cell
            if cell and field["type"] == _HYPERLINK:
                pending.extend(_linked_documents(cell, ref.connection_id))
    return result


class LarkBaseReader(LarkReader):
    def start_read(self) -> "_LarkBaseRead":
        return _LarkBaseRead(self._start())

    async def read(self, ref: SourceRef) -> Evidence:
        return await self.start_read().read(ref)

    async def resolve_ref(self, ref: SourceRef) -> SourceRef:
        return await self.start_read().resolve_ref(ref)


class _LarkBaseRead:
    def __init__(self, transport: LarkRead):
        self._transport = transport

    async def resolve_ref(self, ref: SourceRef) -> SourceRef:
        if ref.kind != "lark_document" or "wiki" not in ref.locator:
            return ref
        if ref.revision is not None or ref.locator not in ({"wiki": "1"}, {"wiki": "1", "blocks": "1"}):
            raise SourceError(INVALID)
        token = identifier(ref.resource_id)
        data = await self._transport.data("wiki/v2/spaces/get_node", {"token": token})
        node = obj(data.get("node"))
        if node.get("node_token") != token:
            raise SourceError(_SCOPE_DENIED)
        if node.get("obj_type") != "docx":
            raise SourceError(_UNSUPPORTED_CONTENT)
        return ref.model_copy(
            update={
                "resource_id": provider_id(node.get("obj_token")),
                "locator": {k: v for k, v in ref.locator.items() if k != "wiki"},
            }
        )

    async def read(self, ref: SourceRef) -> Evidence:
        resource = identifier(ref.resource_id)
        if ref.revision is not None:
            raise SourceError(INVALID)
        read = self._transport
        if ref.kind == "lark_document":
            return await self._document(read, ref, resource)
        if ref.kind != "lark_base_record" or set(ref.locator) not in (
            {"table_id", "record_id"},
            {"table_id", "filter"},
        ):
            raise SourceError(INVALID)
        table = identifier(ref.locator["table_id"])
        query = _filter(ref.locator["filter"]) if "filter" in ref.locator else None
        record = None if query else identifier(ref.locator["record_id"])
        path = f"bitable/v1/apps/{resource}/tables/{table}"
        fields, cursor = await read.pages(path + "/fields")
        schema = _schema(fields)
        body = {"schema": list(schema.values()), "records": []}
        if cursor:
            body["continuation"] = {"schema": cursor}
            return lark_evidence(ref, body, ["schema_page_limit"])
        if query:
            if any(c["field_name"] not in schema for c in query["conditions"]):
                raise SourceError(INVALID)
            if not read.pages_left:
                return lark_evidence(ref, body, ["record_page_limit"])
            items, cursor = await read.pages(path + "/records/search", body={"filter": query, "automatic_fields": True})
        else:
            data = await read.data(f"{path}/records/{record}", {"automatic_fields": "true"})
            item = obj(data.get("record"))
            if item.get("record_id") != record:
                raise SourceError(_SCOPE_DENIED)
            items = [item]
        findings = []
        pending = []
        body["records"] = [await _record(read, item, schema, ref, findings, pending) for item in items]
        if cursor:
            body["continuation"] = {"records": cursor}
            findings.append("record_page_limit")
        return lark_evidence(ref, body, findings, pending_refs=pending, pending_reason="linked_content_not_collected")

    @staticmethod
    async def _document(read: LarkRead, ref: SourceRef, document: str) -> Evidence:
        path = f"docx/v1/documents/{document}"
        findings = []
        if not ref.locator:
            data = await read.data(path + "/raw_content")
            body = {k: data[k] for k in ("content", "revision_id") if k in data}
            if not isinstance(data.get("content"), str):
                findings.append("document_text_unavailable")
        elif ref.locator == {"blocks": "1"}:
            blocks, cursor = await read.pages(path + "/blocks")
            body = {"blocks": blocks}
            if cursor:
                body["continuation"] = {"blocks": cursor}
                findings.append("block_page_limit")
            for block in blocks:
                provider_id(block.get("block_id"))
                if not _readable_block(block):
                    findings.append("block_content_unparsed")
        else:
            # An alias can only be read through the gateway's separate authorized-object dispatch.
            raise SourceError(INVALID)
        return lark_evidence(ref, body, findings)


def _readable_block(block: dict) -> bool:
    # Text blocks 1..17 include Page, headings, lists, code, quote, equation and todo.
    kind = block.get("block_type")
    if type(kind) is not int or not 1 <= kind <= _LAST_TEXT_BLOCK:
        return False
    content = [
        v for k, v in block.items() if k not in {"block_id", "block_type", "parent_id", "children", "comment_ids"}
    ]
    if len(content) != 1 or not isinstance(content[0], dict) or not isinstance(content[0].get("elements"), list):
        return False
    return all(
        isinstance(el, dict) and isinstance(el.get("text_run"), dict) and isinstance(el["text_run"].get("content"), str)
        for el in content[0]["elements"]
    )
