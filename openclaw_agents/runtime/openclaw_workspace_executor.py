"""Workspace-backed OpenClaw executor for code-changing software roles."""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from openclaw_agents.database.store import ControlPlaneStore
from openclaw_agents.runtime.external_executor import ExecutionContextBuilder
from openclaw_agents.runtime.ollama_prompt_runner import ANSI_ESCAPE_RE, CONTROL_CHAR_RE
from openclaw_agents.runtime.dispatcher import ContractValidator


ALLOWED_STATUSES = {"SUCCESS", "NEEDS_CLARIFICATION", "BLOCKED", "FAILED", "CANCELLED"}
IMPLEMENTER_FAILURE_CAUSES = {"IMPLEMENTATION_DEFECT", "BAD_PLAN", "UNKNOWN"}
TESTER_FAILURE_CAUSES = {"PASS", "FAIL", "IMPLEMENTATION_DEFECT", "TEST_GAP", "BAD_PLAN", "UNKNOWN"}
MAX_LIST_ITEMS = 5


class WorkspaceExecutionBlockedError(RuntimeError):
    """Raised when workspace-backed execution should block rather than fail."""


class WorkspaceExecutionTimeoutError(WorkspaceExecutionBlockedError):
    """Raised when the OpenClaw workspace backend exceeds its runtime budget."""


@dataclass(slots=True)
class WorkspaceStateSnapshot:
    root: Path
    files: dict[str, tuple[int, int]]


