from __future__ import annotations

import json
import os
import selectors
import signal
import subprocess
import threading
import time
from dataclasses import replace
from typing import Any

from .contracts import (
    AvailabilityResult,
    CallResult,
    Mode,
    PROTOCOL_VERSION,
    Provenance,
    ServerSpec,
    SidecarError,
)

_SENSITIVE_MARKERS = (
    "ACCESS_KEY",
    "API_KEY",
    "AUTH",
    "CREDENTIAL",
    "PASSWORD",
    "PRIVATE_KEY",
    "SECRET",
    "TOKEN",
)
_INHERITED_ENVIRONMENT = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "TZ",
    }
)
_MAX_INTERLEAVED_NOTIFICATIONS = 32


class _Failure(Exception):
    def __init__(self, error_class: str, *, returned_bytes: int = 0) -> None:
        self.error_class = error_class
        self.returned_bytes = returned_bytes
        super().__init__(error_class)


class LocalMcpClient:
    """One-process, one-request-at-a-time newline-delimited JSON-RPC client."""

    def __init__(self, spec: ServerSpec) -> None:
        self.spec = spec
        self._process: subprocess.Popen[bytes] | None = None
        self._buffer = bytearray()
        self._next_id = 1
        self._lock = threading.RLock()
        self._availability: AvailabilityResult | None = None
        self._server_name = spec.expected_name
        self._server_version = spec.expected_version

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def __enter__(self) -> LocalMcpClient:
        self.start()
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def start(self) -> AvailabilityResult:
        with self._lock:
            if self._availability is not None:
                if (
                    not self._availability.available
                    and self.spec.mode is Mode.REQUIRED
                ):
                    raise SidecarError(
                        self.spec.expected_name,
                        self._availability.provenance.error_class or "Unavailable",
                    )
                return self._availability
            started = time.perf_counter()
            returned_bytes = 0
            try:
                self._spawn()
                initialized, size = self._request(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "codexteam-local-mcp", "version": "0.1"},
                    },
                )
                returned_bytes += size
                self._validate_identity(initialized)
                self._notify("notifications/initialized", {})
                listed, size = self._request("tools/list", {})
                returned_bytes += size
                tools = self._validate_tools(listed)
                provenance = self._provenance(
                    "tools/list", started, returned_bytes=returned_bytes
                )
                self._availability = AvailabilityResult(True, tools, provenance)
            except _Failure as exc:
                self.close()
                provenance = self._provenance(
                    "tools/list",
                    started,
                    returned_bytes=returned_bytes + exc.returned_bytes,
                    error_class=exc.error_class,
                )
                self._availability = AvailabilityResult(False, (), provenance)
                if self.spec.mode is Mode.REQUIRED:
                    raise SidecarError(self.spec.expected_name, exc.error_class) from None
            return self._availability

    def call(self, tool: str, arguments: dict[str, Any]) -> CallResult:
        with self._lock:
            availability = self.start()
            started = time.perf_counter()
            if not availability.available:
                provenance = replace(availability.provenance, tool=tool)
                return CallResult(False, None, provenance)
            if tool not in self.spec.allowed_tools:
                return self._call_failure(tool, started, "AllowlistError")
            if not isinstance(arguments, dict):
                return self._call_failure(tool, started, "ArgumentError")
            try:
                result, returned_bytes = self._request(
                    "tools/call", {"name": tool, "arguments": arguments}
                )
                if "structuredContent" not in result and "content" not in result:
                    raise _Failure("MalformedResponse", returned_bytes=returned_bytes)
                content = result.get("structuredContent", result.get("content"))
                source_bytes, cache_hit = _query_stats(content)
                if result.get("isError") is True:
                    return self._call_failure(
                        tool,
                        started,
                        "ToolError",
                        returned_bytes=returned_bytes,
                        source_bytes=source_bytes,
                        cache_hit=cache_hit,
                    )
                provenance = self._provenance(
                    tool,
                    started,
                    returned_bytes=returned_bytes,
                    source_bytes=source_bytes,
                    cache_hit=cache_hit,
                )
                return CallResult(True, content, provenance)
            except _Failure as exc:
                self.close()
                return self._call_failure(
                    tool,
                    started,
                    exc.error_class,
                    returned_bytes=exc.returned_bytes,
                )

    def close(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
            self._buffer.clear()
            if process is None:
                return
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=1.0)
            else:
                process.wait()
            if process.stdout is not None:
                process.stdout.close()

    def _spawn(self) -> None:
        try:
            self._process = subprocess.Popen(
                self.spec.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self.spec.cwd,
                env=_sanitized_environment(self.spec.environment),
                shell=False,
                start_new_session=True,
            )
        except (OSError, ValueError):
            raise _Failure("StartError") from None

    def _request(self, method: str, params: dict[str, Any]) -> tuple[dict[str, Any], int]:
        request_id = self._next_id
        self._next_id += 1
        self._write(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        )
        deadline = time.monotonic() + self.spec.timeout_seconds
        returned_bytes = 0
        for _ in range(_MAX_INTERLEAVED_NOTIFICATIONS + 1):
            raw = self._readline(deadline)
            returned_bytes += len(raw)
            if returned_bytes > self.spec.max_response_bytes:
                raise _Failure("ResponseTooLarge", returned_bytes=returned_bytes)
            try:
                response = json.loads(raw, parse_constant=_reject_json_constant)
            except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
                raise _Failure(
                    "MalformedResponse", returned_bytes=returned_bytes
                ) from None
            if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
                raise _Failure("MalformedResponse", returned_bytes=returned_bytes)
            if "id" not in response and isinstance(response.get("method"), str):
                continue
            response_id = response.get("id")
            if (
                isinstance(response_id, bool)
                or not isinstance(response_id, (str, int))
                or response_id != request_id
            ):
                raise _Failure("ResponseIdError", returned_bytes=returned_bytes)
            if "error" in response:
                raise _Failure("JsonRpcError", returned_bytes=returned_bytes)
            result = response.get("result")
            if not isinstance(result, dict):
                raise _Failure("MalformedResponse", returned_bytes=returned_bytes)
            return result, returned_bytes
        raise _Failure("NotificationLimit", returned_bytes=returned_bytes)

    def _notify(self, method: str, params: dict[str, Any]) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def _write(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise _Failure("ProcessExited")
        payload = _bounded_json_request(message, self.spec.max_request_bytes)
        descriptor = process.stdin.fileno()
        deadline = time.monotonic() + self.spec.timeout_seconds
        selector = selectors.DefaultSelector()
        try:
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_WRITE)
            written = 0
            while written < len(payload):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise _Failure("Timeout")
                try:
                    count = os.write(descriptor, payload[written:])
                except BlockingIOError:
                    continue
                if count <= 0:
                    raise _Failure("ProcessExited")
                written += count
        except _Failure:
            raise
        except (BrokenPipeError, OSError):
            raise _Failure("ProcessExited") from None
        finally:
            selector.close()

    def _readline(self, deadline: float) -> bytes:
        process = self._process
        if process is None or process.stdout is None:
            raise _Failure("ProcessExited")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while True:
                newline = self._buffer.find(b"\n")
                if newline >= 0:
                    if newline + 1 > self.spec.max_response_bytes:
                        raise _Failure(
                            "ResponseTooLarge", returned_bytes=len(self._buffer)
                        )
                    line = bytes(self._buffer[: newline + 1])
                    del self._buffer[: newline + 1]
                    return line
                if len(self._buffer) >= self.spec.max_response_bytes:
                    raise _Failure(
                        "ResponseTooLarge", returned_bytes=len(self._buffer)
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _Failure("Timeout")
                if not selector.select(remaining):
                    raise _Failure("Timeout")
                chunk = os.read(process.stdout.fileno(), 65_536)
                if not chunk:
                    raise _Failure("EarlyEof")
                self._buffer.extend(chunk)
        finally:
            selector.close()

    def _validate_identity(self, initialized: dict[str, Any]) -> None:
        if initialized.get("protocolVersion") != PROTOCOL_VERSION:
            raise _Failure("ProtocolVersionError")
        info = initialized.get("serverInfo")
        if not isinstance(info, dict):
            raise _Failure("IdentityError")
        name = info.get("name")
        version = info.get("version")
        if not isinstance(name, str) or not isinstance(version, str):
            raise _Failure("IdentityError")
        if name != self.spec.expected_name or version != self.spec.expected_version:
            raise _Failure("IdentityError")
        self._server_name = name
        self._server_version = version

    def _validate_tools(self, listed: dict[str, Any]) -> tuple[str, ...]:
        definitions = listed.get("tools")
        if not isinstance(definitions, list):
            raise _Failure("ToolCatalogError")
        names: list[str] = []
        for definition in definitions:
            if not isinstance(definition, dict):
                raise _Failure("ToolCatalogError")
            name = definition.get("name")
            schema = definition.get("inputSchema")
            if not isinstance(name, str) or not name or not isinstance(schema, dict):
                raise _Failure("ToolCatalogError")
            annotations = definition.get("annotations")
            if name in self.spec.allowed_tools and (
                not isinstance(annotations, dict)
                or annotations.get("readOnlyHint") is not True
                or annotations.get("destructiveHint") is not False
            ):
                raise _Failure("ToolCatalogError")
            names.append(name)
        if len(set(names)) != len(names) or not self.spec.allowed_tools <= set(names):
            raise _Failure("ToolCatalogError")
        return tuple(names)

    def _call_failure(
        self,
        tool: str,
        started: float,
        error_class: str,
        *,
        returned_bytes: int = 0,
        source_bytes: int | None = None,
        cache_hit: bool | None = None,
    ) -> CallResult:
        provenance = self._provenance(
            tool,
            started,
            returned_bytes=returned_bytes,
            source_bytes=source_bytes,
            cache_hit=cache_hit,
            error_class=error_class,
        )
        if self.spec.mode is Mode.REQUIRED:
            raise SidecarError(self.spec.expected_name, error_class)
        return CallResult(False, None, provenance)

    def _provenance(
        self,
        tool: str,
        started: float,
        *,
        returned_bytes: int,
        source_bytes: int | None = None,
        cache_hit: bool | None = None,
        error_class: str | None = None,
    ) -> Provenance:
        return Provenance(
            server_name=self._server_name,
            server_version=self._server_version,
            tool=tool,
            duration_ms=round((time.perf_counter() - started) * 1_000, 3),
            returned_bytes=returned_bytes,
            source_bytes=source_bytes,
            cache_hit=cache_hit,
            error_class=error_class,
        )


def _sanitized_environment(overrides: tuple[tuple[str, str], ...]) -> dict[str, str]:
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in _INHERITED_ENVIRONMENT
        and not _sensitive_environment_name(name)
    }
    environment.update(
        {
            name: value
            for name, value in overrides
            if not _sensitive_environment_name(name)
        }
    )
    return environment


