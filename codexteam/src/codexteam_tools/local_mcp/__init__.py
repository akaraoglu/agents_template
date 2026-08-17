"""Experimental, isolated local MCP sidecar."""

from .adapters import context_server_spec, local_docs_server_spec
from .client import LocalMcpClient
from .contracts import (
    AvailabilityResult,
    CallResult,
    Mode,
    Provenance,
    ServerSpec,
    SidecarError,
)

__all__ = [
    "AvailabilityResult",
    "CallResult",
    "LocalMcpClient",
    "Mode",
    "Provenance",
    "ServerSpec",
    "SidecarError",
    "context_server_spec",
    "local_docs_server_spec",
]
