"""Bound native inputs without truncating approved context or granted source files."""

import hashlib
import json


def context_parts(text, limit=150000):
    parts, raw = {}, text.encode("utf8")
    while raw:
        chunk = raw[:limit].decode("utf8", errors="ignore")
        if not chunk:
            raise ValueError("LIVE_NATIVE_CONTEXT_LIMIT")
        name = "context.md" if not parts else f"context-extra-{len(parts):02}.md"
        parts[name] = chunk
        raw = raw[len(chunk.encode("utf8")):]
    return parts or {"context.md": ""}


def pack_sources(inputs, source_sets, *, required_paths=(), wire_limit=1450000, optional_budget=250000):
    """Each available path points to one complete file; optional context may yield.

    The SDK serializes HTTP bodies with ensure_ascii=True, so measure that wire
    representation too. Keep headroom below the bridge's 1.5MB request limit.
    """
    result, required = dict(inputs), set(required_paths)
    index = {"version": 1, "sources": {}, "optional_omitted": 0}
    entries = [(prefix, path, body, prefix != "source" or path in required)
        for prefix, files in source_sets for path, body in files.items()]
    entries.sort(key=lambda row: not row[3])
    active_limit = wire_limit
    optional_started = False

    def sync():
        result["source-index.json"] = json.dumps(index, ensure_ascii=False)
        return (len(result["source-index.json"].encode("utf8")) <= 180000
            and len(json.dumps({"inputs": result}).encode("utf8")) <= active_limit)

    if any(len(value.encode("utf8")) > 180000 for value in result.values()) or not sync():
        raise ValueError("LIVE_NATIVE_CONTEXT_LIMIT")
    for position, (prefix, path, body, mandatory) in enumerate(entries):
        if not mandatory and not optional_started:
            optional_started = True
            active_limit = min(wire_limit, len(json.dumps({"inputs": result}).encode("utf8")) + optional_budget)
        name = f"{prefix}-file-{position:04}.txt"
        namespace = index["sources"].setdefault(prefix, {})
        namespace[path] = {"input": name, "sha256": hashlib.sha256(body.encode("utf8")).hexdigest()}
        result[name] = body
        if len(body.encode("utf8")) > 180000 or not sync():
            del result[name]
            del namespace[path]
            if mandatory:
                raise ValueError("LIVE_NATIVE_CONTEXT_LIMIT")
            index["optional_omitted"] += 1
            sync()
    if not sync():
        raise ValueError("LIVE_NATIVE_CONTEXT_LIMIT")
    return result