class OpenClawWorkspaceExecutor:
    """Provision OpenClaw agents per workspace and normalize code-changing task results."""

    def __init__(
        self,
        store: ControlPlaneStore | None = None,
        *,
        context_builder: ExecutionContextBuilder | None = None,
        schema_dir: str | Path | None = None,
        openclaw_bin: str = "openclaw",
    ) -> None:
        self.store = store or ControlPlaneStore()
        self.context_builder = context_builder or ExecutionContextBuilder(self.store)
        base = Path(__file__).resolve().parents[1]
        self.validator = ContractValidator(schema_dir or base / "schemas")
        self.openclaw_bin = openclaw_bin

    @staticmethod
    def _sanitize_identifier(value: str) -> str:
        sanitized = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-_").lower()
        return sanitized or "runtime"

    def _backend_agent_id(self, packet: dict[str, Any]) -> str:
        project_slug = self._sanitize_identifier(packet["project_id"])
        role_slug = self._sanitize_identifier(packet["to_agent"])
        run_key = (
            (packet.get("metadata") or {}).get("run_id")
            or (packet.get("metadata") or {}).get("attempt_id")
            or packet["task_id"]
        )
        digest = hashlib.sha1(str(run_key).encode("utf-8")).hexdigest()[:8]
        return f"ocw-{project_slug}-{role_slug}-{digest}"

    def _session_id(self, packet: dict[str, Any]) -> str:
        project_slug = self._sanitize_identifier(packet["project_id"])
        task_slug = self._sanitize_identifier(packet["task_id"])
        role_slug = self._sanitize_identifier(packet["to_agent"])
        return f"ocw-{project_slug}-{role_slug}-{task_slug}"

    @staticmethod
    def _strip_terminal_noise(payload: str) -> str:
        without_ansi = ANSI_ESCAPE_RE.sub("", payload)
        return CONTROL_CHAR_RE.sub("", without_ansi)

    def _extract_json_payload(self, text: str) -> Any:
        cleaned = self._strip_terminal_noise(text)
        decoder = json.JSONDecoder()
        for index, char in enumerate(cleaned):
            if char not in "[{":
                continue
            try:
                payload, _end = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            return payload
        raise ValueError("OpenClaw output did not contain a JSON object or array")

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

    @staticmethod
    def _workspace_root(context: dict[str, Any]) -> Path:
        workspace_ref = (
            ((context.get("workspace_state") or {}).get("workspace_ref"))
            or ((context.get("project_record") or {}).get("workspace_ref"))
            or ((context.get("task_envelope") or {}).get("metadata") or {}).get("workspace_ref")
        )
        if not workspace_ref:
            raise WorkspaceExecutionBlockedError("workspace-backed OpenClaw execution requires workspace_ref")
        root = Path(workspace_ref)
        if not root.exists():
            raise WorkspaceExecutionBlockedError(f"workspace path does not exist: {root}")
        return root

    @staticmethod
    def _scan_workspace(root: Path) -> WorkspaceStateSnapshot:
        files: dict[str, tuple[int, int]] = {}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if ".git" in relative.parts or "artifacts" in relative.parts:
                continue
            stat = path.stat()
            files[str(relative)] = (stat.st_mtime_ns, stat.st_size)
        return WorkspaceStateSnapshot(root=root, files=files)

    @staticmethod
    def _changed_files(before: WorkspaceStateSnapshot, after: WorkspaceStateSnapshot) -> list[str]:
        changed: set[str] = set()
        before_keys = set(before.files.keys())
        after_keys = set(after.files.keys())
        for path in sorted(before_keys | after_keys):
            if before.files.get(path) != after.files.get(path):
                changed.add(path)
        return sorted(changed)

    @staticmethod
    def _model_identifier(context: dict[str, Any], fallback_model: str | None = None) -> str:
        runtime = ((context.get("model") or {}).get("runtime")) or "ollama"
        hint = fallback_model or ((context.get("model") or {}).get("model_hint"))
        if hint and "/" in str(hint):
            return str(hint)
        if runtime == "ollama":
            return f"ollama/{hint or 'gemma4:31b'}"
        if hint:
            return str(hint)
        return "ollama/gemma4:31b"

    @staticmethod
    def _write_command_log(
        *,
        command: list[str],
        log_path: Path,
        returncode: int | None,
        stdout: str,
        stderr: str,
        timeout_seconds: int | None = None,
        harvested_from_session: bool = False,
    ) -> None:
        log_path.write_text(
            "command: {command}\nreturncode: {returncode}\ntimeout_seconds: {timeout}\nharvested_from_session: {harvested}\n\nstdout:\n{stdout}\n\nstderr:\n{stderr}\n".format(
                command=command,
                returncode=returncode,
                timeout=timeout_seconds,
                harvested=harvested_from_session,
                stdout=stdout,
                stderr=stderr,
            )
        )

    @staticmethod
    def _append_log_note(log_path: Path, note: str) -> None:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n{note}\n")

    @staticmethod
    def _session_dir(agent_record: dict[str, Any]) -> Path | None:
        agent_dir = agent_record.get("agentDir")
        if not isinstance(agent_dir, str) or not agent_dir:
            return None
        return Path(agent_dir).resolve().parent / "sessions"

    @staticmethod
    def _latest_session_entry(session_dir: Path | None) -> dict[str, Any] | None:
        if session_dir is None:
            return None
        index_path = session_dir / "sessions.json"
        if not index_path.exists():
            return None
        try:
            payload = json.loads(index_path.read_text())
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        entries = [value for value in payload.values() if isinstance(value, dict)]
        if not entries:
            return None
        entries.sort(key=lambda item: int(item.get("updatedAt") or 0), reverse=True)
        return entries[0]

    def _harvest_session_result(self, session_dir: Path | None) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
        entry = self._latest_session_entry(session_dir)
        if not entry or entry.get("status") != "done":
            return None
        session_file = entry.get("sessionFile")
        if not isinstance(session_file, str) or not Path(session_file).exists():
            return None
        visible_text: str | None = None
        provider = entry.get("provider")
        model = entry.get("model")
        for line in Path(session_file).read_text().splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "model_change":
                provider = event.get("provider") or provider
                model = event.get("modelId") or model
                continue
            if event.get("type") != "message":
                continue
            message = event.get("message") or {}
            if message.get("role") != "assistant":
                continue
            for item in message.get("content") or []:
                if item.get("type") != "text" or not isinstance(item.get("text"), str):
                    continue
                candidate = item["text"].strip()
                try:
                    parsed = self._parse_visible_payload(candidate)
                except Exception:
                    continue
                visible_text = candidate
                return (
                    visible_text,
                    parsed,
                    {
                        "result": {
                            "payloads": [{"text": visible_text, "mediaUrl": None}],
                            "meta": {
                                "agentMeta": {
                                    "sessionId": entry.get("sessionId"),
                                    "provider": provider,
                                    "model": model,
                                }
                            }
                        }
                    },
                )
        return None

    @staticmethod
    def _task_context_brief(context: dict[str, Any]) -> dict[str, Any]:
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
            summary["requirements"] = context["requirements"][:MAX_LIST_ITEMS]
        if isinstance(context.get("suggested_files"), list):
            summary["suggested_files"] = context["suggested_files"][:MAX_LIST_ITEMS]
        if isinstance(context.get("plan_summary"), dict):
            summary["plan_summary"] = {
                "summary": context["plan_summary"].get("summary"),
                "implementation_steps": (context["plan_summary"].get("implementation_steps") or [])[:MAX_LIST_ITEMS],
                "test_obligations": (context["plan_summary"].get("test_obligations") or [])[:MAX_LIST_ITEMS],
            }
        if isinstance(context.get("code_summary"), dict):
            summary["code_summary"] = {
                "summary": context["code_summary"].get("summary"),
                "changed_files": (context["code_summary"].get("changed_files") or [])[:MAX_LIST_ITEMS],
                "handoff_notes_for_tester": (context["code_summary"].get("handoff_notes_for_tester") or [])[:MAX_LIST_ITEMS],
            }
        return summary

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except Exception:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except Exception:
                pass
            try:
                process.wait(timeout=2)
            except Exception:
                pass

    def _run_command(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
        log_path: Path,
        session_dir: Path | None = None,
        grace_seconds: int = 15,
    ) -> Any:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            harvested: tuple[str, dict[str, Any], dict[str, Any]] | None = None
            deadline = time.time() + max(grace_seconds, 0)
            while time.time() <= deadline and harvested is None:
                harvested = self._harvest_session_result(session_dir)
                if harvested is not None:
                    break
                time.sleep(1.0)
            self._terminate_process_tree(process)
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + f"\nworker timeout after {timeout_seconds}s"
            if harvested is not None:
                self._write_command_log(
                    command=command,
                    log_path=log_path,
                    returncode=process.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    timeout_seconds=timeout_seconds,
                    harvested_from_session=True,
                )
                return harvested[2]
            self._write_command_log(
                command=command,
                log_path=log_path,
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
                timeout_seconds=timeout_seconds,
            )
            raise WorkspaceExecutionTimeoutError(f"OpenClaw workspace execution timed out after {timeout_seconds}s")
        finally:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

        self._write_command_log(
            command=command,
            log_path=log_path,
            returncode=process.returncode,
            stdout=stdout,
            stderr=stderr,
        )
        if process.returncode != 0:
            harvested = self._harvest_session_result(session_dir)
            if harvested is not None:
                self._write_command_log(
                    command=command,
                    log_path=log_path,
                    returncode=process.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    harvested_from_session=True,
                )
                return harvested[2]
            message = stderr.strip() or stdout.strip() or f"OpenClaw returned {process.returncode}"
            raise WorkspaceExecutionBlockedError(message)
        return self._extract_json_payload(stdout)

    def _list_agents(self, *, openclaw_bin: str, timeout_seconds: int, log_path: Path) -> list[dict[str, Any]]:
        payload = self._run_command(
            [openclaw_bin, "agents", "list", "--json"],
            timeout_seconds=timeout_seconds,
            log_path=log_path,
        )
        if not isinstance(payload, list):
            raise ValueError("OpenClaw agents list did not return an array")
        return [item for item in payload if isinstance(item, dict)]

    def _ensure_agent(
        self,
        *,
        backend_agent_id: str,
        workspace_ref: str,
        model_id: str,
        openclaw_bin: str,
        timeout_seconds: int,
        log_path: Path,
    ) -> dict[str, Any]:
        agents = self._list_agents(
            openclaw_bin=openclaw_bin,
            timeout_seconds=timeout_seconds,
            log_path=log_path.with_suffix(".agents.log"),
        )
        for agent in agents:
            if agent.get("id") == backend_agent_id:
                existing_model = str(agent.get("model") or "")
                existing_workspace = str(agent.get("workspace") or "")
                if existing_model == model_id and existing_workspace == workspace_ref:
                    return agent
                self._run_command(
                    [
                        openclaw_bin,
                        "agents",
                        "delete",
                        backend_agent_id,
                        "--force",
                        "--json",
                    ],
                    timeout_seconds=timeout_seconds,
                    log_path=log_path.with_suffix(".reconcile.log"),
                )
                break
        Path(workspace_ref).mkdir(parents=True, exist_ok=True)
        payload = self._run_command(
            [
                openclaw_bin,
                "agents",
                "add",
                backend_agent_id,
                "--workspace",
                workspace_ref,
                "--model",
                model_id,
                "--non-interactive",
                "--json",
            ],
            timeout_seconds=timeout_seconds,
            log_path=log_path.with_suffix(".provision.log"),
        )
        if not isinstance(payload, dict):
            raise ValueError("OpenClaw agent provisioning did not return an object")
        return payload

    def _raw_visible_text(self, payload: dict[str, Any]) -> str:
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ValueError("OpenClaw response is missing the `result` object")
        payloads = result.get("payloads")
        if not isinstance(payloads, list) or not payloads:
            raise ValueError("OpenClaw response has no payloads")
        first = payloads[0]
        if not isinstance(first, dict) or not isinstance(first.get("text"), str):
            raise ValueError("OpenClaw response payload is missing visible text")
        return first["text"]

    def _parse_visible_payload(self, text: str) -> dict[str, Any]:
        cleaned = self._strip_terminal_noise(text).strip()
        if cleaned.startswith("```"):
            match = re.search(r"```(?:json|yaml)?\s*(.*?)```", cleaned, flags=re.DOTALL)
            cleaned = match.group(1).strip() if match else cleaned
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            parsed = yaml.safe_load(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("OpenClaw visible text did not decode to an object")
        return parsed

    @staticmethod
    def _artifact_payload_brief(artifact_type: str, payload: Any) -> dict[str, Any] | Any:
        if not isinstance(payload, dict):
            return payload
        if artifact_type == "software_task_plan":
            return {
                "summary": payload.get("summary"),
                "task_breakdown": (payload.get("task_breakdown") or [])[:MAX_LIST_ITEMS],
                "implementation_steps": (payload.get("implementation_steps") or [])[:MAX_LIST_ITEMS],
                "test_obligations": (payload.get("test_obligations") or [])[:MAX_LIST_ITEMS],
                "open_questions": (payload.get("open_questions") or [])[:MAX_LIST_ITEMS],
            }
        if artifact_type == "code_change":
            return {
                "summary": payload.get("summary"),
                "changed_files": (payload.get("changed_files") or [])[:MAX_LIST_ITEMS],
                "build_notes": payload.get("build_notes"),
                "handoff_notes_for_tester": (payload.get("handoff_notes_for_tester") or [])[:MAX_LIST_ITEMS],
                "known_limitations": (payload.get("known_limitations") or [])[:MAX_LIST_ITEMS],
            }
        if artifact_type == "test_execution_report":
            return {
                "summary": payload.get("summary"),
                "commands_run": (payload.get("commands_run") or [])[:MAX_LIST_ITEMS],
                "result": payload.get("result"),
                "failures": (payload.get("failures") or [])[:MAX_LIST_ITEMS],
                "failure_cause": payload.get("failure_cause"),
                "coverage_notes": (payload.get("coverage_notes") or [])[:MAX_LIST_ITEMS],
            }
        return {
            key: value
            for key, value in payload.items()
            if key in {"summary", "result", "failure_cause", "requirements", "constraints", "goals"}
        }

    def _artifact_entry_brief(self, entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "artifact_type": entry.get("artifact_type"),
            "task_id": entry.get("task_id"),
            "produced_by_agent": entry.get("produced_by_agent"),
            "ref": entry.get("ref"),
            "payload": self._artifact_payload_brief(str(entry.get("artifact_type") or ""), entry.get("payload")),
        }

    def _prompt_context(self, context: dict[str, Any]) -> dict[str, Any]:
        task = context["task_envelope"]
        project = context.get("project_record") or {}
        parent_task = context.get("parent_task_record") or {}
        workspace = context.get("workspace_state") or {}
        return {
            "task": {
                "task_id": task.get("task_id"),
                "task_type": task.get("task_type"),
                "goal": task.get("goal"),
                "priority": task.get("priority"),
                "from_agent": task.get("from_agent"),
                "expected_output": task.get("expected_output") or {},
                "context": self._task_context_brief(task.get("context") or {}),
            },
            "project": {
                "project_id": project.get("project_id"),
                "goal": project.get("goal"),
                "current_phase": project.get("current_phase"),
                "current_owner_agent": project.get("current_owner_agent"),
                "runtime_status": project.get("runtime_status"),
            },
            "parent_task": {
                "task_id": parent_task.get("task_id"),
                "task_type": parent_task.get("task_type"),
                "status": parent_task.get("status"),
                "goal": parent_task.get("goal"),
            },
            "workspace": {
                "workspace_ref": workspace.get("workspace_ref") or project.get("workspace_ref"),
                "repo_root": workspace.get("repo_root") or project.get("workspace_ref"),
                "branch_or_worktree_id": workspace.get("branch_or_worktree_id"),
                "last_clean_commit_or_checkpoint": workspace.get("last_clean_commit_or_checkpoint"),
            },
            "input_artifacts": [self._artifact_entry_brief(item) for item in (context.get("input_artifacts") or [])[:3]],
            "recent_artifacts": [self._artifact_entry_brief(item) for item in (context.get("recent_artifacts") or [])[:4]],
            "child_tasks": [
                {
                    "task_id": item.get("task_id"),
                    "task_type": item.get("task_type"),
                    "to_agent": item.get("to_agent"),
                    "status": item.get("status"),
                }
                for item in (context.get("child_tasks") or [])[-3:]
            ],
        }

    def _build_prompt(self, context: dict[str, Any]) -> str:
        packet = context["task_envelope"]
        role = packet["to_agent"]
        workspace_root = self._workspace_root(context)
        if role == "implementer":
            artifact_schema = {
                "status": "SUCCESS | NEEDS_CLARIFICATION | BLOCKED | FAILED",
                "summary": "short summary",
                "findings": ["important implementation facts"],
                "risks": ["remaining risk"],
                "build_notes": "what changed or build impact",
                "known_limitations": ["remaining limitation"],
                "handoff_notes_for_tester": ["what tester should verify next"],
            }
            role_notes = [
                "Modify the real workspace when implementation is justified by the provided plan and artifacts.",
                "Do not invent completed tests. Only change code or tests you actually touched.",
                "If the plan is incomplete or unsafe, return NEEDS_CLARIFICATION or BLOCKED.",
            ]
        elif role == "tester":
            artifact_schema = {
                "status": "SUCCESS | NEEDS_CLARIFICATION | BLOCKED | FAILED",
                "summary": "short validation summary",
                "findings": ["important validation facts"],
                "risks": ["remaining risk"],
                "commands_run": ["exact commands"],
                "result": "PASS | FAIL",
                "failures": ["failure details"],
                "failure_cause": "PASS | IMPLEMENTATION_DEFECT | TEST_GAP | BAD_PLAN | UNKNOWN",
                "coverage_notes": ["coverage or evidence notes"],
            }
            role_notes = [
                "Run real validation commands in the workspace when possible.",
                "Use `result=PASS` only when the implemented change validated successfully.",
                "Use failure_cause BAD_PLAN, TEST_GAP, or IMPLEMENTATION_DEFECT when result is FAIL so Morpheus can route retries correctly.",
            ]
        else:
            raise ValueError(f"openclaw_workspace executor only supports implementer and tester, not {role}")

        prompt_context = self._prompt_context(context)
        return "\n".join(
            [
                f"You are the OpenClaw runtime backend for the `{role}` role.",
                f"Operate only inside the workspace: {workspace_root}",
                "You may inspect files, edit files, and run commands needed to complete the task.",
                *[f"- {note}" for note in role_notes],
                "",
                "Role prompt:",
                context["agent"].get("prompt_text") or "",
                "",
                "Return exactly one JSON object and no markdown fences.",
                "The JSON schema for your visible reply is:",
                json.dumps(artifact_schema, indent=2, sort_keys=True),
                "",
                "Execution context:",
                json.dumps(prompt_context, indent=2, sort_keys=True),
            ]
        )

    def _normalize_response(
        self,
        *,
        packet: dict[str, Any],
        parsed: dict[str, Any],
        visible_text: str,
        openclaw_payload: dict[str, Any],
        changed_files: list[str],
        backend_agent_id: str,
    ) -> dict[str, Any]:
        role = packet["to_agent"]
        status = str(parsed.get("status") or "SUCCESS").upper()
        if status not in ALLOWED_STATUSES:
            status = "SUCCESS"
        summary = str(parsed.get("summary") or f"{role} completed {packet['task_type']}.").strip()
        findings = self._ensure_string_list(parsed.get("findings"))
        risks = self._ensure_string_list(parsed.get("risks"))
        meta = ((openclaw_payload.get("result") or {}).get("meta") or {})
        agent_meta = meta.get("agentMeta") if isinstance(meta, dict) else {}
        trace = {
            "run_id": packet["metadata"]["run_id"],
            "executor": "openclaw_workspace",
            "backend_agent_id": backend_agent_id,
            "backend_session_id": (agent_meta or {}).get("sessionId"),
            "backend_provider": (agent_meta or {}).get("provider"),
            "backend_model": (agent_meta or {}).get("model"),
        }
        if role == "implementer":
            artifact_payload = {
                "summary": summary,
                "changed_files": changed_files or self._ensure_string_list(parsed.get("changed_files")),
                "build_notes": str(parsed.get("build_notes") or "OpenClaw workspace executor completed the implementation step."),
                "known_limitations": self._ensure_string_list(parsed.get("known_limitations")),
                "handoff_notes_for_tester": self._ensure_string_list(parsed.get("handoff_notes_for_tester")),
                "openclaw_visible_text": visible_text,
            }
            findings = findings or artifact_payload["changed_files"]
            next_reason = "Implementation step completed." if status == "SUCCESS" else summary
            artifact_type = "code_change"
        else:
            result_value = str(parsed.get("result") or "PASS").upper()
            if result_value not in {"PASS", "FAIL"}:
                result_value = "FAIL" if status in {"BLOCKED", "FAILED"} else "PASS"
            failure_cause = str(parsed.get("failure_cause") or ("PASS" if result_value == "PASS" else "UNKNOWN")).upper()
            if failure_cause not in TESTER_FAILURE_CAUSES:
                failure_cause = "UNKNOWN"
            artifact_payload = {
                "summary": summary,
                "test_changes": changed_files,
                "commands_run": self._ensure_string_list(parsed.get("commands_run")),
                "result": result_value,
                "failures": self._ensure_string_list(parsed.get("failures")),
                "failure_cause": None if result_value == "PASS" else failure_cause,
                "coverage_notes": self._ensure_string_list(parsed.get("coverage_notes")),
                "openclaw_visible_text": visible_text,
            }
            findings = findings or artifact_payload["commands_run"]
            risks = risks or artifact_payload["failures"]
            next_reason = "Validation step completed." if status == "SUCCESS" else summary
            artifact_type = "test_execution_report"

        response = {
            "task_id": packet["task_id"],
            "project_id": packet["project_id"],
            "agent": role,
            "status": status,
            "summary": summary,
            "artifacts_out": [
                {
                    "artifact_type": artifact_type,
                    "ref": f"inline://{role}-{packet['task_id']}",
                    "payload": artifact_payload,
                    "metadata": {
                        "executor": "openclaw_workspace",
                        "backend_agent_id": backend_agent_id,
                        "backend_model": (agent_meta or {}).get("model"),
                    },
                }
            ],
            "findings": findings,
            "next_action": {
                "type": "RETURN_TO_REQUESTER",
                "reason": next_reason,
                "target_agent": packet["from_agent"],
            },
            "risks": risks,
            "trace": trace,
        }
        self.validator.validate("response_envelope", response)
        return response

    def execute(
        self,
        *,
        packet: dict[str, Any],
        response_path: Path,
        log_path: Path,
        timeout_seconds: int,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = config or {}
        context = self.context_builder.build(packet)
        workspace_root = self._workspace_root(context)
        backend_agent_id = config.get("backend_agent_id") or self._backend_agent_id(packet)
        session_id = config.get("session_id") or self._session_id(packet)
        model_id = str(config.get("model") or self._model_identifier(context))
        thinking = str(config.get("thinking") or "minimal")
        openclaw_bin = str(config.get("openclaw_bin") or self.openclaw_bin)
        openclaw_timeout_seconds = int(config.get("openclaw_timeout_seconds") or max(timeout_seconds - 30, 30))
        session_grace_seconds = int(config.get("session_grace_seconds") or 15)
        before = self._scan_workspace(workspace_root)
        agent_record = self._ensure_agent(
            backend_agent_id=backend_agent_id,
            workspace_ref=str(workspace_root),
            model_id=model_id,
            openclaw_bin=openclaw_bin,
            timeout_seconds=timeout_seconds,
            log_path=log_path,
        )
        prompt = self._build_prompt(context)
        payload = self._run_command(
            [
                openclaw_bin,
                "agent",
                "--agent",
                backend_agent_id,
                "--session-id",
                session_id,
                "--message",
                prompt,
                "--thinking",
                thinking,
                "--timeout",
                str(openclaw_timeout_seconds),
                "--json",
            ],
            timeout_seconds=timeout_seconds,
            log_path=log_path,
            session_dir=self._session_dir(agent_record),
            grace_seconds=session_grace_seconds,
        )
        if not isinstance(payload, dict):
            raise ValueError("OpenClaw agent run did not return an object")
        try:
            visible_text = self._raw_visible_text(payload)
            parsed = self._parse_visible_payload(visible_text)
        except ValueError as exc:
            harvested = self._harvest_session_result(self._session_dir(agent_record))
            if harvested is not None:
                visible_text, parsed, payload = harvested
                self._append_log_note(log_path, "recovered_empty_payload_from_session: True")
            else:
                session_dir = self._session_dir(agent_record)
                backend_model = str(agent_record.get("model") or model_id)
                raise WorkspaceExecutionBlockedError(
                    "OpenClaw response was not usable: "
                    f"{exc}; backend_agent_id={backend_agent_id}; "
                    f"backend_model={backend_model}; session_id={session_id}; "
                    f"session_dir={session_dir or 'n/a'}"
                ) from exc
        after = self._scan_workspace(workspace_root)
        response = self._normalize_response(
            packet=packet,
            parsed=parsed,
            visible_text=visible_text,
            openclaw_payload=payload,
            changed_files=self._changed_files(before, after),
            backend_agent_id=backend_agent_id,
        )
        response_path.write_text(yaml.safe_dump(response, sort_keys=False))
        return response
