"""Queue-backed worker runner for runtime task packets."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from openclaw_agents.database.store import ControlPlaneStore, utc_now
from openclaw_agents.runtime.dispatcher import ContractValidator, RuntimeDispatcher
from openclaw_agents.runtime.external_executor import PromptSubprocessExecutor
from openclaw_agents.runtime.openclaw_workspace_executor import (
    OpenClawWorkspaceExecutor,
    WorkspaceExecutionBlockedError,
)
from openclaw_agents.runtime.project_state import ProjectStateLayout
from openclaw_agents.runtime.role_executor import BuiltinRoleExecutor


TERMINAL_RESPONSE_STATUS = {"SUCCESS", "NEEDS_CLARIFICATION", "BLOCKED", "FAILED", "CANCELLED"}


@dataclass(slots=True)
class WorkerExecutionResult:
    run_id: str
    task_id: str
    agent_id: str
    status: str
    summary: str
    response_file: str


class RuntimeWorker:
    """Claim pending runtime packets and execute them through configured adapters."""

    def __init__(
        self,
        store: ControlPlaneStore | None = None,
        *,
        worker_config_path: str | Path | None = None,
        state_dir: str | Path | None = None,
        default_executor: str | None = None,
    ) -> None:
        self.store = store or ControlPlaneStore()
        base = Path(__file__).resolve().parents[1]
        self.worker_config_path = Path(worker_config_path or Path(__file__).with_name("worker_config.yaml"))
        self.worker_config = yaml.safe_load(self.worker_config_path.read_text())
        self.default_executor_override = default_executor
        self.dispatcher = RuntimeDispatcher(self.store, state_dir=state_dir)
        self.validator = ContractValidator(base / "schemas")
        self.agent_registry = yaml.safe_load((base / "config" / "agent_registry.yaml").read_text())
        self.role_executor = BuiltinRoleExecutor(store=self.store, dispatcher=self.dispatcher)
        self.prompt_subprocess_executor = PromptSubprocessExecutor(self.store)
        self.openclaw_workspace_executor = OpenClawWorkspaceExecutor(self.store)

    def _agent_config(self, agent_id: str) -> dict[str, Any]:
        merged = dict(self.worker_config.get("defaults") or {})
        merged.update(((self.worker_config.get("agents") or {}).get(agent_id) or {}))
        if self.default_executor_override:
            merged["executor"] = self.default_executor_override
        return merged

    def _response_path(self, *, packet_path: Path, workspace_ref: str | None, task_id: str, attempt_id: str) -> Path:
        dir_name = (self.worker_config.get("defaults") or {}).get("response_dir_name", "runtime_responses")
        if workspace_ref:
            layout = ProjectStateLayout.from_workspace(workspace_ref)
            root = layout.ensure_runtime_dirs(response_dir_name=dir_name)
        else:
            root = self.dispatcher.state_dir / "responses"
        root.mkdir(parents=True, exist_ok=True)
        return root / f"{task_id}_{attempt_id}.yaml"

    def _log_path(self, response_path: Path) -> Path:
        return response_path.with_suffix(".log")

    def _read_packet(self, packet_path: Path) -> dict[str, Any]:
        payload = yaml.safe_load(packet_path.read_text())
        if not isinstance(payload, dict):
            raise ValueError(f"{packet_path} did not decode to an object")
        self.validator.validate("task_envelope", payload)
        return payload

    def _primary_artifact_type(self, agent_id: str, packet: dict[str, Any]) -> str:
        expected = packet.get("expected_output") or {}
        if expected.get("artifact_type"):
            return expected["artifact_type"]
        agent = ((self.agent_registry.get("agents") or {}).get(agent_id) or {})
        return agent.get("primary_artifact", "project_status_report")

    def _mock_artifact_payload(self, artifact_type: str, packet: dict[str, Any], summary: str) -> Any:
        task_id = packet["task_id"]
        project_id = packet["project_id"]
        base = {
            "summary": summary,
            "project_id": project_id,
            "task_id": task_id,
            "generated_by": packet["to_agent"],
        }
        if artifact_type == "project_charter":
            return {
                **base,
                "goal": packet["goal"],
                "requirements": [packet["goal"]],
                "constraints": [],
                "acceptance_criteria": [],
                "priority": packet["priority"],
                "assigned_orchestrator": "niaobe",
            }
        if artifact_type == "architecture_spec":
            return {
                **base,
                "design_decisions": [],
                "interfaces": [],
                "risks": [],
                "assumptions": [],
                "open_questions": [],
            }
        if artifact_type == "software_task_plan":
            return {
                **base,
                "task_breakdown": [packet["goal"]],
                "implementation_steps": [],
                "test_obligations": [],
                "risks": [],
                "open_questions": [],
            }
        if artifact_type == "code_change":
            return {
                **base,
                "changed_files": [],
                "build_notes": "mock executor did not build code",
                "known_limitations": ["mock executor output"],
                "handoff_notes_for_tester": [],
            }
        if artifact_type == "test_execution_report":
            return {
                **base,
                "test_changes": [],
                "commands_run": [],
                "result": "PASS",
                "failures": [],
                "failure_cause": None,
                "coverage_notes": ["mock executor output"],
            }
        if artifact_type == "software_delivery_package":
            return {
                **base,
                "implemented_changes": [],
                "test_changes": [],
                "test_execution_report": "mock executor output",
                "known_limitations": ["mock executor output"],
                "recommended_next_step": "return_to_requester",
            }
        if artifact_type == "verification_report":
            return {
                **base,
                "result": "PASS",
                "evidence": [],
                "defects": [],
                "defect_category": None,
                "confidence": "LOW",
                "recommended_next_action": "return_to_requester",
            }
        return base

    def _mock_response(self, packet: dict[str, Any], response_path: Path) -> dict[str, Any]:
        artifact_type = self._primary_artifact_type(packet["to_agent"], packet)
        summary = f"Mock executor completed {packet['task_type']} for {packet['project_id']}."
        artifact_ref = str(response_path.parent / f"{packet['task_id']}_{artifact_type}.yaml")
        response = {
            "task_id": packet["task_id"],
            "project_id": packet["project_id"],
            "agent": packet["to_agent"],
            "status": "SUCCESS",
            "summary": summary,
            "artifacts_out": [
                {
                    "artifact_type": artifact_type,
                    "ref": artifact_ref,
                    "payload": self._mock_artifact_payload(artifact_type, packet, summary),
                    "filename": Path(artifact_ref).name,
                    "metadata": {"executor": "mock"},
                }
            ],
            "findings": ["mock executor path"],
            "next_action": {"type": "RETURN_TO_REQUESTER", "reason": "mock executor completed the task"},
            "risks": ["result generated by mock executor"],
            "trace": {"run_id": packet["metadata"]["run_id"]},
        }
        response_path.write_text(yaml.safe_dump(response, sort_keys=False))
        return response

    def _subprocess_response(
        self,
        packet: dict[str, Any],
        response_path: Path,
        *,
        command: list[str] | str,
        timeout_seconds: int,
        workspace_ref: str | None,
    ) -> dict[str, Any]:
        if isinstance(command, str):
            command_parts = shlex.split(command)
        else:
            command_parts = list(command)
        values = {
            "packet": packet["metadata"]["packet_ref"],
            "response_file": str(response_path),
            "task_id": packet["task_id"],
            "project_id": packet["project_id"],
            "agent_id": packet["to_agent"],
            "workspace_ref": workspace_ref or "",
            "run_id": packet["metadata"]["run_id"],
        }
        rendered = [part.format(**values) for part in command_parts]
        env = {
            **dict(os.environ),
            "OPENCLAW_TASK_PACKET": values["packet"],
            "OPENCLAW_RESPONSE_FILE": values["response_file"],
            "OPENCLAW_TASK_ID": values["task_id"],
            "OPENCLAW_PROJECT_ID": values["project_id"],
            "OPENCLAW_AGENT_ID": values["agent_id"],
            "OPENCLAW_WORKSPACE_REF": values["workspace_ref"],
            "OPENCLAW_RUN_ID": values["run_id"],
        }
        completed = subprocess.run(
            rendered,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
        self._log_path(response_path).write_text(
            f"command: {rendered}\nreturncode: {completed.returncode}\n\nstdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}\n"
        )
        if response_path.exists():
            payload = yaml.safe_load(response_path.read_text())
            if not isinstance(payload, dict):
                raise ValueError(f"{response_path} did not decode to an object")
            return payload
        if completed.returncode != 0:
            raise RuntimeError(f"executor returned {completed.returncode}: {completed.stderr.strip() or completed.stdout.strip()}")
        if completed.stdout.strip():
            try:
                payload = yaml.safe_load(completed.stdout)
            except Exception as exc:  # pragma: no cover - yaml parser detail
                raise RuntimeError("executor completed without response file and stdout was not valid YAML") from exc
            if not isinstance(payload, dict):
                raise RuntimeError("executor stdout did not decode to an object")
            response_path.write_text(yaml.safe_dump(payload, sort_keys=False))
            return payload
        raise RuntimeError("executor completed without producing a response envelope")

    def _failure_response(self, packet: dict[str, Any], summary: str, *, status: str = "FAILED") -> dict[str, Any]:
        return {
            "task_id": packet["task_id"],
            "project_id": packet["project_id"],
            "agent": packet["to_agent"],
            "status": status,
            "summary": summary,
            "artifacts_out": [],
            "findings": [summary],
            "next_action": {"type": "RETURN_TO_REQUESTER", "reason": summary},
            "risks": [summary],
            "trace": {"run_id": packet["metadata"]["run_id"]},
        }

    def _execute_packet(self, packet: dict[str, Any], config: dict[str, Any], response_path: Path) -> dict[str, Any] | None:
        executor = config.get("executor", "disabled")
        if executor == "disabled":
            return None
        if executor == "mock":
            return self._mock_response(packet, response_path)
        if executor == "builtin":
            response = self.role_executor.execute(packet)
            response_path.write_text(yaml.safe_dump(response, sort_keys=False))
            self._log_path(response_path).write_text(
                f"executor: builtin\nagent: {packet['to_agent']}\ntask_id: {packet['task_id']}\n"
            )
            return response
        if executor == "subprocess":
            command = config.get("command")
            if not command:
                raise RuntimeError(f"subprocess executor is missing command for {packet['to_agent']}")
            timeout_seconds = int(config.get("command_timeout_seconds", 3600))
            return self._subprocess_response(
                packet,
                response_path,
                command=command,
                timeout_seconds=timeout_seconds,
                workspace_ref=packet["metadata"].get("workspace_ref"),
            )
        if executor == "prompt_subprocess":
            command = config.get("command") or self.prompt_subprocess_executor.default_command()
            timeout_seconds = int(config.get("command_timeout_seconds", 3600))
            return self.prompt_subprocess_executor.execute(
                packet=packet,
                response_path=response_path,
                log_path=self._log_path(response_path),
                command=command,
                timeout_seconds=timeout_seconds,
            )
        if executor == "openclaw_workspace":
            timeout_seconds = int(config.get("command_timeout_seconds", 3600))
            return self.openclaw_workspace_executor.execute(
                packet=packet,
                response_path=response_path,
                log_path=self._log_path(response_path),
                timeout_seconds=timeout_seconds,
                config=config,
            )
        raise RuntimeError(f"unsupported executor {executor}")

    def _claim_run(self, run: dict[str, Any]) -> bool:
        now = utc_now()
        with self.store.project_transaction(run["project_id"]) as conn:
            claimed = self.store.claim_agent_run(run["run_id"], started_at=now, conn=conn)
            if not claimed:
                return False
            attempt = self.store.get_active_task_attempt(run["task_id"], conn=conn) or self.store.get_latest_task_attempt(
                run["task_id"],
                conn=conn,
            )
            if attempt:
                self.store.update(
                    "task_attempts",
                    {"status": "RUNNING", "started_at": attempt.get("started_at") or now},
                    where_clause="attempt_id = ?",
                    where_params=[attempt["attempt_id"]],
                    conn=conn,
                )
            self.store.update(
                "tasks",
                {"status": "RUNNING", "updated_at": now},
                where_clause="task_id = ?",
                where_params=[run["task_id"]],
                conn=conn,
            )
        return True

    def process_once(self, *, agent_id: str | None = None) -> WorkerExecutionResult | None:
        for run in self.store.list_pending_runtime_runs(agent_id=agent_id):
            config = self._agent_config(run["agent_id"])
            if config.get("executor", "disabled") == "disabled":
                continue
            if not self._claim_run(run):
                continue
            packet_path = Path(run["log_ref"])
            packet = self._read_packet(packet_path)
            response_path = self._response_path(
                packet_path=packet_path,
                workspace_ref=run.get("workspace_ref"),
                task_id=run["task_id"],
                attempt_id=run["session_id"],
            )
            try:
                response = self._execute_packet(packet, config, response_path)
                if response is None:
                    return None
            except WorkspaceExecutionBlockedError as exc:
                response = self._failure_response(packet, f"worker execution blocked: {exc}", status="BLOCKED")
                response_path.write_text(yaml.safe_dump(response, sort_keys=False))
                log_path = self._log_path(response_path)
                if not log_path.exists():
                    log_path.write_text(f"worker execution blocked: {exc}\n")
            except Exception as exc:
                response = self._failure_response(packet, f"worker execution failed: {exc}")
                response_path.write_text(yaml.safe_dump(response, sort_keys=False))
                log_path = self._log_path(response_path)
                if not log_path.exists():
                    log_path.write_text(f"worker execution failed: {exc}\n")

            self.store.update(
                "agent_runs",
                {
                    "raw_transcript_ref": str(response_path),
                    "log_ref": str(self._log_path(response_path)),
                },
                where_clause="run_id = ?",
                where_params=[run["run_id"]],
            )
            record = self.dispatcher.record_response(response)
            self.role_executor.handle_recorded_response(response, record)
            return WorkerExecutionResult(
                run_id=record.run_id,
                task_id=record.task_id,
                agent_id=record.agent_id,
                status=record.status,
                summary=response["summary"],
                response_file=str(response_path),
            )
        return None

    def serve_forever(self, *, agent_id: str | None = None, poll_interval: float | None = None) -> None:
        interval = poll_interval
        if interval is None:
            interval = float((self.worker_config.get("defaults") or {}).get("poll_interval_seconds", 1.0))
        while True:
            self.process_once(agent_id=agent_id)
            time.sleep(interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run queue-backed runtime workers")
    parser.add_argument("--config", default=str(Path(__file__).with_name("worker_config.yaml")))
    parser.add_argument("--state-dir", help="Override the runtime packet state directory")
    parser.add_argument("--agent", help="Process only runs for one agent id")
    parser.add_argument("--default-executor", choices=["disabled", "mock", "builtin", "subprocess", "prompt_subprocess", "openclaw_workspace"])
    parser.add_argument("--once", action="store_true", help="Process at most one run and exit")
    parser.add_argument("--poll-interval", type=float, help="Override poll interval in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    worker = RuntimeWorker(
        worker_config_path=args.config,
        state_dir=args.state_dir,
        default_executor=args.default_executor,
    )
    if args.once:
        result = worker.process_once(agent_id=args.agent)
        if result is None:
            print("no runnable work found")
            return 0
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
        return 0
    worker.serve_forever(agent_id=args.agent, poll_interval=args.poll_interval)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
