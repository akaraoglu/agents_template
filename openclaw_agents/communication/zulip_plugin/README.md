# Zulip Runtime Plugin

This package provides the fresh Zulip transport/runtime boundary for the foundation bootstrap:
- inbound message normalization
- DM and stream/topic publish helpers
- reaction and upload helpers
- queue expiry and recreation hooks

Project-aware routing, confirmation policy, and canonical projection are handled by `communication/zulip_gateway.py`.

Two runtime modes are supported:
- in-memory mode for unit tests
- live mode booted from `communication/zulip_gateway_config.yaml` for Neo, AgentSmith, and Niaobe
