"""Canonical JSON and digest helpers for immutable ADLC authoring objects."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from pydantic import BaseModel

if TYPE_CHECKING:
    from langflow.adlc.blueprints.models import NodePackageDefinition


def _json_compatible(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_compatible(value.model_dump(mode="json", exclude_none=False))
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON-compatible data deterministically as UTF-8."""
    return json.dumps(
        _json_compatible(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def sha256_digest(value: Any) -> str:
    """Return an ADLC-formatted SHA-256 digest for canonical JSON."""
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def package_content_digest(package: NodePackageDefinition) -> str:
    """Hash every persisted package-definition field."""
    return sha256_digest(package)
