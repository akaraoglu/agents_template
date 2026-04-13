from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import yaml

from openclaw_agents.runtime.worker_supervisor import WorkerSupervisor

from tests.helpers import ControlPlaneHarness


class WorkerSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = ControlPlaneHarness()

    def tearDown(self) -> None:
        self.harness.cleanup()

    def test_check_configuration_lists_enabled_agents_and_default_prompt_runner(self) -> None:
        worker_config_path = self.harness.tmp_path / "worker_config.yaml"
        worker_config_path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": "1.0.0",
                    "defaults": {
                        "executor": "disabled",
                        "poll_interval_seconds": 1.0,
                        "command_timeout_seconds": 60,
                    },
                    "agents": {
                        "architect": {"executor": "prompt_subprocess"},
                        "morpheus": {"executor": "builtin"},
                        "oracle": {"executor": "disabled"},
                    },
                },
                sort_keys=False,
            )
        )
        supervisor = WorkerSupervisor(
            worker_config_path=worker_config_path,
            state_dir=self.harness.state_dir,
            python_executable=sys.executable,
            repo_root=self.harness.tmp_path,
        )

        summary = supervisor.check_configuration()

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["enabled_agents"], ["architect", "morpheus"])
        architect = next(worker for worker in summary["workers"] if worker["agent_id"] == "architect")
        self.assertTrue(architect["uses_default_prompt_runner"])
        self.assertIn("--state-dir", architect["worker_command"])
        self.assertTrue(summary["warnings"])

    def test_build_worker_command_and_agent_filter(self) -> None:
        worker_config_path = self.harness.tmp_path / "worker_config.yaml"
        worker_config_path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": "1.0.0",
                    "defaults": {"executor": "disabled"},
                    "agents": {
                        "architect": {"executor": "prompt_subprocess"},
                        "implementer": {"executor": "subprocess", "command": [sys.executable, "-c", "print('ok')"]},
                    },
                },
                sort_keys=False,
            )
        )
        supervisor = WorkerSupervisor(
            worker_config_path=worker_config_path,
            state_dir=self.harness.state_dir,
            agent_filter=["implementer"],
            python_executable=sys.executable,
            repo_root=self.harness.tmp_path,
        )

        self.assertEqual(supervisor.enabled_agents(), ["implementer"])
        command = supervisor.build_worker_command("implementer")
        self.assertEqual(
            command,
            [
                sys.executable,
                "-m",
                "openclaw_agents.runtime.worker_runner",
                "--config",
                str(worker_config_path.resolve()),
                "--agent",
                "implementer",
                "--state-dir",
                str(self.harness.state_dir.resolve()),
            ],
        )
        summary = supervisor.check_configuration()
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["enabled_agents"], ["implementer"])

    def test_check_configuration_fails_when_filtered_agent_is_disabled(self) -> None:
        worker_config_path = self.harness.tmp_path / "worker_config.yaml"
        worker_config_path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": "1.0.0",
                    "defaults": {"executor": "disabled"},
                    "agents": {
                        "architect": {"executor": "disabled"},
                    },
                },
                sort_keys=False,
            )
        )
        supervisor = WorkerSupervisor(
            worker_config_path=worker_config_path,
            agent_filter=["architect"],
            python_executable=sys.executable,
            repo_root=self.harness.tmp_path,
        )

        summary = supervisor.check_configuration()

        self.assertFalse(summary["ok"])
        self.assertIn("no enabled workers found", summary["problems"][0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
