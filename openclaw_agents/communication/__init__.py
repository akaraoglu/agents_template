"""Communication helpers for the OpenClaw control plane."""

from .topic_router import RouteContext, TopicRouter
from .zulip_client import ZulipApiClient, ZulipApiError, ZulipCredentials, load_zuliprc
from .zulip_gateway import (
    DispatchPlan,
    GatewayEvent,
    GatewayResult,
    InboundEnvelope,
    SchemaValidator,
    ZulipGateway,
    load_gateway_config,
)

__all__ = [
    "DispatchPlan",
    "GatewayEvent",
    "GatewayResult",
    "InboundEnvelope",
    "RouteContext",
    "SchemaValidator",
    "TopicRouter",
    "ZulipApiClient",
    "ZulipApiError",
    "ZulipCredentials",
    "ZulipGateway",
    "load_gateway_config",
    "load_zuliprc",
]


def __getattr__(name: str):
    if name == "GatewayService":
        from .zulip_gateway_service import GatewayService

        return GatewayService
    raise AttributeError(name)
