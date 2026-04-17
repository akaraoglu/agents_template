"""Long-running foundation gateway service for the fresh Zulip bridge."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from openclaw_agents.runtime_paths import resolve_runtime_root
from openclaw_agents.communication.subscription_bootstrap import ensure_subscriptions
from openclaw_agents.communication.zulip_gateway import ZulipGateway
from openclaw_agents.communication.zulip_plugin import ZulipRuntimePlugin
from openclaw_agents.communication.zulip_plugin.client import ZulipApiError


class GatewayService:
    """Boot the shared live plugin and feed normalized events into the foundation gateway."""

    def __init__(
        self,
        *,
        config_path: str | Path | None = None,
        credentials_file: str | Path | None = None,
        enabled_agents: list[str] | None = None,
        verify_tls: bool | None = None,
        poll_interval_seconds: float | None = None,
        batch_size: int | None = None,
        ensure_subscriptions_on_start: bool | None = None,
        runtime_root: str | Path | None = None,
        plugin: ZulipRuntimePlugin | None = None,
        gateway: ZulipGateway | None = None,
    ) -> None:
        self.package_root = Path(__file__).resolve().parents[1]
        self.runtime_root = resolve_runtime_root(runtime_root)
        self.config_path = Path(config_path or (self.package_root / "communication" / "zulip_gateway_config.yaml"))
        self.config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        runtime_config = self.config.get("runtime") or {}

        self.plugin = plugin or ZulipRuntimePlugin.from_config(
            config_path=self.config_path,
            credentials_file=credentials_file,
            enabled_agents=enabled_agents,
            verify_tls=verify_tls,
        )
        self.gateway = gateway or ZulipGateway(base_dir=self.runtime_root, plugin=self.plugin)
        self.poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else float(runtime_config.get("poll_interval_seconds", 1.0))
        )
        self.batch_size = batch_size if batch_size is not None else int(runtime_config.get("batch_size", 50))
        self.ensure_subscriptions_on_start = (
            ensure_subscriptions_on_start
            if ensure_subscriptions_on_start is not None
            else bool(runtime_config.get("startup_subscriptions", True))
        )
        self._initialized = False
        self._stop_requested = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self.plugin.initialize(ensure_subscriptions=False)
        if self.ensure_subscriptions_on_start:
            ensure_subscriptions(self.plugin, self.config)
        self._initialized = True

    def check(self) -> dict[str, Any]:
        self.initialize()
        return {
            "config_path": str(self.config_path),
            "runtime_root": str(self.runtime_root),
            "plugin_health": self.plugin.health(),
            "identities": self.plugin.identify_bots(),
            "checkpoint": self.gateway.dedupe_store.get_checkpoint(),
        }

    def process_once(self) -> dict[str, Any]:
        self.initialize()
        processed: list[dict[str, Any]] = []
        background_results: list[dict[str, Any]] = []
        errors: list[str] = []
        try:
            events = self.plugin.poll_events(limit=self.batch_size)
        except ZulipApiError as exc:
            raise RuntimeError(f"zulip polling failed: {exc}") from exc

        for event in events:
            try:
                processed.append(self.gateway.process_event(event))
            except Exception as exc:  # pragma: no cover - runtime protection
                message = f"failed to process event {event.get('event_id')}: {exc}"
                print(message, file=sys.stderr)
                errors.append(message)

        try:
            background_results = self.gateway.process_pending_runtime_work(limit=self.batch_size)
        except Exception as exc:  # pragma: no cover - runtime protection
            message = f"failed to process pending runtime work: {exc}"
            print(message, file=sys.stderr)
            errors.append(message)

        maintenance = self.gateway.run_maintenance()

        return {
            "events_polled": len(events),
            "results": processed,
            "background_results": background_results,
            "maintenance": maintenance,
            "errors": errors,
            "plugin_health": self.plugin.health(),
        }

    def request_stop(self, *_args: Any) -> None:
        self._stop_requested = True

    def serve_forever(self) -> None:
        self.initialize()
        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)
        while not self._stop_requested:
            result = self.process_once()
            if result["errors"]:
                print(json.dumps(result, indent=2, sort_keys=True), file=sys.stderr)
            time.sleep(self.poll_interval_seconds)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the OpenClaw foundation Zulip gateway service")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("zulip_gateway_config.yaml")),
        help="Path to the foundation Zulip gateway config",
    )
    parser.add_argument("--credentials-file", help="Optional path to the local Zulip credential bundle")
    parser.add_argument("--enabled-agents", help="Comma-separated subset of enabled agents to boot")
    parser.add_argument("--poll-interval", type=float, help="Override the poll interval in seconds")
    parser.add_argument("--batch-size", type=int, help="Override the maximum events processed per poll")
    parser.add_argument("--skip-subscriptions", action="store_true", help="Skip stream subscription sync on startup")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for Zulip API calls")
    parser.add_argument("--runtime-root", help="Override the runtime root (defaults to OPENCLAW_ROOT or ~/workspace/clawspace)")
    parser.add_argument("--check", action="store_true", help="Validate config, credentials, and queue registration")
    parser.add_argument("--once", action="store_true", help="Run one poll cycle and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    enabled_agents = args.enabled_agents.split(",") if args.enabled_agents else None
    service = GatewayService(
        config_path=args.config,
        credentials_file=args.credentials_file,
        enabled_agents=enabled_agents,
        verify_tls=False if args.insecure else None,
        poll_interval_seconds=args.poll_interval,
        batch_size=args.batch_size,
        ensure_subscriptions_on_start=not args.skip_subscriptions,
        runtime_root=args.runtime_root,
    )
    if args.check:
        print(json.dumps(service.check(), indent=2, sort_keys=True))
        return 0
    if args.once:
        print(json.dumps(service.process_once(), indent=2, sort_keys=True))
        return 0
    service.serve_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
