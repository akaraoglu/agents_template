from __future__ import annotations

import json
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "AgenticTeam" / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from worker_contracts import ARCHITECT_CONTRACT, MORPHEUS_CONTRACT, SMITH_PLANNING_CONTRACT
from agent_runner import complete_artifact_run_graph, print_repair_brief
from niaobe_run_task import accept_task_handoff, continue_child_result
from oracle_run_task import verify_task
from worker_runtime import (
    WorkerRuntimeError,
    complete_artifact_run,
    complete_planning_run,
    complete_run,
    autoplan_required_planning_project,
    main_for_contract,
    main_for_artifact_contract,
    main_for_planning_contract,
    parse_envelope,
    parse_planning_envelope,
    prepare_artifact_run,
    prepare_planning_run,
    prepare_run,
)


def helper_read_output(path: str, content: str) -> str:
    payload = {
        "status": "OK",
        "project_id": "demo-project",
        "phase": "PROJECT",
        "action": "project_read",
        "evidence": path,
        "details": "ok",
        "retryable": False,
    }
    return f"OUTCOME_JSON: {json.dumps(payload, separators=(',', ':'))}\nCONTENT_BEGIN\n{content.rstrip()}\nCONTENT_END\n"


def helper_ok_output(action: str) -> str:
    payload = {
        "status": "OK",
        "project_id": "demo-project",
        "phase": "DESIGN",
        "action": action,
        "evidence": "artifact",
        "details": "ok",
        "retryable": False,
    }
    return f"OUTCOME_JSON: {json.dumps(payload, separators=(',', ':'))}\n"


def valid_architect_draft() -> str:
    return (
        "\n".join(
            [
                "# T001",
                "## Overview",
                "Overview text.",
                "## Approach",
                "Approach text.",
                "## File Changes",
                "File changes text.",
                "## Interfaces",
                "Interfaces text.",
                "## Risks",
                "Risks text.",
                "## Implementation Notes",
                "Notes text.",
                "## Test Strategy",
                "Strategy text.",
            ]
        )
        + "\n"
    )


class WorkerRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.workspace_root = Path(self.temp_dir.name) / "workspaces"
        self.bin_root = Path(self.temp_dir.name) / "bin"
        self.project_path = Path(self.temp_dir.name) / "projects" / "demo-project"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.bin_root.mkdir(parents=True, exist_ok=True)
        self.project_path.mkdir(parents=True, exist_ok=True)
        self.env_patch = mock.patch.dict(
            os.environ,
            {
                "CLAWSPACE_WORKSPACE_ROOT": str(self.workspace_root),
                "CLAWSPACE_BIN_ROOT": str(self.bin_root),
            },
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _fake_run(self, cmd: list[str], capture_output: bool = True, text: bool = True, timeout: int = 120):
        del capture_output, text, timeout
        joined = " ".join(cmd)
        if cmd[:3] == ["bash", str(self.bin_root / "resolve_project.sh"), "demo-project"]:
            return mock.Mock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "project_id": "demo-project",
                        "project_path": str(self.project_path),
                    }
                ),
                stderr="",
            )
        if cmd[:2] == ["bash", str(self.bin_root / "project_read.sh")]:
            requested = cmd[3]
            content = {
                "PROJECT.md": "\n".join(
                    [
                        "# Demo Project",
                        "",
                        "## Required Plan",
                        "## Overview",
                        "Build the deterministic demo project.",
                        "",
                        "## Phases",
                        "1. **T001: First Task**",
                        "   - Do the first task.",
                        "2. **T002: Second Task**",
                        "   - Do the second task.",
                        "",
                        "## Required Outputs",
                        "- README.md",
                        "- src/main.py",
                        "- tests/test_main.py",
                        "",
                    ]
                ),
                "PROJECT_STATE.md": "# Project State\n- **owner**: smith\n",
                "CURRENT_TASK.md": "# Current Task\n",
                "management/tasks/T001.md": "# Task T001\n",
                "management/architecture/T001.md": "# Architecture T001\n",
            }[requested]
            return mock.Mock(returncode=0, stdout=helper_read_output(requested, content), stderr="")
        if cmd[:2] == ["bash", str(self.bin_root / "project_mkdir.sh")]:
            return mock.Mock(returncode=0, stdout=helper_ok_output("mkdir"), stderr="")
        if cmd[:2] == ["bash", str(self.bin_root / "project_write.sh")]:
            return mock.Mock(returncode=0, stdout=helper_ok_output("write"), stderr="")
        if cmd[:2] == ["bash", str(self.bin_root / "verify_artifact.sh")]:
            return mock.Mock(returncode=0, stdout=helper_ok_output("verify"), stderr="")
        if cmd[:2] == ["bash", str(self.bin_root / "ack_handoff.sh")]:
            return mock.Mock(returncode=0, stdout="ACK_READY\nSTATUS: RECEIVED\n", stderr="")
        if cmd[:2] == ["bash", str(self.bin_root / "write_state.sh")]:
            return mock.Mock(returncode=0, stdout=helper_ok_output("write_state"), stderr="")
        if cmd[:2] == ["bash", str(self.bin_root / "handoff.sh")]:
            from_agent = cmd[2]
            to_agent = cmd[3]
            phase = cmd[6]
            task_id = cmd[7] if len(cmd) > 7 else "T001"
            return mock.Mock(
                returncode=0,
                stdout=(
                    "HANDOFF_READY\n"
                    "ENVELOPE: "
                    + json.dumps(
                        {
                            "project_id": "demo-project",
                            "from": from_agent,
                            "to": to_agent,
                            "phase": phase,
                            "instructions": "Task T001 is ready.",
                            "task_id": task_id,
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                ),
                stderr="",
            )
        if cmd[:2] == ["bash", str(self.bin_root / "project_exec.sh")]:
            return mock.Mock(returncode=0, stdout=helper_ok_output("exec") + "OK\n", stderr="")
        if cmd[:4] == ["openclaw", "gateway", "call", "sessions.send"]:
            return mock.Mock(returncode=0, stdout='{"ok":true}', stderr="")
        raise AssertionError(f"unexpected command: {joined}")

    def test_parse_envelope_rejects_project_path(self) -> None:
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "architect",
                "phase": "DESIGN",
                "instructions": "Do the design.",
                "project_path": "/tmp/escape",
            }
        )
        with self.assertRaises(WorkerRuntimeError):
            parse_envelope(envelope, ARCHITECT_CONTRACT)

    def test_parse_planning_envelope_rejects_project_path(self) -> None:
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "from": "neo",
                "to": "smith",
                "phase": "HANDOFF",
                "instructions": "Plan the project.",
                "project_path": "/tmp/escape",
            }
        )
        with self.assertRaises(WorkerRuntimeError):
            parse_planning_envelope(envelope, SMITH_PLANNING_CONTRACT)

    @mock.patch("worker_runtime.subprocess.run")
    def test_prepare_creates_context_and_handoff_files(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "architect",
                "phase": "DESIGN",
                "instructions": "Design the task.",
            }
        )
        prepared = prepare_run(ARCHITECT_CONTRACT, envelope)
        self.assertTrue(prepared.run_dir.exists())
        self.assertTrue(prepared.context_file.exists())
        self.assertTrue(prepared.handoff_file.exists())
        handoff = json.loads(prepared.handoff_file.read_text(encoding="utf-8"))
        self.assertEqual(handoff["output_path"], "management/architecture/T001.md")
        self.assertIn("PROJECT.md", prepared.context_file.read_text(encoding="utf-8"))

    @mock.patch("worker_runtime.subprocess.run")
    def test_architect_prepare_prints_work_order_and_template(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "architect",
                "phase": "DESIGN",
                "instructions": "Design the task.",
            }
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            prepare_run(ARCHITECT_CONTRACT, envelope)

        output = stdout.getvalue()
        self.assertIn("WORK_ORDER_BEGIN", output)
        self.assertIn("--- PROJECT.md ---", output)
        self.assertIn("DRAFT_TEMPLATE_BEGIN", output)
        self.assertIn("## Test Strategy", output)

    @mock.patch("worker_runtime.subprocess.run")
    def test_complete_sends_done_after_import_and_verify(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "architect",
                "phase": "DESIGN",
                "instructions": "Design the task.",
            }
        )
        prepared = prepare_run(ARCHITECT_CONTRACT, envelope)
        prepared.draft_file.write_text(valid_architect_draft(), encoding="utf-8")
        state = complete_run(ARCHITECT_CONTRACT, prepared.run_dir)
        self.assertEqual(state["status"], "sent")
        result = json.loads((prepared.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["payload"]["to"], "niaobe")

    @mock.patch("worker_runtime.subprocess.run")
    def test_architect_cli_complete_uses_langgraph_runtime(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "architect",
                "phase": "DESIGN",
                "instructions": "Design the task.",
            }
        )
        prepared = prepare_run(ARCHITECT_CONTRACT, envelope)
        prepared.draft_file.write_text(valid_architect_draft(), encoding="utf-8")

        exit_code = main_for_contract(ARCHITECT_CONTRACT, ["complete", str(prepared.run_dir)])

        self.assertEqual(exit_code, 0)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "sent")
        self.assertEqual(state["runtime_engine"], "langgraph")
        result = json.loads((prepared.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["engine"], "langgraph")

    @mock.patch("worker_runtime.subprocess.run")
    def test_architect_langgraph_first_invalid_draft_requests_repair(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "architect",
                "phase": "DESIGN",
                "instructions": "Design the task.",
            }
        )
        prepared = prepare_run(ARCHITECT_CONTRACT, envelope)
        prepared.draft_file.write_text("# T001\n## Overview\nOnly overview.\n", encoding="utf-8")

        exit_code = main_for_contract(ARCHITECT_CONTRACT, ["complete", str(prepared.run_dir)])

        self.assertEqual(exit_code, 20)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "repair_needed")
        self.assertEqual(state["runtime_engine"], "langgraph")
        self.assertEqual(state["last_error"]["code"], "verification_failed")

    @mock.patch("worker_runtime.subprocess.run")
    def test_architect_langgraph_missing_draft_repair_then_complete(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "architect",
                "phase": "DESIGN",
                "instructions": "Design the task.",
            }
        )
        prepared = prepare_run(ARCHITECT_CONTRACT, envelope)

        first_exit = main_for_contract(ARCHITECT_CONTRACT, ["complete", str(prepared.run_dir)])

        self.assertEqual(first_exit, 20)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "repair_needed")
        self.assertEqual(state["last_error"]["code"], "missing_draft")

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            repair_exit = main_for_contract(ARCHITECT_CONTRACT, ["repair", str(prepared.run_dir)])

        self.assertEqual(repair_exit, 0)
        repair_output = stdout.getvalue()
        self.assertIn("REPAIR_MODE=architecture_draft", repair_output)
        self.assertIn("DRAFT_FILE=", repair_output)
        self.assertIn("NEXT_REQUIRED=", repair_output)

        prepared.draft_file.write_text(valid_architect_draft(), encoding="utf-8")
        second_exit = main_for_contract(ARCHITECT_CONTRACT, ["complete", str(prepared.run_dir)])

        self.assertEqual(second_exit, 0)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "sent")
        self.assertEqual(state["runtime_engine"], "langgraph")
        self.assertEqual(state["completion_attempts"], 2)

    @mock.patch("worker_runtime.subprocess.run")
    def test_complete_marks_verification_failed_when_required_heading_is_missing(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "architect",
                "phase": "DESIGN",
                "instructions": "Design the task.",
            }
        )
        prepared = prepare_run(ARCHITECT_CONTRACT, envelope)
        prepared.draft_file.write_text("# T001\n## Overview\nOnly overview.\n", encoding="utf-8")
        with self.assertRaises(WorkerRuntimeError):
            complete_run(ARCHITECT_CONTRACT, prepared.run_dir)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "verification_failed")

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_artifact_complete_imports_verifies_execs_and_sends_done(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "morpheus",
                "phase": "IMPLEMENT",
                "instructions": "Implement the task.",
            }
        )
        prepared = prepare_artifact_run(MORPHEUS_CONTRACT, envelope)
        state_after_prepare = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(
            state_after_prepare["manifest_write_file"],
            str(Path(state_after_prepare["draft_write_root"]) / "manifest.json"),
        )
        self.assertEqual(Path(state_after_prepare["draft_write_root"]).name, prepared.run_dir.name)
        self.assertEqual(state_after_prepare["required_output_paths"], ["README.md", "src/main.py", "tests/test_main.py"])
        artifacts = {
            "README.md": "# Demo\n",
            "src/main.py": "def main():\n    return 0\n",
            "tests/test_main.py": "import unittest\n\nclass DemoTest(unittest.TestCase):\n    def test_demo(self):\n        self.assertTrue(True)\n",
        }
        for relative_path, content in artifacts.items():
            draft = prepared.draft_dir / relative_path
            draft.parent.mkdir(parents=True, exist_ok=True)
            draft.write_text(content, encoding="utf-8")
        prepared.manifest_file.write_text(
            json.dumps(
                {
                    "artifacts": [{"path": path} for path in artifacts],
                    "test_command": ["python3", "-m", "unittest", "tests/test_main.py"],
                }
            ),
            encoding="utf-8",
        )

        state = complete_artifact_run(MORPHEUS_CONTRACT, prepared.run_dir)

        self.assertEqual(state["status"], "sent")
        self.assertEqual(state["artifacts"], list(artifacts))
        self.assertEqual(state["test_command"], ["python3", "-m", "unittest", "tests/test_main.py"])
        self.assertIn("project_exec.sh", state["project_exec"])
        result = json.loads((prepared.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertTrue(result["payload"]["instructions"].startswith("DONE: Artifacts="))
        ack_calls = [
            call
            for call in run_mock.call_args_list
            if call.args and call.args[0][:2] == ["bash", str(self.bin_root / "ack_handoff.sh")]
        ]
        self.assertEqual(ack_calls, [])

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_prepare_extracts_required_outputs_from_task_inputs(self, run_mock: mock.Mock) -> None:
        def fake_run(cmd: list[str], *args: object, **kwargs: object) -> mock.Mock:
            if cmd[:2] == ["bash", str(self.bin_root / "project_read.sh")]:
                requested = cmd[3]
                content = {
                    "PROJECT.md": "# Demo Project\n\nNo required output section here.\n",
                    "CURRENT_TASK.md": "# Current Task\n",
                    "management/tasks/T001.md": "\n".join(
                        [
                            "# Task T001",
                            "",
                            "## Required Outputs",
                            "- README.md",
                            "- src/main.py",
                            "- tests/test_main.py",
                            "",
                        ]
                    ),
                    "management/architecture/T001.md": "# Architecture T001\n",
                }[requested]
                return mock.Mock(returncode=0, stdout=helper_read_output(requested, content), stderr="")
            return self._fake_run(cmd, *args, **kwargs)

        run_mock.side_effect = fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "morpheus",
                "phase": "IMPLEMENT",
                "instructions": "Implement the task.",
            }
        )

        prepared = prepare_artifact_run(MORPHEUS_CONTRACT, envelope)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(state["required_output_paths"], ["README.md", "src/main.py", "tests/test_main.py"])
        self.assertFalse(state["subteam_required"])
        self.assertTrue(state["virtual_team_enabled"])
        self.assertIn("planner_evidence_file", state["team"])
        self.assertIn("tester_review_file", state["team"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_prepare_prints_virtual_team_paths_without_spawn_blocks(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "morpheus",
                "phase": "IMPLEMENT",
                "instructions": "Implement the task.",
            }
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            prepare_artifact_run(MORPHEUS_CONTRACT, envelope)

        output = stdout.getvalue()
        self.assertIn("TEAM_MODE=langgraph_virtual", output)
        self.assertIn("PLANNER_EVIDENCE_FILE=", output)
        self.assertIn("IMPLEMENTER_CHECKLIST_FILE=", output)
        self.assertIn("TESTER_REVIEW_FILE=", output)
        self.assertIn("ACTION_REQUIRED=", output)
        self.assertIn("BLOCK_COMMAND=", output)
        self.assertIn("NEXT_ACTIONS_BEGIN", output)
        self.assertIn("WORK_ORDER_TRUNCATED=no", output)
        self.assertNotIn("SUBTEAM_MODE=", output)
        self.assertNotIn("SPAWN_TASK_BEGIN", output)

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_prepare_marks_truncated_work_order(self, run_mock: mock.Mock) -> None:
        def fake_run(cmd: list[str], *args: object, **kwargs: object) -> mock.Mock:
            if cmd[:2] == ["bash", str(self.bin_root / "project_read.sh")] and cmd[3] == "management/architecture/T001.md":
                return mock.Mock(
                    returncode=0,
                    stdout=helper_read_output(
                        "management/architecture/T001.md",
                        "# Architecture T001\n\n" + ("Long implementation detail.\n" * 400),
                    ),
                    stderr="",
                )
            return self._fake_run(cmd, *args, **kwargs)

        run_mock.side_effect = fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "morpheus",
                "phase": "IMPLEMENT",
                "instructions": "Implement the task.",
            }
        )

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            prepared = prepare_artifact_run(MORPHEUS_CONTRACT, envelope)

        output = stdout.getvalue()
        context_text = prepared.context_file.read_text(encoding="utf-8")
        self.assertIn("WORK_ORDER_TRUNCATED=yes", output)
        self.assertIn("If WORK_ORDER_TRUNCATED=yes", output)
        self.assertIn("## Full Input Copies", context_text)
        self.assertIn("full source", context_text)
        self.assertLess(len(context_text), 5000)

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_artifact_complete_requires_project_outputs(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "morpheus",
                "phase": "IMPLEMENT",
                "instructions": "Implement the task.",
            }
        )
        prepared = prepare_artifact_run(MORPHEUS_CONTRACT, envelope)
        artifacts = {
            "README.md": "# Demo\n",
            "src/main.py": "def main():\n    return 0\n",
        }
        for relative_path, content in artifacts.items():
            draft = prepared.draft_dir / relative_path
            draft.parent.mkdir(parents=True, exist_ok=True)
            draft.write_text(content, encoding="utf-8")
        prepared.manifest_file.write_text(
            json.dumps(
                {
                    "artifacts": [{"path": path} for path in artifacts],
                    "test_command": ["python3", "-m", "unittest"],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaises(WorkerRuntimeError):
            complete_artifact_run(MORPHEUS_CONTRACT, prepared.run_dir)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "repair_needed")
        self.assertIn("tests/test_main.py", state["last_error"]["message"])

    def _prepare_morpheus_artifacts(self):
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "morpheus",
                "phase": "IMPLEMENT",
                "instructions": "Implement the task.",
            }
        )
        prepared = prepare_artifact_run(MORPHEUS_CONTRACT, envelope)
        artifacts = {
            "README.md": "# Demo\n",
            "src/main.py": "def main():\n    return 0\n",
            "tests/test_main.py": "import unittest\n\nclass DemoTest(unittest.TestCase):\n    def test_demo(self):\n        self.assertTrue(True)\n",
        }
        for relative_path, content in artifacts.items():
            draft = prepared.draft_dir / relative_path
            draft.parent.mkdir(parents=True, exist_ok=True)
            draft.write_text(content, encoding="utf-8")
        prepared.manifest_file.write_text(
            json.dumps(
                {
                    "artifacts": [{"path": path} for path in artifacts],
                    "test_command": ["python3", "-m", "unittest", "tests/test_main.py"],
                }
            ),
            encoding="utf-8",
        )
        return prepared

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_langgraph_complete_imports_verifies_execs_and_sends_done(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        prepared = self._prepare_morpheus_artifacts()

        state = complete_artifact_run_graph(MORPHEUS_CONTRACT, prepared.run_dir)

        self.assertEqual(state["status"], "sent")
        self.assertEqual(state["runtime_engine"], "langgraph")
        self.assertEqual(state["artifacts"], ["README.md", "src/main.py", "tests/test_main.py"])
        result = json.loads((prepared.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["engine"], "langgraph")
        self.assertTrue(result["payload"]["instructions"].startswith("DONE: Artifacts="))
        self.assertEqual(state["planner_result"]["status"], "recorded")
        self.assertEqual(state["implementer_result"]["status"], "recorded")
        self.assertEqual(state["tester_result"]["status"], "approved")
        self.assertIn("Planner Evidence", Path(state["team"]["planner_evidence_file"]).read_text(encoding="utf-8"))
        self.assertIn("Tester Review", Path(state["team"]["tester_review_file"]).read_text(encoding="utf-8"))

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_langgraph_complete_does_not_require_spawned_subteam_results(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        prepared = self._prepare_morpheus_artifacts()

        state = complete_artifact_run_graph(MORPHEUS_CONTRACT, prepared.run_dir)

        self.assertEqual(state["status"], "sent")
        self.assertEqual(state["tester_result"]["status"], "approved")

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_artifact_cli_uses_langgraph_even_if_classic_env_is_set(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        prepared = self._prepare_morpheus_artifacts()

        with mock.patch.dict(os.environ, {"MORPHEUS_RUNTIME_ENGINE": "classic"}, clear=False):
            exit_code = main_for_artifact_contract(MORPHEUS_CONTRACT, ["complete", str(prepared.run_dir)])

        self.assertEqual(exit_code, 0)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "sent")
        self.assertEqual(state["runtime_engine"], "langgraph")

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_langgraph_missing_drafts_stay_recoverable_until_budget(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "morpheus",
                "phase": "IMPLEMENT",
                "instructions": "Implement the task.",
            }
        )
        prepared = prepare_artifact_run(MORPHEUS_CONTRACT, envelope)

        with self.assertRaises(WorkerRuntimeError):
            complete_artifact_run_graph(MORPHEUS_CONTRACT, prepared.run_dir)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "repair_needed")
        self.assertEqual(state["last_error"]["code"], "missing_draft")
        self.assertEqual(state["repair_guard"]["mode"], "missing_outputs")
        self.assertIn("manifest.json", state["repair_guard"]["missing_paths"])
        self.assertIn("src/main.py", state["repair_guard"]["missing_paths"])
        self.assertFalse((prepared.run_dir / "result.json").exists())

        prepared.manifest_file.write_text(
            json.dumps(
                {
                    "artifacts": [
                        {"path": "README.md"},
                        {"path": "src/main.py"},
                        {"path": "tests/test_main.py"},
                    ],
                    "test_command": ["python3", "-m", "unittest", "tests/test_main.py"],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaises(WorkerRuntimeError):
            complete_artifact_run_graph(MORPHEUS_CONTRACT, prepared.run_dir)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "repair_needed")
        self.assertEqual(state["completion_attempts"], 2)
        self.assertEqual(state["repair_guard"]["mode"], "missing_outputs")
        self.assertNotIn("manifest.json", state["repair_guard"]["missing_paths"])
        self.assertEqual(
            state["repair_guard"]["missing_paths"],
            ["README.md", "src/main.py", "tests/test_main.py"],
        )
        self.assertFalse((prepared.run_dir / "result.json").exists())

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_langgraph_first_test_failure_requests_repair(self, run_mock: mock.Mock) -> None:
        def fake_run(cmd: list[str], *args: object, **kwargs: object) -> mock.Mock:
            if cmd[:2] == ["bash", str(self.bin_root / "project_exec.sh")]:
                return mock.Mock(
                    returncode=1,
                    stdout='OUTCOME_JSON: {"status":"FAILED","details":"tests failed"}\nSTDERR_BEGIN\nFAIL\nSTDERR_END\n',
                    stderr="",
                )
            return self._fake_run(cmd, *args, **kwargs)

        run_mock.side_effect = fake_run
        prepared = self._prepare_morpheus_artifacts()

        with self.assertRaises(WorkerRuntimeError):
            complete_artifact_run_graph(MORPHEUS_CONTRACT, prepared.run_dir)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "repair_needed")
        self.assertEqual(state["last_error"]["code"], "test_failed")
        self.assertIn("tests/test_main.py", state["repair_guard"]["test_hashes"])
        self.assertEqual(state["repair_guard"]["allowed_repair_paths"], ["src/main.py"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_langgraph_blocks_test_weakening_after_test_failure(self, run_mock: mock.Mock) -> None:
        def fake_run(cmd: list[str], *args: object, **kwargs: object) -> mock.Mock:
            if cmd[:2] == ["bash", str(self.bin_root / "project_exec.sh")]:
                return mock.Mock(
                    returncode=1,
                    stdout='OUTCOME_JSON: {"status":"FAILED","details":"tests failed"}\nSTDERR_BEGIN\nFAIL\nSTDERR_END\n',
                    stderr="",
                )
            return self._fake_run(cmd, *args, **kwargs)

        run_mock.side_effect = fake_run
        prepared = self._prepare_morpheus_artifacts()
        with self.assertRaises(WorkerRuntimeError):
            complete_artifact_run_graph(MORPHEUS_CONTRACT, prepared.run_dir)
        test_draft = prepared.draft_dir / "tests/test_main.py"
        test_draft.write_text(test_draft.read_text(encoding="utf-8") + "\n# weakened\n", encoding="utf-8")

        with self.assertRaises(WorkerRuntimeError):
            complete_artifact_run_graph(MORPHEUS_CONTRACT, prepared.run_dir)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["blocked_code"], "test_weakening_detected")

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_langgraph_blocks_forbidden_doc_edit_after_test_failure(self, run_mock: mock.Mock) -> None:
        def fake_run(cmd: list[str], *args: object, **kwargs: object) -> mock.Mock:
            if cmd[:2] == ["bash", str(self.bin_root / "project_exec.sh")]:
                return mock.Mock(
                    returncode=1,
                    stdout='OUTCOME_JSON: {"status":"FAILED","details":"tests failed"}\nSTDERR_BEGIN\nFAIL\nSTDERR_END\n',
                    stderr="",
                )
            return self._fake_run(cmd, *args, **kwargs)

        run_mock.side_effect = fake_run
        prepared = self._prepare_morpheus_artifacts()
        with self.assertRaises(WorkerRuntimeError):
            complete_artifact_run_graph(MORPHEUS_CONTRACT, prepared.run_dir)
        readme_draft = prepared.draft_dir / "README.md"
        readme_draft.write_text(readme_draft.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")

        with self.assertRaises(WorkerRuntimeError):
            complete_artifact_run_graph(MORPHEUS_CONTRACT, prepared.run_dir)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["blocked_code"], "forbidden_repair_edit")

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_langgraph_repair_brief_requires_repair_needed_state(self, run_mock: mock.Mock) -> None:
        def fake_run(cmd: list[str], *args: object, **kwargs: object) -> mock.Mock:
            if cmd[:2] == ["bash", str(self.bin_root / "project_exec.sh")]:
                return mock.Mock(
                    returncode=1,
                    stdout='OUTCOME_JSON: {"status":"FAILED","details":"tests failed"}\nSTDERR_BEGIN\nFAIL\nSTDERR_END\n',
                    stderr="",
                )
            return self._fake_run(cmd, *args, **kwargs)

        run_mock.side_effect = fake_run
        prepared = self._prepare_morpheus_artifacts()
        with self.assertRaises(WorkerRuntimeError):
            complete_artifact_run_graph(MORPHEUS_CONTRACT, prepared.run_dir)

        state = print_repair_brief(MORPHEUS_CONTRACT, prepared.run_dir)

        self.assertEqual(state["status"], "repair_needed")
        self.assertEqual(state["repair_guard"]["allowed_repair_paths"], ["src/main.py"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_prepare_repairs_corrupt_task_id_from_handoff_ledger(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        ledger_path = self.project_path / ".openclaw" / "handoffs.jsonl"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            json.dumps(
                {
                    "event_type": "handoff_sent",
                    "project_id": "demo-project",
                    "from": "niaobe",
                    "to": "morpheus",
                    "phase": "IMPLEMENT",
                    "task_id": "T001",
                    "ack_required": False,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "int_not_found",
                "from": "niaobe",
                "to": "morpheus",
                "phase": "IMPLEMENT",
                "instructions": "Implement the task.",
            }
        )

        prepared = prepare_artifact_run(MORPHEUS_CONTRACT, envelope)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(state["task_id"], "T001")
        self.assertTrue(state["task_id_repaired_from_handoff"])
        self.assertEqual(prepared.run_dir.parent.name, "T001")

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_accept_task_handoff_delegates_to_architect(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "smith",
                "to": "niaobe",
                "phase": "TASK_HANDOFF",
                "instructions": "Run task T001.",
            }
        )

        state = accept_task_handoff(envelope)

        self.assertEqual(state["status"], "sent")
        self.assertIn('"to":"architect"', state["handoff_envelope"])
        self.assertIn('"phase":"DESIGN"', state["handoff_envelope"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_architect_done_delegates_exact_morpheus_envelope(
        self, run_mock: mock.Mock
    ) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "architect",
                "to": "niaobe",
                "phase": "DESIGN",
                "instructions": "DONE: management/architecture/T001.md written for T001.",
            }
        )

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "sent")
        self.assertIn('"to":"morpheus"', state["handoff_envelope"])
        self.assertIn('"phase":"IMPLEMENT"', state["handoff_envelope"])
        self.assertIn('"task_id":"T001"', state["handoff_envelope"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_morpheus_done_delegates_to_oracle(
        self, run_mock: mock.Mock
    ) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "morpheus",
                "to": "niaobe",
                "phase": "IMPLEMENT",
                "instructions": "DONE: Artifacts=README.md, src/main.py, tests/test_main.py.",
            }
        )

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "sent")
        self.assertIn('"to":"oracle"', state["handoff_envelope"])
        self.assertIn('"phase":"VERIFY"', state["handoff_envelope"])
        self.assertIn('"task_id":"T001"', state["handoff_envelope"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_runtime_failure_reports_task_blocked(self, run_mock: mock.Mock) -> None:
        def fake_run(cmd: list[str], *args: object, **kwargs: object) -> mock.Mock:
            if (
                cmd[:2] == ["bash", str(self.bin_root / "verify_artifact.sh")]
                and len(cmd) > 4
                and cmd[4] == "tests/test_main.py"
            ):
                return mock.Mock(
                    returncode=20,
                    stdout='OUTCOME_JSON: {"status":"BLOCKED","details":"required artifact missing"}\n',
                    stderr="",
                )
            return self._fake_run(cmd, *args, **kwargs)

        run_mock.side_effect = fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "morpheus",
                "to": "niaobe",
                "phase": "IMPLEMENT",
                "instructions": "DONE: Artifacts=README.md, src/main.py.",
            }
        )

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["result_payload"]["status"], "blocked")
        self.assertEqual(state["result_payload"]["code"], "helper_failed")
        sent_calls = [
            call
            for call in run_mock.call_args_list
            if call.args and call.args[0][:4] == ["openclaw", "gateway", "call", "sessions.send"]
        ]
        self.assertTrue(any("TASK_BLOCKED" in " ".join(call.args[0]) for call in sent_calls))

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_oracle_pass_marks_done_and_notifies_smith(
        self, run_mock: mock.Mock
    ) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "oracle",
                "to": "niaobe",
                "phase": "VERIFY",
                "instructions": "PASS: task verification complete.",
            }
        )

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "done")
        self.assertEqual(state["result_payload"]["status"], "done")
        write_state_calls = [
            call
            for call in run_mock.call_args_list
            if call.args and call.args[0][:2] == ["bash", str(self.bin_root / "write_state.sh")]
        ]
        self.assertTrue(any("DONE" in call.args[0] for call in write_state_calls))

    @mock.patch("worker_runtime.subprocess.run")
    def test_oracle_runtime_writes_report_and_notifies_niaobe(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "oracle",
                "phase": "VERIFY",
                "instructions": "Verify task T001.",
            }
        )

        state = verify_task(envelope)

        self.assertEqual(state["status"], "sent")
        self.assertEqual(state["runtime_engine"], "langgraph")
        self.assertEqual(state["verdict"], "PASS")
        self.assertEqual(state["report"], "management/validation/T001_REPORT.md")
        self.assertEqual(state["result_payload"]["engine"], "langgraph")
        write_calls = [
            call
            for call in run_mock.call_args_list
            if call.args and call.args[0][:2] == ["bash", str(self.bin_root / "project_write.sh")]
        ]
        self.assertTrue(any("management/validation/T001_REPORT.md" in call.args[0] for call in write_calls))
        sent_calls = [
            call
            for call in run_mock.call_args_list
            if call.args and call.args[0][:4] == ["openclaw", "gateway", "call", "sessions.send"]
        ]
        self.assertTrue(any("PASS:" in " ".join(call.args[0]) for call in sent_calls))

    @mock.patch("worker_runtime.subprocess.run")
    def test_smith_planning_prepare_creates_context_and_manifest_file(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "from": "neo",
                "to": "smith",
                "phase": "HANDOFF",
                "instructions": "Create the full plan.",
            }
        )
        prepared = prepare_planning_run(SMITH_PLANNING_CONTRACT, envelope)
        self.assertTrue(prepared.run_dir.exists())
        self.assertTrue(prepared.context_file.exists())
        self.assertTrue(prepared.handoff_file.exists())
        self.assertTrue(prepared.manifest_file.parent.exists())
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertTrue(state["inbound_receipt_acknowledged"])
        handoff = json.loads(prepared.handoff_file.read_text(encoding="utf-8"))
        self.assertEqual(handoff["manifest_schema"]["active_task"], "T001")

    @mock.patch("worker_runtime.subprocess.run")
    def test_smith_planning_complete_imports_verifies_handoffs_and_sends(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "from": "neo",
                "to": "smith",
                "phase": "HANDOFF",
                "instructions": "Create the full plan.",
            }
        )
        prepared = prepare_planning_run(SMITH_PLANNING_CONTRACT, envelope)
        drafts = {
            "management/PLAN.md": "# Plan\n\n## Overview\nPlan text.\n\n## Phases\n1. T001\n2. T002\n",
            "management/BACKLOG.md": "# Backlog\n\n- T001 READY\n- T002 PENDING\n",
            "management/tasks/T001.md": "# Task T001\n\nT001 details.\n",
            "management/tasks/T002.md": "# Task T002\n\nT002 details.\n",
            "CURRENT_TASK.md": "# Current Task\n\nT001 is active.\n",
        }
        for relative_path, content in drafts.items():
            draft = prepared.draft_dir / relative_path
            draft.parent.mkdir(parents=True, exist_ok=True)
            draft.write_text(content, encoding="utf-8")
        prepared.manifest_file.write_text(
            json.dumps(
                {
                    "artifacts": [{"path": path} for path in drafts],
                    "active_task": "T001",
                }
            ),
            encoding="utf-8",
        )

        state = complete_planning_run(SMITH_PLANNING_CONTRACT, prepared.run_dir)

        self.assertEqual(state["status"], "sent")
        self.assertEqual(state["active_task"], "T001")
        self.assertEqual(state["task_ids"], ["T001", "T002"])
        result = json.loads((prepared.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["active_task"], "T001")
        self.assertIn('"to":"niaobe"', result["handoff_envelope"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_smith_autoplan_required_plan_imports_and_handoffs(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "from": "neo",
                "to": "smith",
                "phase": "HANDOFF",
                "instructions": "Create the full plan.",
            }
        )

        state = autoplan_required_planning_project(SMITH_PLANNING_CONTRACT, envelope)

        self.assertEqual(state["status"], "sent")
        self.assertEqual(state["active_task"], "T001")
        self.assertEqual(state["task_ids"], ["T001", "T002"])
        self.assertIn("management/tasks/T001.md", state["artifacts"])
        self.assertIn("management/tasks/T002.md", state["artifacts"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_smith_cli_autoplan_uses_langgraph_runtime(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "from": "neo",
                "to": "smith",
                "phase": "HANDOFF",
                "instructions": "Create the deterministic 4-task plan.",
            }
        )

        exit_code = main_for_planning_contract(SMITH_PLANNING_CONTRACT, ["autoplan", envelope])

        self.assertEqual(exit_code, 0)
        runs = sorted((self.workspace_root / "smith" / "runs" / "demo-project" / "planning").iterdir())
        self.assertTrue(runs)
        state = json.loads((runs[-1] / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "sent")
        self.assertEqual(state["runtime_engine"], "langgraph")
        self.assertEqual(state["task_ids"], ["T001", "T002"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_smith_planning_first_verification_failure_sets_repair_needed(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "from": "neo",
                "to": "smith",
                "phase": "HANDOFF",
                "instructions": "Create the full plan.",
            }
        )
        prepared = prepare_planning_run(SMITH_PLANNING_CONTRACT, envelope)
        drafts = {
            "management/PLAN.md": "# Plan\n\n## Overview\nPlan text.\n\n## Phases\n1. T001\n",
            "management/BACKLOG.md": "# Backlog\n\n- T001 READY\n",
            "management/tasks/T001.md": "# Task T001\n\nT001 details.\n",
            "CURRENT_TASK.md": "# Current Task\n\nT002 is active.\n",
        }
        for relative_path, content in drafts.items():
            draft = prepared.draft_dir / relative_path
            draft.parent.mkdir(parents=True, exist_ok=True)
            draft.write_text(content, encoding="utf-8")
        prepared.manifest_file.write_text(
            json.dumps(
                {
                    "artifacts": [{"path": path} for path in drafts],
                    "active_task": "T001",
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaises(WorkerRuntimeError):
            complete_planning_run(SMITH_PLANNING_CONTRACT, prepared.run_dir)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "repair_needed")

    @mock.patch("worker_runtime.subprocess.run")
    def test_smith_planning_second_verification_failure_blocks(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        envelope = json.dumps(
            {
                "project_id": "demo-project",
                "from": "neo",
                "to": "smith",
                "phase": "HANDOFF",
                "instructions": "Create the full plan.",
            }
        )
        prepared = prepare_planning_run(SMITH_PLANNING_CONTRACT, envelope)
        drafts = {
            "management/PLAN.md": "# Plan\n\n## Overview\nPlan text.\n\n## Phases\n1. T001\n",
            "management/BACKLOG.md": "# Backlog\n\n- T001 READY\n",
            "management/tasks/T001.md": "# Task T001\n\nT001 details.\n",
            "CURRENT_TASK.md": "# Current Task\n\nT002 is active.\n",
        }
        for relative_path, content in drafts.items():
            draft = prepared.draft_dir / relative_path
            draft.parent.mkdir(parents=True, exist_ok=True)
            draft.write_text(content, encoding="utf-8")
        prepared.manifest_file.write_text(
            json.dumps(
                {
                    "artifacts": [{"path": path} for path in drafts],
                    "active_task": "T001",
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaises(WorkerRuntimeError):
            complete_planning_run(SMITH_PLANNING_CONTRACT, prepared.run_dir)
        with self.assertRaises(WorkerRuntimeError):
            complete_planning_run(SMITH_PLANNING_CONTRACT, prepared.run_dir)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "blocked")
        result = json.loads((prepared.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["payload"]["to"], "neo")


if __name__ == "__main__":
    unittest.main()
