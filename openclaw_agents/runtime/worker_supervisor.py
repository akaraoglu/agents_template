"""Supervise one runtime worker process per enabled agent."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from openclaw_agents.runtime.external_executor import PromptSubprocessExecutor


ALLOWED_EXECUTORS = {"disabled", "mock", "builtin", "subprocess", "prompt_subprocess", "openclaw_workspace"}


@dataclass(slots=True)
class WorkerSpec:
    agent_id: str
    executor: str
    command: list[str]
    uses_default_prompt_runner: bool = False


class WorkerSupervisor:
    """Spawn and restart one worker-runner child process per enabled agent."""

    def __init__(
        self,
        *,
        worker_config_path: str | Path | None = None,
        state_dir: str | Path | None = None,
        agent_filter: list[str] | None = None,
        python_executable: str | None = None,
        repo_root: str | Path | None = None,
        restart_delay_seconds: float = 2.0,
        stop_timeout_seconds: float = 10.0,
    ) -> None:
        runtime_dir = Path(__file__).resolve().parent
        self.worker_config_path = Path(worker_config_path or runtime_dir / "worker_config.yaml").resolve()
        self.worker_config = yaml.safe_load(self.worker_config_path.read_text()) or {}
        self.state_dir = Path(state_dir).resolve() if state_dir else None
        self.agent_filter = list(agent_filter or [])
        self.python_executable = python_executable or sys.executable
        self.repo_root = Path(repo_root or runtime_dir.parents[1]).resolve()
        self.restart_delay_seconds = restart_delay_seconds
        self.stop_timeout_seconds = stop_timeout_seconds
        self._stop_requested = False
        self._children: dict[str, subprocess.Popen[str]] = {}

    def _merged_agent_config(self, agent_id: str) -> dict[str, Any]:
        merged = dict(self.worker_config.get("defaults") or {})
        merged.update(((self.worker_config.get("agents") or {}).get(agent_id) or {}))
        return merged

    def _selected_agents(self) -> list[str]:
        agents = list((self.worker_config.get("agents") or {}).keys())
        if not self.agent_filter:
            return agents
        allowed = set(self.agent_filter)
        return [agent_id for agent_id in agents if agent_id in allowed]

    def enabled_agents(self) -> list[str]:
        enabled: list[str] = []
        for agent_id in self._selected_agents():
            executor = self._merged_agent_config(agent_id).get("executor", "disabled")
            if executor != "disabled":
                enabled.append(agent_id)
        return enabled

    @staticmethod
    def _command_preview(command: list[str] | str | None) -> list[str]:
        if not command:
            return []
        if isinstance(command, str):
            return shlex.split(command)
        return [str(part) for part in command]

    @staticmethod
    def _command_resolves(command: list[str]) -> bool:
        if not command:
            return False
        binary = command[0]
        if not binary or "{" in binary:
            return True
        if os.path.isabs(binary):
            return Path(binary).exists()
        if "/" in binary:
            return Path(binary).exists()
        return shutil.which(binary) is not None

    def build_worker_command(self, agent_id: str) -> list[str]:
        command = [
            self.python_executable,
            "-m",
            "openclaw_agents.runtime.worker_runner",
            "--config",
            str(self.worker_config_path),
            "--agent",
            agent_id,
        ]
        if self.state_dir:
            command.extend(["--state-dir", str(self.state_dir)])
        return command

    def worker_specs(self) -> list[WorkerSpec]:
        specs: list[WorkerSpec] = []
        for agent_id in self.enabled_agents():
            config = self._merged_agent_config(agent_id)
            executor = str(config.get("executor", "disabled"))
            specs.append(
                WorkerSpec(
                    agent_id=agent_id,
                    executor=executor,
                    command=self.build_worker_command(agent_id),
                    uses_default_prompt_runner=(executor == "prompt_subprocess" and not config.get("command")),
                )
            )
        return specs

    def check_configuration(self) -> dict[str, Any]:
        problems: list[str] = []
        warnings: list[str] = []
        workers: list[dict[str, Any]] = []
        declared_agents = set((self.worker_config.get("agents") or {}).keys())
        for requested in self.agent_filter:
            if requested not in declared_agents:
                problems.append(f"requested agent `{requested}` is not present in worker_config.yaml")

        for agent_id in self._selected_agents():
            config = self._merged_agent_config(agent_id)
            executor = str(config.get("executor", "disabled"))
            if executor not in ALLOWED_EXECUTORS:
                problems.append(f"agent `{agent_id}` has unsupported executor `{executor}`")
                continue
            uses_default_prompt_runner = executor == "prompt_subprocess" and not config.get("command")
            external_command = self._command_preview(config.get("command"))
            if executor == "subprocess":
                if not external_command:
                    problems.append(f"agent `{agent_id}` uses `subprocess` but has no command configured")
                elif not self._command_resolves(external_command):
                    problems.append(f"agent `{agent_id}` command does not resolve: {external_command[0]}")
            if executor == "prompt_subprocess" and external_command and not self._command_resolves(external_command):
                problems.append(f"agent `{agent_id}` prompt_subprocess command does not resolve: {external_command[0]}")
            if executor == "disabled":
                continue
            if uses_default_prompt_runner:
                warnings.append(
                    f"agent `{agent_id}` will use the built-in Ollama prompt runner with model hints from model_map.yaml"
                )
            workers.append(
                {
                    "agent_id": agent_id,
                    "executor": executor,
                    "worker_command": self.build_worker_command(agent_id),
                    "external_command": external_command,
                    "uses_default_prompt_runner": uses_default_prompt_runner,
                }
            )

        if not workers:
            problems.append("no enabled workers found in worker_config.yaml for the requested selection")

        summary = {
            "worker_config_path": str(self.worker_config_path),
            "repo_root": str(self.repo_root),
            "state_dir": str(self.state_dir) if self.state_dir else None,
            "enabled_agents": [worker["agent_id"] for worker in workers],
            "workers": workers,
            "problems": problems,
            "warnings": warnings,
            "default_prompt_runner_command": PromptSubprocessExecutor.default_command(),
        }
        summary["ok"] = not problems
        return summary

    def _handle_signal(self, *_args: object) -> None:
        self._stop_requested = True

    def _spawn_worker(self, spec: WorkerSpec) -> subprocess.Popen[str]:
        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        process = subprocess.Popen(
            spec.command,
            cwd=self.repo_root,
            env=env,
            text=True,
        )
        self._children[spec.agent_id] = process
        print(
            json.dumps(
                {
                    "event": "worker_started",
                    "agent_id": spec.agent_id,
                    "executor": spec.executor,
                    "pid": process.pid,
                    "command": spec.command,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return process

    def _terminate_children(self) -> None:
        for process in self._children.values():
            if process.poll() is None:
                process.terminate()
        deadline = time.time() + self.stop_timeout_seconds
        while time.time() < deadline:
            if all(process.poll() is not None for process in self._children.values()):
                return
            time.sleep(0.2)
        for process in self._children.values():
            if process.poll() is None:
                process.kill()

    def serve_forever(self) -> int:
        summary = self.check_configuration()
        if not summary["ok"]:
            raise RuntimeError("worker supervisor configuration invalid:\n" + json.dumps(summary, indent=2, sort_keys=True))
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        specs = {spec.agent_id: spec for spec in self.worker_specs()}
        for spec in specs.values():
            self._spawn_worker(spec)

        while not self._stop_requested:
            for agent_id, process in list(self._children.items()):
                returncode = process.poll()
                if returncode is None:
                    continue
                print(
                    json.dumps(
                        {
                            "event": "worker_exited",
                            "agent_id": agent_id,
                            "returncode": returncode,
                        },
                        sort_keys=True,
                    ),
                    flush=True,
                )
                if self._stop_requested:
                    continue
                time.sleep(self.restart_delay_seconds)
                self._spawn_worker(specs[agent_id])
            time.sleep(0.5)

        self._terminate_children()
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supervise one runtime worker process per enabled agent")
    parser.add_argument("--config", default=str(Path(__file__).with_name("worker_config.yaml")))
    parser.add_argument("--state-dir", help="Override the runtime packet state directory passed to worker children")
    parser.add_argument("--agent", action="append", help="Restrict supervision to one or more agent ids")
    parser.add_argument("--check", action="store_true", help="Validate config and print a JSON summary")
    parser.add_argument("--restart-delay", type=float, default=2.0, help="Delay in seconds before restarting a worker")
    parser.add_argument("--stop-timeout", type=float, default=10.0, help="Graceful shutdown timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    supervisor = WorkerSupervisor(
        worker_config_path=args.config,
        state_dir=args.state_dir,
        agent_filter=args.agent,
        restart_delay_seconds=args.restart_delay,
        stop_timeout_seconds=args.stop_timeout,
    )
    if args.check:
        summary = supervisor.check_configuration()
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0 if summary["ok"] else 1
    return supervisor.serve_forever()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