def _sensitive_environment_name(name: str) -> bool:
    upper = name.upper()
    return upper == "NO_PROXY" or upper.endswith("_PROXY") or any(
        marker in upper for marker in _SENSITIVE_MARKERS
    )


def _query_stats(content: Any) -> tuple[int | None, bool | None]:
    if not isinstance(content, dict):
        return None, None
    stats = content.get("query_stats")
    if not isinstance(stats, dict):
        return None, None
    source_bytes = stats.get("source_bytes")
    cache_hit = stats.get("cache_hit")
    if isinstance(source_bytes, bool) or not isinstance(source_bytes, int):
        source_bytes = None
    if not isinstance(cache_hit, bool):
        cache_hit = None
    return source_bytes, cache_hit


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _bounded_json_request(message: dict[str, Any], maximum: int) -> bytes:
    encoder = json.JSONEncoder(
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        check_circular=True,
    )
    chunks: list[bytes] = []
    size = 1
    try:
        for text in encoder.iterencode(message):
            chunk = text.encode("utf-8")
            size += len(chunk)
            if size > maximum:
                raise _Failure("RequestTooLarge")
            chunks.append(chunk)
    except _Failure:
        raise
    except (TypeError, ValueError):
        raise _Failure("ArgumentError") from None
    return b"".join(chunks) + b"\n"
