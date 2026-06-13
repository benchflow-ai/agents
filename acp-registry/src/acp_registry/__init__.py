"""Popular ACP-registry agents, adapted to BenchFlow.

Importing this package does not touch BenchFlow's registry. Call :func:`register`
to install the wired agents:

    import acp_registry
    acp_registry.register()                 # all wired agents
    acp_registry.register("qwen-code")       # a subset

Inspect the full classification of the ACP registry via the catalog:

    from acp_registry import ACP_AGENTS, by_status, WIRED, CATALOG
    for a in by_status(CATALOG):
        print(a.registry_id, a.reason)
"""

from .catalog import (
    ACP_AGENTS,
    BY_ID,
    CATALOG,
    NATIVE,
    OUT_OF_SCOPE,
    VENDOR_LOCKED,
    WIRED,
    AcpAgent,
    by_status,
    wired_agents,
)
from .register import register

__all__ = [
    "ACP_AGENTS",
    "BY_ID",
    "AcpAgent",
    "by_status",
    "wired_agents",
    "register",
    "NATIVE",
    "WIRED",
    "CATALOG",
    "VENDOR_LOCKED",
    "OUT_OF_SCOPE",
]
