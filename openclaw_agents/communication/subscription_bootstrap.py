"""Subscription bootstrap helpers for required Zulip stream setup."""

from __future__ import annotations

from typing import Any

from .zulip_plugin import ZulipRuntimePlugin


def build_subscription_plan(config: dict[str, Any]) -> dict[str, list[str]]:
    return dict(config.get("required_subscriptions", {}))


def ensure_subscriptions(plugin: ZulipRuntimePlugin, config: dict[str, Any]) -> dict[str, Any]:
    return plugin.ensure_subscriptions(build_subscription_plan(config))
