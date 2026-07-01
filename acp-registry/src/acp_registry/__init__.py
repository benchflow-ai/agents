"""Popular ACP-registry agents, adapted to BenchFlow.

Importing this package does not touch BenchFlow's registry. Call :func:`register`
to install the wired agents:

    import acp_registry
    acp_registry.register()                 # all wired agents
    acp_registry.register("qwen-code")       # a subset

Note: on a benchflow with entry-point autoload, merely *installing* this
distribution registers every wired agent automatically — benchflow discovers the
``benchflow.agents`` entry point (``acp_registry:register``) and invokes it at
import time (built-ins are never overwritten). Uninstall the distribution (or
run an older benchflow) to opt out.

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
