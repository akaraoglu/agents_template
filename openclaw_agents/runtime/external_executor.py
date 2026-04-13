"""Prompt-aware external execution adapters for runtime workers."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from openclaw_agents.database.store import ControlPlaneStore
from openclaw_agents.runtime.artifact_parsers import ArtifactParser


class ExecutionContextBuilder:
    """Build a prompt-plus-state execution context for external backends."""

    def __init__(
        self,
        store: ControlPlaneStore | None = None,
        *,
        agent_registry_path: str | Path | None = None,
        model_map_path: str | Path | None = None,
        artifact_parser: ArtifactParser | None = None,
    ) -> None:
        self.store = store or ControlPlaneStore()
        base = Path(__file__).resolve().parents[1]
        self.agent_registry = yaml.safe_load(Path(agent_registry_path or base / "config" / "agent_registry.yaml").read_text())
        self.model_map = yaml.safe_load(Path(model_map_path or base / "config" / "model_map.yaml").read_text())
        self.artifact_parser = artifact_parser or ArtifactParser(self.store)
        self.repo_root = base

    def _artifact_record_for_ref(self, ref: str) -> dict[str, Any] | None:
        return self.store.fetchone("SELECT * FROM artifacts WHERE ref = ?", (ref,))

    def _artifact_entry(self, ref: str) -> dict[str, Any]:
        record = self._artifact_record_for_ref(ref)
        payload: Any
        try:
            payload = self.artifact_parser.parse_ref(ref)
        except Exception as exc:  # pragma: no cover - passthrough fallback
            payload = {"error": str(exc), "ref": ref}
        return {
            "ref": ref,
            "artifact_id": (record or {}).get("artifact_id"),
            "artifact_type": (record or {}).get("artifact_type"),
            "task_id": (record or {}).get("task_id"),
            "produced_by_agent": (record or {}).get("produced_by_agent"),
            "store_backend": (record or {}).get("store_backend"),
            "metadata": (record or {}).get("metadata_json") or {},
            "payload": payload,
        }

    def build(self, packet: dict[str, Any]) -> dict[str, Any]:
        agent_id = packet["to_agent"]
        agent_config = ((self.agent_registry.get("agents") or {}).get(agent_id) or {})
        prompt_path_rel = agent_config.get("prompt_path")
        prompt_path = self.repo_root / prompt_path_rel if prompt_path_rel else None
        project = self.store.get_project(packet["project_id"]) or {}
        task = self.store.get_task(packet["task_id"]) or {}
        parent_task = self.store.get_task(task.get("parent_task_id")) if task.get("parent_task_id") else None
        workspace_ref = packet.get("metadata", {}).get("workspace_ref")
        workspace_state = self.store.get_workspace_state(workspace_ref) if workspace_ref else None
        model_profile = packet.get("metadata", {}).get("model_profile")
        model_config = ((self.model_map.get("profiles") or {}).get(model_profile) or {}) if model_profile else {}
        input_artifacts = [self._artifact_entry(ref) for ref in packet.get("artifacts_in") or []]
        recent_artifacts = [
            self._artifact_entry(ref)
            for ref in self.store.list_recent_artifact_refs(packet["project_id"], limit=10)
        ]
        child_tasks = self.store.list_child_tasks(packet["task_id"]) if task else []
        return {
            "agent": {
                "agent_id": agent_id,
                "display_name": agent_config.get("display_name"),
                "role_type": agent_config.get("role_type"),
                "purpose": agent_config.get("purpose"),
                "prompt_path": str(prompt_path) if prompt_path else None,
                "prompt_text": prompt_path.read_text() if prompt_path and prompt_path.exists() else "",
                "accepts_tasks": agent_config.get("accepts_tasks") or [],
                "primary_artifact": agent_config.get("primary_artifact"),
            },
            "model": {
                "profile": model_profile,
                "runtime": model_config.get("runtime"),
                "model_hint": model_config.get("model_hint"),
                "purpose": model_config.get("purpose"),
            },
            "task_envelope": packet,
            "task_record": task,
            "project_record": project,
            "parent_task_record": parent_task,
            "workspace_state": workspace_state,
            "input_artifacts": input_artifacts,
            "recent_artifacts": recent_artifacts,
            "child_tasks": child_tasks,
        }

    @staticmethod
    def write_context(path: str | Path, context: dict[str, Any]) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(context, indent=2, sort_keys=True))
        return path


class PromptSubprocessExecutor:
    """Run an external subprocess with a structured execution context."""

    def __init__(
        self,
        store: ControlPlaneStore | None = None,
        *,
        context_builder: ExecutionContextBuilder | None = None,
    ) -> None:
        self.store = store or ControlPlaneStore()
        self.context_builder = context_builder or ExecutionContextBuilder(self.store)

    @staticmethod
    def default_command() -> list[str]:
        return [
            sys.executable,
            "-m",
            "openclaw_agents.runtime.ollama_prompt_runner",
            "--context",
            "{context}",
            "--response-file",
            "{response_file}",
            "--model",
            "{model_hint}",
        ]

    @staticmethod
    def _load_response_payload(response_path: Path, stdout: str) -> dict[str, Any]:
        if response_path.exists():
            payload = yaml.safe_load(response_path.read_text())
            if not isinstance(payload, dict):
                raise ValueError(f"{response_path} did not decode to an object")
            return payload
        if stdout.strip():
            payload = yaml.safe_load(stdout)
            if not isinstance(payload, dict):
                raise ValueError("executor stdout did not decode to an object")
            response_path.write_text(yaml.safe_dump(payload, sort_keys=False))
            return payload
        raise RuntimeError("executor completed without producing a response envelope")

    def execute(
        self,
        *,
        packet: dict[str, Any],
        response_path: Path,
        log_path: Path,
        command: list[str] | str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        context = self.context_builder.build(packet)
        context_path = response_path.with_suffix(".context.json")
        self.context_builder.write_context(context_path, context)
        if isinstance(command, str):
            command_parts = shlex.split(command)
        else:
            command_parts = list(command)
        values = {
            "context": str(context_path),
            "packet": packet["metadata"]["packet_ref"],
            "response_file": str(response_path),
            "task_id": packet["task_id"],
            "project_id": packet["project_id"],
            "agent_id": packet["to_agent"],
            "workspace_ref": packet["metadata"].get("workspace_ref") or "",
            "run_id": packet["metadata"]["run_id"],
            "prompt_path": context["agent"]["prompt_path"] or "",
            "model_profile": context["model"]["profile"] or "",
            "model_runtime": context["model"]["runtime"] or "",
            "model_hint": context["model"]["model_hint"] or "",
        }
        rendered = [part.format(**values) for part in command_parts]
        env = {
            **dict(os.environ),
            "OPENCLAW_EXECUTION_CONTEXT": values["context"],
            "OPENCLAW_TASK_PACKET": values["packet"],
            "OPENCLAW_RESPONSE_FILE": values["response_file"],
            "OPENCLAW_TASK_ID": values["task_id"],
            "OPENCLAW_PROJECT_ID": values["project_id"],
            "OPENCLAW_AGENT_ID": values["agent_id"],
            "OPENCLAW_WORKSPACE_REF": values["workspace_ref"],
            "OPENCLAW_RUN_ID": values["run_id"],
            "OPENCLAW_PROMPT_PATH": values["prompt_path"],
            "OPENCLAW_MODEL_PROFILE": values["model_profile"],
            "OPENCLAW_MODEL_RUNTIME": values["model_runtime"],
            "OPENCLAW_MODEL_HINT": values["model_hint"],
        }
        completed = subprocess.run(
            rendered,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
        log_path.write_text(
            "command: {command}\ncontext: {context}\nreturncode: {returncode}\n\nstdout:\n{stdout}\n\nstderr:\n{stderr}\n".format(
                command=rendered,
                context=context_path,
                returncode=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
            )
        )
        if completed.returncode != 0 and not response_path.exists():
            raise RuntimeError(f"executor returned {completed.returncode}: {completed.stderr.strip() or completed.stdout.strip()}")
        return self._load_response_payload(response_path, completed.stdout)
