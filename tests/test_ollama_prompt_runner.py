from __future__ import annotations

import json
import os
import stat
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from openclaw_agents.runtime.dispatcher import RuntimeDispatcher
from openclaw_agents.runtime.ollama_prompt_runner import OllamaPromptRunner
from openclaw_agents.runtime.worker_runner import RuntimeWorker

from tests.helpers import ControlPlaneHarness, queue_task, seed_project


class OllamaPromptRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = ControlPlaneHarness()

    def tearDown(self) -> None:
        self.harness.cleanup()

    def _write_fake_ollama(self, *, stdout_payload: dict[str, object]) -> Path:
        bin_dir = self.harness.tmp_path / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        fake_ollama = bin_dir / "ollama"
        fake_ollama.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import json",
                    "import sys",
                    "args = sys.argv[1:]",
                    "assert args[0] == 'run'",
                    "model = args[1]",
                    "assert model == 'gemma4:31b'",
                    "prompt = args[2]",
                    "assert 'Return exactly one JSON object' in prompt",
                    "assert 'Design the project' in prompt or 'architecture' in prompt",
                    "assert '\"scope\": \"project\"' in prompt",
                    f"print(json.dumps({json.dumps(stdout_payload, sort_keys=True)}))",
                ]
            )
        )
        fake_ollama.chmod(fake_ollama.stat().st_mode | stat.S_IEXEC)
        return fake_ollama

    def test_runner_normalizes_fake_ollama_response(self) -> None:
        context_path = self.harness.tmp_path / "context.json"
        response_path = self.harness.tmp_path / "response.yaml"
        context_path.write_text(
            json.dumps(
                {
                    "agent": {
                        "agent_id": "architect",
                        "display_name": "Architect",
                        "primary_artifact": "architecture_spec",
                        "prompt_text": "Architect role prompt",
                    },
                    "model": {
                        "profile": "ollama_reasoning",
                        "runtime": "ollama",
                        "model_hint": "gemma4:31b",
                    },
                    "context_scope": "project",
                    "context_root": {
                        "root_path": "/tmp/project_1",
                        "project_root": "/tmp/project_1",
                        "workspace_root": "/tmp",
                    },
                    "context_payload": {
                        "scope": "project",
                        "root": {
                            "root_path": "/tmp/project_1",
                            "project_root": "/tmp/project_1",
                            "workspace_root": "/tmp",
                        },
                        "task": {
                            "task_id": "task_1",
                            "task_type": "DESIGN_ARCHITECTURE",
                            "goal": "Design the project architecture",
                            "priority": "MEDIUM",
                            "from_agent": "niobe",
                            "expected_output": {"artifact_type": "architecture_spec"},
                            "context": {},
                        },
                        "project": {
                            "project_id": "project_1",
                            "goal": "Design the project architecture",
                            "current_phase": "project_design",
                            "current_owner_agent": "architect",
                            "runtime_status": "READY",
                        },
                        "parent_task": None,
                        "workspace": None,
                        "input_artifacts": [],
                        "relevant_artifacts": [],
                        "child_tasks": [],
                    },
                    "task_envelope": {
                        "task_id": "task_1",
                        "project_id": "project_1",
                        "from_agent": "niobe",
                        "to_agent": "architect",
                        "task_type": "DESIGN_ARCHITECTURE",
                        "title": "Design the project",
                        "goal": "Design the project architecture",
                        "priority": "MEDIUM",
                        "context": {},
                        "expected_output": {"artifact_type": "architecture_spec"},
                        "decision_bounds": {},
                        "return_to": "requesting_agent",
                        "metadata": {"run_id": "run_1"},
                    },
                    "project_record": {"project_id": "project_1", "goal": "Design the project architecture"},
                    "parent_task_record": None,
                    "workspace_state": None,
                    "input_artifacts": [],
                    "relevant_artifacts": [],
                    "child_tasks": [],
                },
                indent=2,
                sort_keys=True,
            )
        )
        fake_ollama = self._write_fake_ollama(
            stdout_payload={
                "summary": "Architecture prepared with one service boundary.",
                "findings": ["Use one gateway and one state store."],
                "risks": ["Needs interface hardening."],
            }
        )
        runner = OllamaPromptRunner(ollama_bin=str(fake_ollama), transport="cli")
        response = runner.execute(context_path=context_path, response_path=response_path)

        self.assertEqual(response["agent"], "architect")
        self.assertEqual(response["task_id"], "task_1")
        self.assertEqual(response["trace"]["run_id"], "run_1")
        self.assertEqual(response["artifacts_out"][0]["artifact_type"], "architecture_spec")
        self.assertEqual(response["next_action"]["type"], "RETURN_TO_REQUESTER")
        self.assertEqual(response["next_action"]["target_agent"], "niobe")
        persisted = yaml.safe_load(response_path.read_text())
        self.assertEqual(persisted["summary"], response["summary"])

    def test_parse_output_strips_terminal_noise(self) -> None:
        runner = OllamaPromptRunner(ollama_bin="ollama")
        parsed = runner.parse_output(
            '{"summary": "ok", "findings": []\x1b[7D\x1b[K\n, "risks": [], "next_action": "return"}'
        )
        self.assertEqual(parsed["summary"], "ok")
        self.assertEqual(parsed["next_action"], "return")

    def test_worker_prompt_subprocess_falls_back_to_builtin_ollama_runner(self) -> None:
        store = self.harness.store
        workspace_ref = self.harness.tmp_path / "workspace"
        workspace_ref.mkdir(parents=True, exist_ok=True)
        seed_project(
            store,
            project_id="P_worker_prompt",
            goal="Design a project with the default prompt runner",
            current_phase="project_design",
            current_owner_agent="niobe",
            next_action={"type": "DESIGN_ARCHITECTURE", "target_agent": "architect"},
            workspace_ref=str(workspace_ref),
        )
        store.upsert(
            "workspace_states",
            {
                "workspace_ref": str(workspace_ref),
                "project_id": "P_worker_prompt",
                "repo_root": str(workspace_ref),
                "branch_or_worktree_id": "main",
                "last_clean_commit_or_checkpoint": "checkpoint-1",
                "is_consistent": True,
            },
            conflict_columns=["workspace_ref"],
        )
        task = store.record_task(
            project_id="P_worker_prompt",
            from_agent="niobe",
            to_agent="architect",
            task_type="DESIGN_ARCHITECTURE",
            title="Design the project",
            goal="Design a project with the default prompt runner",
            priority="MEDIUM",
            context={"requirements": ["Return an architecture spec"]},
            expected_output={"artifact_type": "architecture_spec"},
            return_to="requesting_agent",
        )
        dispatcher = RuntimeDispatcher(store, state_dir=self.harness.state_dir)
        queue_task(dispatcher, task)

        worker_config_path = self.harness.tmp_path / "worker_config.yaml"
        worker_config_path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": "1.0.0",
                    "defaults": {
                        "executor": "disabled",
                        "poll_interval_seconds": 1.0,
                        "command_timeout_seconds": 60,
                        "response_dir_name": "runtime_responses",
                    },
                    "agents": {
                        "architect": {
                            "executor": "prompt_subprocess",
                        }
                    },
                },
                sort_keys=False,
            )
        )

        fake_ollama = self._write_fake_ollama(
            stdout_payload={
                "summary": "Default prompt runner produced an architecture spec.",
                "findings": ["Fallback command path executed."],
                "risks": [],
            }
        )
        env_path = f"{fake_ollama.parent}:{os.environ.get('PATH', '')}"
        worker = RuntimeWorker(
            store,
            worker_config_path=worker_config_path,
            state_dir=self.harness.state_dir,
        )
        with patch.dict(
            os.environ,
            {
                "PATH": env_path,
                "OPENCLAW_OLLAMA_TRANSPORT": "cli",
            },
            clear=False,
        ):
            result = worker.process_once(agent_id="architect")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(
            Path(result.response_file),
            workspace_ref / ".agents" / "runtime" / "runtime_responses" / Path(result.response_file).name,
        )
        persisted_task = store.get_task(task["task_id"])
        assert persisted_task is not None
        self.assertEqual(persisted_task["status"], "SUCCESS")
        payload = yaml.safe_load(Path(result.response_file).read_text())
        self.assertEqual(payload["agent"], "architect")
        self.assertEqual(payload["artifacts_out"][0]["artifact_type"], "architecture_spec")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
