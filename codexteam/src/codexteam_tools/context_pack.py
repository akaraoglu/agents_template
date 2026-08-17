from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .files import atomic_write_json


CONTEXT_PACK_FILENAME = "context-pack.json"


def build_context_pack(request: Any, turn_number: int, metrics: dict[str, Any]) -> dict[str, Any]:
    mcp = metrics["activity"]["mcp"]
    value = {
        "schema_version": "1.0",
        "identity": {
            "team_id": request.team_id,
            "task_id": request.task_id,
            "attempt_id": request.attempt_id,
            "role": request.role,
            "turn_number": turn_number,
        },
        "handoff": {
            "source_path": request.prompt_source_path,
            "content_digest": request.prompt_content_digest,
        },
        "context_targets": _context_target_provenance(request.prompt),
        "policy": {
            "role_policy_digest": request.role_policy.digest,
            "agent_spec_digest": request.agent_spec.digest if request.agent_spec is not None else None,
            "guidance_digest": request.guidance_digest,
            "execution_spec_digest": request.execution_spec["execution_spec_digest"],
        },
        "mcp": {
            "effective_servers": list(request.effective_mcp_servers),
            "effective_tools": {
                server: list(tools) for server, tools in request.effective_mcp_tools
            },
            "calls": mcp["calls"],
            "failed_calls": mcp["failed_calls"],
            "server_duration_ms": mcp["server_duration_ms"],
            "client_duration_ms": mcp["client_duration_ms"],
            "returned_bytes": mcp["returned_bytes"],
            "source_bytes": mcp["source_bytes"],
            "source_digests": mcp["source_digests"],
        },
    }
    value["digest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return value


def write_context_pack(path: Path, value: dict[str, Any]) -> None:
    atomic_write_json(path, value)
    path.chmod(0o600)


def _context_target_provenance(prompt: str) -> list[dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for token in prompt.split("`")[1::2]:
        clean = token.strip()
        if clean and "\n" not in clean and len(clean) <= 256:
            encoded = clean.encode("utf-8")
            digest = hashlib.sha256(encoded).hexdigest()
            targets[digest] = {"sha256": digest, "bytes": len(encoded)}
    return [targets[digest] for digest in sorted(targets)]
