"""Strict ``{{root.path}}`` template resolution for ADLC task inputs.

A full-string reference like ``"{{task.coding.output}}"`` resolves to the
referenced value with its original type; references embedded inside a longer
string substitute as text. Unknown roots, paths, or indexes raise
:class:`TemplateResolutionError` so coordinators fail fast instead of
dispatching partially bound requests.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

TEMPLATE_PATTERN = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")
_ROOT_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*$")


class TemplateResolutionError(ValueError):
    """Raised when a template reference cannot be resolved strictly."""

    def __init__(self, reference: str, reason: str) -> None:
        self.reference = reference
        self.reason = reason
        super().__init__(f"Cannot resolve template {reference!r}: {reason}")


def resolve_templates(value: Any, *, roots: Mapping[str, Any]) -> Any:
    """Deep-resolve every ``{{root.path}}`` reference inside the value."""
    if isinstance(value, str):
        return _resolve_string(value, roots)
    if isinstance(value, dict):
        return {key: resolve_templates(item, roots=roots) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_templates(item, roots=roots) for item in value]
    return value


def _resolve_string(value: str, roots: Mapping[str, Any]) -> Any:
    matches = list(TEMPLATE_PATTERN.finditer(value))
    if not matches:
        return value
    if len(matches) == 1 and matches[0].span() == (0, len(value)):
        return _resolve_reference(matches[0].group(1), roots)
    resolved = value
    for match in matches:
        resolved = resolved.replace(match.group(0), str(_resolve_reference(match.group(1), roots)))
    return resolved


def _resolve_reference(reference: str, roots: Mapping[str, Any]) -> Any:
    segments = reference.split(".")
    root_name = segments[0]
    if not _ROOT_NAME_PATTERN.fullmatch(root_name):
        raise TemplateResolutionError(reference, "invalid root name")
    if root_name not in roots:
        raise TemplateResolutionError(reference, f"unknown root {root_name!r}")
    current: Any = roots[root_name]
    walked: list[str] = [root_name]
    for segment in segments[1:]:
        current = _drill(current, segment, reference, walked)
        walked.append(segment)
    return current


def _drill(current: Any, segment: str, reference: str, walked: list[str]) -> Any:
    if isinstance(current, Mapping):
        if segment not in current:
            raise TemplateResolutionError(reference, f"missing key {'.'.join([*walked, segment])!r}")
        return current[segment]
    if isinstance(current, list):
        if not segment.isdigit():
            raise TemplateResolutionError(reference, f"list index expected at {'.'.join([*walked, segment])!r}")
        index = int(segment)
        if index >= len(current):
            raise TemplateResolutionError(reference, f"list index {index} out of range at {'.'.join(walked)!r}")
        return current[index]
    raise TemplateResolutionError(reference, f"{'.'.join(walked)!r} is not a container")
