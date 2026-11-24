"""Feature flag for the orchestrator routing seam (plan package G1).

The flag is OFF by default. While it is off, every executor-routing
decision keeps the legacy path unchanged: ``adapter_ref`` values are
treated as literal executor service names and the mock runtime keeps
behaving exactly as before.

Package G2 will read this flag before consulting ``OrchestratorHost``
to resolve the reserved ``orchestrator:auto`` adapter reference; this
module only owns the flag itself (see ``docs/plans/adr-orchestrator-auto.md``).
"""

from __future__ import annotations

import os

ORCHESTRATOR_ROUTING_ENV = "ADLC_ORCHESTRATOR_ROUTING"

#: Reserved ``adapter_ref`` value meaning "the executor is chosen by the
#: OrchestratorHost when the plan is approved" (convention only in G1).
ORCHESTRATOR_AUTO_ADAPTER_REF = "orchestrator:auto"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def orchestrator_routing_enabled() -> bool:
    """Return whether orchestrator routing is explicitly enabled.

    Defaults to ``False``: unless the environment opts in with
    ``ADLC_ORCHESTRATOR_ROUTING=1|true|yes|on`` (case-insensitive), the
    legacy routing path runs 100% unchanged.
    """
    return os.getenv(ORCHESTRATOR_ROUTING_ENV, "").strip().lower() in _TRUE_VALUES


__all__ = [
    "ORCHESTRATOR_AUTO_ADAPTER_REF",
    "ORCHESTRATOR_ROUTING_ENV",
    "orchestrator_routing_enabled",
]
