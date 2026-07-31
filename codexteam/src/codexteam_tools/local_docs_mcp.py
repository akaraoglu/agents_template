from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from .local_docs import (
    DEFAULT_CHUNK_CHARS,
    MAX_READ_CHARS,
    MAX_SEARCH_RESULTS,
    LocalDocsError,
    LocalDocsReader,
)

PROTOCOL_VERSION = "2026-07-28"
LEGACY_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18")
SERVER_NAME = "local-docs"
SERVER_VERSION = "0.1.0"
SERVER_INSTRUCTIONS = (
    "Offline read-only documentation index with no network or write tools. "
    "Start with one focused search_docs query and a limit of at most 5. Do not "
    "guess source IDs: omit source_ids when the exact indexed ID is unknown. "
    "Use list_doc_sources only when an exact source or version filter is needed, "
    "then read_doc only for a returned locator when the excerpt is insufficient."
)


@dataclass(frozen=True)
class Tool:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]

    def definition(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        }


class LocalDocsMcpServer:
    def __init__(self, reader: LocalDocsReader) -> None:
        self.reader = reader
        self.legacy_protocol: str | None = None
        self.tools = (
            Tool(
                "list_doc_sources",
                "List Documentation Sources",
                "List approved offline documentation sources, installed versions, and index provenance.",
                _object_schema({}, required=()),
                self._list_doc_sources,
            ),
            Tool(
                "search_docs",
                "Search Local Documentation",
                "Search the offline index and return bounded excerpts with exact source IDs and locators.",
                _object_schema(
                    {
                        "query": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                        "source_ids": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "pattern": "^[a-z][a-z0-9-]{0,63}$",
                            },
                            "maxItems": 8,
                            "uniqueItems": True,
                        },
                        "version": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 80,
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": MAX_SEARCH_RESULTS,
                            "default": 5,
                        },
                    },
                    required=("query",),
                ),
                self._search_docs,
            ),
            Tool(
                "read_doc",
                "Read Indexed Documentation",
                "Read one indexed document by the exact source ID and locator returned by search_docs.",
                _object_schema(
                    {
                        "source_id": {
                            "type": "string",
                            "pattern": "^[a-z][a-z0-9-]{0,63}$",
                        },
                        "locator": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 400,
                        },
                        "max_chars": {
                            "type": "integer",
                            "minimum": 200,
                            "maximum": MAX_READ_CHARS,
                            "default": DEFAULT_CHUNK_CHARS,
                        },
                    },
                    required=("source_id", "locator"),
                ),
                self._read_doc,
            ),
        )
        self._tools_by_name = {tool.name: tool for tool in self.tools}

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, -32600, "Invalid Request")
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            return _error(request_id, -32600, "Invalid Request")
        if "id" not in message:
            if method in {"notifications/initialized", "notifications/cancelled"}:
                return None
            return None
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
            return _error(None, -32600, "Invalid Request")
        params = message.get("params", {})
        if not isinstance(params, dict):
            return _error(request_id, -32602, "Invalid params")
        if method == "initialize":
            return self._initialize_legacy(request_id, params)

        version_error = self._validate_modern_version(request_id, params)
        if version_error is not None:
            return version_error
        if method == "server/discover":
            return _result(request_id, self._discover())
        if method == "tools/list":
            return _result(request_id, self._list_tools())
        if method == "tools/call":
            return self._call_tool(request_id, params)
        return _error(request_id, -32601, f"Method not found: {method}")

    def serve(self, input_stream: TextIO, output_stream: TextIO) -> int:
        for raw_line in input_stream:
            try:
                message = json.loads(raw_line)
            except json.JSONDecodeError:
                response = _error(None, -32700, "Parse error")
            else:
                response = self.handle(message)
            if response is not None:
                output_stream.write(
                    json.dumps(
                        response,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    )
                    + "\n"
                )
                output_stream.flush()
        return 0

    def _discover(self) -> dict[str, Any]:
        return {
            "resultType": "complete",
            "supportedVersions": [PROTOCOL_VERSION],
            "capabilities": {"tools": {"listChanged": False}},
            "_meta": _server_meta(),
            "instructions": SERVER_INSTRUCTIONS,
            "ttlMs": 300_000,
            "cacheScope": "public",
        }

    def _list_tools(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "tools": [tool.definition() for tool in self.tools]
        }
        if self.legacy_protocol is None:
            value.update(
                {
                    "resultType": "complete",
                    "_meta": _server_meta(),
                    "ttlMs": 300_000,
                    "cacheScope": "public",
                }
            )
        return value

    def _call_tool(
        self,
        request_id: str | int,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _error(request_id, -32602, "Malformed tools/call request")
        tool = self._tools_by_name.get(name)
        if tool is None:
            return _error(request_id, -32602, f"Unknown tool: {name}")
        started = time.perf_counter()
        try:
            _validate_arguments(tool.input_schema, arguments)
            value = tool.handler(arguments)
        except (LocalDocsError, OSError, ValueError) as exc:
            value = _with_query_stats(
                {"error": str(exc)},
                started=started,
            )
            return _result(request_id, self._tool_result(value, is_error=True))
        value = _with_query_stats(value, started=started)
        return _result(request_id, self._tool_result(value, is_error=False))

    def _tool_result(
        self,
        value: dict[str, Any],
        *,
        is_error: bool,
    ) -> dict[str, Any]:
        result = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        value,
                        separators=(",", ":"),
                        sort_keys=True,
                        ensure_ascii=True,
                    ),
                }
            ],
            "structuredContent": value,
            "isError": is_error,
        }
        if self.legacy_protocol is None:
            result["resultType"] = "complete"
            result["_meta"] = _server_meta()
        return result

    def _initialize_legacy(
        self,
        request_id: str | int,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        if requested not in LEGACY_PROTOCOL_VERSIONS:
            return _error(
                request_id,
                -32602,
                f"This server supports modern MCP {PROTOCOL_VERSION}; "
                f"legacy compatibility is limited to {', '.join(LEGACY_PROTOCOL_VERSIONS)}",
            )
        self.legacy_protocol = str(requested)
        return _result(
            request_id,
            {
                "protocolVersion": requested,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": SERVER_NAME,
                    "version": SERVER_VERSION,
                },
                "instructions": SERVER_INSTRUCTIONS,
            },
        )

    def _validate_modern_version(
        self,
        request_id: str | int,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        if self.legacy_protocol is not None:
            return None
        meta = params.get("_meta")
        if not isinstance(meta, dict):
            return _error(request_id, -32602, "Missing required request _meta")
        requested = meta.get("io.modelcontextprotocol/protocolVersion")
        capabilities = meta.get("io.modelcontextprotocol/clientCapabilities")
        if requested != PROTOCOL_VERSION:
            return _error(
                request_id,
                -32022,
                "Unsupported protocol version",
                data={
                    "supported": [PROTOCOL_VERSION],
                    "requested": requested,
                },
            )
        if not isinstance(capabilities, dict):
            return _error(
                request_id,
                -32602,
                "Missing io.modelcontextprotocol/clientCapabilities",
            )
        return None

    def _list_doc_sources(self, arguments: dict[str, Any]) -> dict[str, Any]:
        del arguments
        return self.reader.list_doc_sources()

    def _search_docs(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.reader.search_docs(
            arguments["query"],
            source_ids=arguments.get("source_ids"),
            version=arguments.get("version"),
            limit=arguments.get("limit", 5),
        )

    def _read_doc(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.reader.read_doc(
            arguments["source_id"],
            arguments["locator"],
            max_chars=arguments.get("max_chars", DEFAULT_CHUNK_CHARS),
        )


def _object_schema(
    properties: dict[str, Any],
    *,
    required: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    properties = schema["properties"]
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise LocalDocsError(f"unknown arguments: {', '.join(unknown)}")
    missing = [name for name in schema["required"] if name not in arguments]
    if missing:
        raise LocalDocsError(f"missing arguments: {', '.join(missing)}")
    for name, value in arguments.items():
        field = properties[name]
        expected = field.get("type")
        if expected == "string":
            _validate_string(name, value, field)
        elif expected == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise LocalDocsError(f"{name} must be an integer")
            if value < field.get("minimum", value) or value > field.get(
                "maximum",
                value,
            ):
                raise LocalDocsError(f"{name} is outside the allowed range")
        elif expected == "array":
            if not isinstance(value, list):
                raise LocalDocsError(f"{name} must be an array")
            if len(value) > field.get("maxItems", len(value)):
                raise LocalDocsError(f"{name} has too many entries")
            if field.get("uniqueItems") and len(set(value)) != len(value):
                raise LocalDocsError(f"{name} must contain unique entries")
            item_schema = field.get("items", {})
            for item in value:
                _validate_string(name, item, item_schema)


def _validate_string(name: str, value: Any, field: dict[str, Any]) -> None:
    if not isinstance(value, str):
        raise LocalDocsError(f"{name} must be a string")
    if "minLength" in field and len(value) < field["minLength"]:
        raise LocalDocsError(f"{name} is too short")
    if "maxLength" in field and len(value) > field["maxLength"]:
        raise LocalDocsError(f"{name} is too long")
    if "pattern" in field and re.fullmatch(field["pattern"], value) is None:
        raise LocalDocsError(f"{name} has invalid format")


def _with_query_stats(
    value: dict[str, Any],
    *,
    started: float,
) -> dict[str, Any]:
    result = dict(value)
    source_bytes = result.get("source_bytes", 0)
    if isinstance(source_bytes, bool) or not isinstance(source_bytes, int):
        source_bytes = 0
    stats: dict[str, Any] = {
        "duration_ms": 0.0,
        "returned_bytes": 0,
        "source_bytes": source_bytes,
        "cache_hit": True,
    }
    result["query_stats"] = stats
    for _ in range(4):
        stats["duration_ms"] = round(
            (time.perf_counter() - started) * 1_000,
            3,
        )
        stats["returned_bytes"] = len(
            json.dumps(
                result,
                separators=(",", ":"),
                sort_keys=True,
                ensure_ascii=True,
            ).encode("utf-8")
        )
    return result


def _server_meta() -> dict[str, dict[str, str]]:
    return {
        "io.modelcontextprotocol/serverInfo": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
        }
    }


def _result(request_id: str | int, value: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def _error(
    request_id: str | int | None,
    code: int,
    message: str,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def modern_meta() -> dict[str, Any]:
    return {
        "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {
            "name": "local-docs-test",
            "version": SERVER_VERSION,
        },
        "io.modelcontextprotocol/clientCapabilities": {},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"Offline read-only local documentation MCP server ({PROTOCOL_VERSION})."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Local documentation source manifest whose configured index is opened read-only",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        reader = LocalDocsReader.from_manifest(args.manifest)
    except (LocalDocsError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return LocalDocsMcpServer(reader).serve(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
