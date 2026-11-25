import re

from .http import INVALID, LarkRead, LarkReader, decode_json, identifier, lark_evidence, obj, provider_id
from .models import Evidence, SourceError, SourceRef

_SCOPE_DENIED = "SOURCE_SCOPE_DENIED"
_RESPONSE_INVALID = "SOURCE_RESPONSE_INVALID"
_NOT_FOUND = "SOURCE_NOT_FOUND"
_HISTORY = "im/v1/messages"


def _bounds(ref: SourceRef) -> dict[str, str]:
    keys = ref.locator.keys()
    if (
        ref.kind != "lark_thread"
        or ref.revision is not None
        or not keys
        or keys - {"thread_id", "start_time", "end_time"}
    ):
        raise SourceError(INVALID)
    identifier(ref.resource_id)
    bounds = {key: ref.locator[key] for key in ("start_time", "end_time") if key in keys}
    if "thread_id" not in keys and bounds.keys() != {"start_time", "end_time"}:
        raise SourceError(INVALID)
    if any(not re.fullmatch(r"[0-9]{1,12}", value) for value in bounds.values()):
        raise SourceError(INVALID)
    if bounds.keys() == {"start_time", "end_time"} and int(bounds["start_time"]) > int(bounds["end_time"]):
        raise SourceError(INVALID)
    return bounds


def _check_chat(item: dict, chat: str) -> None:
    if item.get("chat_id") != chat:
        raise SourceError(_SCOPE_DENIED)


def _millis(value: object) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,16}", value):
        raise SourceError(_RESPONSE_INVALID)
    return int(value)


async def _message(read: LarkRead, item: dict, findings: list[str]) -> dict:
    mid = provider_id(item.get("message_id"))
    kept = {
        k: item[k]
        for k in (
            "message_id",
            "chat_id",
            "thread_id",
            "root_id",
            "parent_id",
            "sender",
            "create_time",
            "update_time",
            "msg_type",
            "deleted",
            "updated",
            "mentions",
            "upper_message_id",
        )
        if k in item
    }
    if not isinstance(item.get("sender"), dict) or not item["sender"].get("id"):
        findings.append("message_sender_unavailable")
    if item.get("deleted"):
        findings.append("message_deleted")
        return kept
    body = item.get("body")
    content = body.get("content") if isinstance(body, dict) else None
    if not isinstance(content, str):
        findings.append("message_content_unavailable")
        return kept
    try:
        parsed = obj(decode_json(content))
    except SourceError:
        findings.append("message_content_unparsed")
        return {**kept, "raw_content": content}
    kind = item.get("msg_type")
    if not isinstance(kind, str):
        raise SourceError(_RESPONSE_INVALID)
    if kind in {"file", "image", "audio", "media", "sticker"}:
        key = parsed.get("image_key" if kind == "image" else "file_key")
        metadata = {k: parsed[k] for k in ("file_name", "file_key", "image_key", "duration") if k in parsed}
        metadata.update({"kind": "message_resource", "message_id": mid})
        if key is None:
            findings.append("message_attachment_unavailable")
            kept["attachment"] = metadata
        else:
            key = provider_id(key)
            text_file = kind == "file" and str(parsed.get("file_name", "")).lower().endswith((".txt", ".md", ".csv"))
            kept["attachment"] = await read.attachment(
                f"{_HISTORY}/{mid}/resources/{key}",
                {"type": "image" if kind == "image" else "file"},
                is_text=text_file,
                metadata=metadata,
                findings=findings,
            )
    else:
        kept["content"] = parsed
        if kind == "text":
            if not isinstance(parsed.get("text"), str) or not parsed["text"]:
                findings.append("message_content_unavailable")
        else:
            # Preserve rich posts/cards and references for inspection without claiming full extraction.
            findings.append("message_content_unparsed")
    return kept


class LarkMessageReader(LarkReader):
    async def read(self, ref: SourceRef) -> Evidence:
        bounds = _bounds(ref)
        read = self._start()
        chat = ref.resource_id
        thread = ref.locator.get("thread_id")
        chat_query = {"container_id_type": "chat", "container_id": chat}
        findings = []
        if thread is None:
            # Older roots may have replies inside the requested window. Enumerate roots
            # without a lower time bound; bounded pagination stays explicitly incomplete.
            items, cursor = await read.pages(_HISTORY, chat_query)
        else:
            identifier(thread)

            def is_root(item: dict) -> bool:
                _check_chat(item, chat)
                return (
                    item.get("thread_id") == thread
                    and item.get("root_id") in (None, "", item.get("message_id"))
                    and not item.get("parent_id")
                )

            roots, cursor = await read.pages(_HISTORY, chat_query, stop_when=is_root)
            if not roots:
                if cursor is None:
                    raise SourceError(_NOT_FOUND)
                return lark_evidence(
                    ref, {"messages": [], "continuation": {"chat_roots": cursor}}, ["thread_root_not_bound"]
                )
            if len(roots) != 1:
                raise SourceError(_RESPONSE_INVALID)
            root = roots[0]
            root_id = provider_id(root.get("message_id"))
            replies = []
            if read.pages_left:
                replies, cursor = await read.pages(_HISTORY, {"container_id_type": "thread", "container_id": thread})
            else:
                findings.append("page_limit")
            for reply in replies:
                _check_chat(reply, chat)
                if (
                    reply.get("thread_id") != thread
                    or (reply.get("message_id") != root_id and reply.get("root_id") != root_id)
                    or (reply.get("message_id") == root_id and reply.get("root_id") not in (None, "", root_id))
                ):
                    raise SourceError(_SCOPE_DENIED)
            items = [root, *(reply for reply in replies if reply.get("message_id") != root_id)]

        for item in items:
            _check_chat(item, chat)
        messages = []
        pending = []
        for item in items:
            stamp = _millis(item.get("create_time"))
            if thread is None and item.get("thread_id") and stamp < (int(bounds["end_time"]) + 1) * 1000:
                pending.append(
                    ref.model_copy(update={"locator": {**bounds, "thread_id": provider_id(item["thread_id"])}})
                )
            if ("start_time" in bounds and stamp < int(bounds["start_time"]) * 1000) or (
                "end_time" in bounds and stamp >= (int(bounds["end_time"]) + 1) * 1000
            ):
                continue
            messages.append(await _message(read, item, findings))
        body = {"messages": messages}
        if cursor:
            body["continuation"] = {"messages": cursor}
            findings.append("page_limit")
        return lark_evidence(ref, body, findings, pending_refs=pending, pending_reason="thread_replies_not_collected")
