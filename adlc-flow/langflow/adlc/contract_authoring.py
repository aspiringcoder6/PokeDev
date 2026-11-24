"""Explicit H5B package activation, independent of standard Harness coding."""

import os


def contract_authoring_enabled() -> bool:
    return all(
        os.getenv(name, "").strip().lower() in {"true", "1", "yes", "on"}
        for name in ("ADLC_CONTRACTS_ENABLED", "ADLC_CONTRACT_AUTHORING_ENABLED")
    )
