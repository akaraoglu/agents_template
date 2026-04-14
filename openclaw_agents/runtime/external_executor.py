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

WORKSPACE_ROOT_SCOPE_AGENTS = {"master", "neo", "agent_smith"}
TASK_SCOPE_VISIBLE_AGENTS = {"morpheus"}
PROJECT_CONTEXT_ARTIFACT_TYPES = (
    "project_charter",
    "architecture_spec",
    "software_delivery_package",
    "verification_report",
    "project_status_report",
    "project_closure_report",
    "escalation_packet",
)
TASK_CONTEXT_ARTIFACT_TYPES_BY_TASK_TYPE = {
    "ORCHESTRATE_SOFTWARE": (
        "project_charter",
        "architecture_spec",
        "software_task_plan",
        "code_change",
        "test_execution_report",
        "software_delivery_package",
    ),
    "PLAN_SOFTWARE_TASK": (
        "project_charter",
        "architecture_spec",
        "software_task_plan",
    ),
    "IMPLEMENT_SOFTWARE_TASK": (
        "software_task_plan",
        "architecture_spec",
        "project_charter",
        "code_change",
    ),
    "TEST_SOFTWARE_TASK": (
        "software_task_plan",
        "code_change",
        "architecture_spec",
        "project_charter",
        "test_execution_report",
    ),
}


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

    @staticmethod
    def _compact_record(record: dict[str, Any] | None, keys: tuple[str, ...]) -> dict[str, Any] | None:
        if not record:
            return None
        return {key: record.get(key) for key in keys if key in record}

    @staticmethod
    def _ensure_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            rendered: list[str] = []
            for item in value:
                if isinstance(item, str):
                    rendered.append(item)
                elif item is not None:
                    rendered.append(json.dumps(item, sort_keys=True))
            return rendered
        return [str(value)]

    def _task_context_brief(self, context: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key in (
            "software_goal",
            "project_goal",
            "retry_reason",
            "plan_task_id",
            "implementer_task_id",
            "force_test_result",
            "failure_cause",
            "latest_test_report",
        ):
            if key in context:
                summary[key] = context[key]
        if isinstance(context.get("requirements"), list):
            summary["requirements"] = context["requirements"][:5]
        if isinstance(context.get("suggested_files"), list):
            summary["suggested_files"] = context["suggested_files"][:5]
        plan_summary = context.get("plan_summary")
        if isinstance(plan_summary, dict):
            summary["plan_summary"] = {
                "summary": plan_summary.get("summary"),
                "implementation_steps": (plan_summary.get("implementation_steps") or [])[:5],
                "test_obligations": (plan_summary.get("test_obligations") or [])[:5],
            }
        code_summary = context.get("code_summary")
        if isinstance(code_summary, dict):
            summary["code_summary"] = {
                "summary": code_summary.get("summary"),
                "changed_files": (code_summary.get("changed_files") or [])[:5],
                "handoff_notes_for_tester": (code_summary.get("handoff_notes_for_tester") or [])[:5],
            }
        return summary

    def _task_summary(self, record: dict[str, Any] | None, packet: dict[str, Any] | None = None) -> dict[str, Any] | None:
        source = record or packet
        if not source:
            return None
        context = source.get("context_json") if record else source.get("context")
        expected_output = source.get("expected_output_json") if record else source.get("expected_output")
        return {
            "task_id": source.get("task_id"),
            "task_type": source.get("task_type"),
            "title": source.get("title"),
            "goal": source.get("goal"),
            "priority": source.get("priority"),
            "from_agent": source.get("from_agent"),
            "to_agent": source.get("to_agent"),
            "status": source.get("status"),
            "expected_output": expected_output or {},
            "context": self._task_context_brief(context or {}),
        }

    def _child_task_summary(self, task: dict[str, Any]) -> dict[str, Any]:
        return {
            "task_id": task.get("task_id"),
            "task_type": task.get("task_type"),
            "to_agent": task.get("to_agent"),
            "status": task.get("status"),
            "updated_at": task.get("updated_at"),
        }

    @staticmethod
    def _workspace_root(project_root: Path | None) -> Path | None:
        configured_root = os.environ.get("OPENCLAW_WORKSPACE_ROOT")
        if configured_root:
            return Path(configured_root).resolve()
        workspaces_dir = os.environ.get("OPENCLAW_PROJECT_WORKSPACES_DIR")
        if workspaces_dir:
            return Path(workspaces_dir).resolve().parent
        if project_root is None:
            return None
        if project_root.parent.name == "projects":
            return project_root.parent.parent
        return project_root.parent

    def _artifact_payload_brief(self, artifact_type: str, payload: Any) -> dict[str, Any] | Any:
        if not isinstance(payload, dict):
            return payload
        if artifact_type == "project_charter":
            return {
                "problem_statement": payload.get("problem_statement"),
                "goals": (payload.get("goals") or [])[:5],
                "acceptance_criteria": (payload.get("acceptance_criteria") or [])[:5],
                "constraints": (payload.get("constraints") or [])[:5],
                "open_questions": (payload.get("open_questions") or [])[:5],
            }
        if artifact_type == "architecture_spec":
            return {
                "summary": payload.get("summary"),
                "system_shape": payload.get("system_shape"),
                "interfaces": (payload.get("interfaces") or [])[:5],
                "constraints": (payload.get("constraints") or [])[:5],
                "validation_implications": (payload.get("validation_implications") or [])[:5],
            }
        if artifact_type == "software_task_plan":
            return {
                "summary": payload.get("summary"),
                "implementation_steps": (payload.get("implementation_steps") or [])[:5],
                "test_obligations": (payload.get("test_obligations") or [])[:5],
                "open_questions": (payload.get("open_questions") or [])[:5],
            }
        if artifact_type == "code_change":
            return {
                "summary": payload.get("summary"),
                "changed_files": (payload.get("changed_files") or [])[:8],
                "build_notes": payload.get("build_notes"),
                "handoff_notes_for_tester": (payload.get("handoff_notes_for_tester") or [])[:5],
            }
        if artifact_type == "test_execution_report":
            return {
                "summary": payload.get("summary"),
                "commands_run": (payload.get("commands_run") or [])[:5],
                "result": payload.get("result"),
                "failures": (payload.get("failures") or [])[:5],
                "failure_cause": payload.get("failure_cause"),
            }
        if artifact_type in {"software_delivery_package", "verification_report", "project_status_report", "project_closure_report", "escalation_packet"}:
            return {
                key: value
                for key, value in payload.items()
                if key in {"summary", "result", "failure_cause", "blocking_facts", "open_questions", "verification_result"}
            }
        return payload

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
            "payload": self._artifact_payload_brief(str((record or {}).get("artifact_type") or ""), payload),
        }

    def _context_scope(self, agent_id: str) -> str:
        if agent_id in WORKSPACE_ROOT_SCOPE_AGENTS:
            return "workspace_root"
        agent_config = ((self.agent_registry.get("agents") or {}).get(agent_id) or {})
        if agent_id in TASK_SCOPE_VISIBLE_AGENTS or agent_config.get("visibility") == "internal_only":
            return "task"
        return "project"

    def _latest_artifact_entries(
        self,
        project_id: str,
        artifact_types: tuple[str, ...] | list[str],
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for artifact_type in artifact_types:
            records = self.artifact_parser.list_project_artifacts(project_id, artifact_type=artifact_type)
            if not records:
                continue
            entries.append(self._artifact_entry(records[-1]["ref"]))
        return entries

    def _selected_input_artifacts(
        self,
        packet: dict[str, Any],
        *,
        allowed_types: tuple[str, ...] | list[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        for ref in packet.get("artifacts_in") or []:
            entry = self._artifact_entry(ref)
            artifact_type = entry.get("artifact_type")
            if allowed_types and artifact_type not in allowed_types:
                continue
            selected.append(entry)
            if len(selected) >= limit:
                break
        return selected

    def build_project_context(
        self,
        *,
        packet: dict[str, Any],
        project: dict[str, Any],
        task: dict[str, Any],
        parent_task: dict[str, Any] | None,
        workspace_state: dict[str, Any] | None,
        scope: str,
    ) -> dict[str, Any]:
        project_root = Path(project.get("workspace_ref")) if project.get("workspace_ref") else None
        workspace_root = self._workspace_root(project_root)
        root_path = workspace_root if scope == "workspace_root" and workspace_root is not None else project_root
        relevant_artifacts = self._latest_artifact_entries(packet["project_id"], PROJECT_CONTEXT_ARTIFACT_TYPES)
        child_tasks = [self._child_task_summary(item) for item in self.store.list_child_tasks(packet["task_id"])]
        return {
            "scope": scope,
            "root": {
                "root_path": str(root_path) if root_path else None,
                "project_root": str(project_root) if project_root else None,
                "workspace_root": str(workspace_root) if workspace_root else None,
            },
            "task": self._task_summary(task, packet),
            "parent_task": self._task_summary(parent_task),
            "project": self._compact_record(
                project,
                (
                    "project_id",
                    "goal",
                    "project_status",
                    "runtime_status",
                    "priority",
                    "current_phase",
                    "current_owner_agent",
                    "workspace_ref",
                ),
            ),
            "workspace": self._compact_record(
                workspace_state,
                (
                    "workspace_ref",
                    "repo_root",
                    "branch_or_worktree_id",
                    "last_clean_commit_or_checkpoint",
                    "is_consistent",
                ),
            ),
            "input_artifacts": self._selected_input_artifacts(packet, allowed_types=PROJECT_CONTEXT_ARTIFACT_TYPES, limit=6),
            "relevant_artifacts": relevant_artifacts[:6],
            "child_tasks": child_tasks[:8],
        }

    def build_task_context(
        self,
        *,
        packet: dict[str, Any],
        project: dict[str, Any],
        task: dict[str, Any],
        parent_task: dict[str, Any] | None,
        workspace_state: dict[str, Any] | None,
    ) -> dict[str, Any]:
        project_root = Path(project.get("workspace_ref")) if project.get("workspace_ref") else None
        relevant_types = TASK_CONTEXT_ARTIFACT_TYPES_BY_TASK_TYPE.get(packet["task_type"], ())
        input_artifacts = self._selected_input_artifacts(packet, allowed_types=relevant_types, limit=4)
        relevant_artifacts = self._latest_artifact_entries(packet["project_id"], relevant_types)[:4]
        child_tasks = [self._child_task_summary(item) for item in self.store.list_child_tasks(packet["task_id"])]
        return {
            "scope": "task",
            "root": {
                "root_path": str(project_root) if project_root else None,
                "project_root": str(project_root) if project_root else None,
                "workspace_root": None,
            },
            "task": self._task_summary(task, packet),
            "parent_task": self._task_summary(parent_task),
            "project": self._compact_record(
                project,
                (
                    "project_id",
                    "goal",
                    "project_status",
                    "runtime_status",
                    "current_phase",
                    "current_owner_agent",
                ),
            ),
            "workspace": self._compact_record(
                workspace_state,
                (
                    "workspace_ref",
                ),
            ),
            "input_artifacts": input_artifacts,
            "relevant_artifacts": relevant_artifacts,
            "child_tasks": child_tasks[:4],
        }

    def build(self, packet: dict[str, Any]) -> dict[str, Any]:
        agent_id = packet["to_agent"]
        agent_config = ((self.agent_registry.get("agents") or {}).get(agent_id) or {})
        prompt_path_rel = agent_config.get("prompt_path")
        prompt_path = self.repo_root / prompt_path_rel if prompt_path_rel else None
        project = self.store.get_project(packet["project_id"]) or {}
        task = self.store.get_task(packet["task_id"]) or {}
        parent_task = self.store.get_task(task.get("parent_task_id")) if task.get("parent_task_id") else None
        workspace_ref = packet.get("metadata", {}).get("workspace_ref") or project.get("workspace_ref")
        workspace_state = self.store.get_workspace_state(workspace_ref) if workspace_ref else None
        model_profile = packet.get("metadata", {}).get("model_profile")
        model_config = ((self.model_map.get("profiles") or {}).get(model_profile) or {}) if model_profile else {}
        context_scope = self._context_scope(agent_id)
        if context_scope == "task":
            context_payload = self.build_task_context(
                packet=packet,
                project=project,
                task=task,
                parent_task=parent_task,
                workspace_state=workspace_state,
            )
        else:
            context_payload = self.build_project_context(
                packet=packet,
                project=project,
                task=task,
                parent_task=parent_task,
                workspace_state=workspace_state,
                scope=context_scope,
            )
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
            "context_scope": context_scope,
            "context_root": context_payload["root"],
            "context_payload": context_payload,
            "task_envelope": packet,
            "task_record": context_payload["task"],
            "project_record": context_payload["project"],
            "parent_task_record": context_payload["parent_task"],
            "workspace_state": context_payload["workspace"],
            "input_artifacts": context_payload["input_artifacts"],
            "relevant_artifacts": context_payload["relevant_artifacts"],
            "recent_artifacts": context_payload["relevant_artifacts"],
            "child_tasks": context_payload["child_tasks"],
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
