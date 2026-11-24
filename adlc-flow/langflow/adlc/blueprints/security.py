"""Secret-safety checks shared by package loading and stage resolution."""

from __future__ import annotations

_SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "client_secret",
    "credential",
    "credentials",
    "password",
    "private_key",
    "secret",
    "token",
}


def find_raw_secret_path(value: object, *, path: str = "") -> str | None:
    """Return the first secret-like field path outside a ``secret_refs`` subtree."""
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{path}/{key}"
            if key == "secret_refs":
                continue
            if key.lower() in _SENSITIVE_KEYS:
                return child_path
            nested_path = find_raw_secret_path(item, path=child_path)
            if nested_path is not None:
                return nested_path
    elif isinstance(value, list):
        for index, item in enumerate(value):
            nested_path = find_raw_secret_path(item, path=f"{path}/{index}")
            if nested_path is not None:
                return nested_path
    return None
