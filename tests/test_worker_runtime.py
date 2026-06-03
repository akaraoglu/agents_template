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
    block_artifact_run,
    complete_artifact_run,
    complete_planning_run,
    complete_run,
    dispatch_artifact_task,
    agent_task_runtime_state,
    resume_artifact_task,
    advance_artifact_task,
    handle_artifact_work_report_outcome,
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


def session_send_params(call: mock._Call) -> dict[str, object]:
    command = call.args[0]
    return json.loads(command[command.index("--params") + 1])


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
        self.openclaw_root = Path(self.temp_dir.name) / ".openclaw"
        self.project_path = Path(self.temp_dir.name) / "projects" / "demo-project"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.bin_root.mkdir(parents=True, exist_ok=True)
        self.project_path.mkdir(parents=True, exist_ok=True)
        self._seed_openclaw_agent_session("morpheus")
        self.env_patch = mock.patch.dict(
            os.environ,
            {
                "CLAWSPACE_WORKSPACE_ROOT": str(self.workspace_root),
                "CLAWSPACE_BIN_ROOT": str(self.bin_root),
                "OPENCLAW_ROOT": str(self.openclaw_root),
            },
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def _seed_openclaw_agent_session(self, agent: str) -> None:
        sessions_dir = self.openclaw_root / "agents" / agent / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        session_id = f"{agent}-main-session"
        session_file = sessions_dir / f"{session_id}.jsonl"
        session_file.write_text("", encoding="utf-8")
        payload = {
            f"agent:{agent}:main": {
                "sessionId": session_id,
                "sessionFile": str(session_file),
                "usageFamilyKey": f"agent:{agent}:main",
                "systemSent": True,
                "status": "done",
                "model": "ollama/gemma4:26b",
                "contextTokens": 262144,
            }
        }
        (sessions_dir / "sessions.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _morpheus_done_work_result(self, *, evidence_paths: list[str] | None = None) -> dict[str, object]:
        return {
            "project_id": "demo-project",
            "task_id": "T001",
            "from": "morpheus",
            "phase": "IMPLEMENT",
            "status": "DONE",
            "summary": "Implementation complete.",
            "verification": {
                "task_id": "T001",
                "agent": "morpheus",
                "timestamp": "2026-06-01T12:00:00Z",
                "performed": True,
                "command": ["python3", "-m", "unittest", "tests/test_main.py"],
                "status": "pass",
                "summary": "draft validation passed",
                "evidence_paths": evidence_paths or ["README.md", "src/main.py", "tests/test_main.py"],
            },
        }

    def _architect_done_work_result(self, *, evidence_paths: list[str] | None = None) -> dict[str, object]:
        return {
            "project_id": "demo-project",
            "task_id": "T001",
            "from": "architect",
            "phase": "DESIGN",
            "status": "DONE",
            "summary": "Architecture complete.",
            "verification": {
                "task_id": "T001",
                "agent": "architect",
                "timestamp": "2026-06-01T12:00:00Z",
                "performed": True,
                "command": ["bash", str(self.bin_root / "verify_artifact.sh"), "demo-project", "DESIGN", "management/architecture/T001.md"],
                "status": "pass",
                "summary": "Architecture artifact verified.",
                "evidence_paths": evidence_paths or ["management/architecture/T001.md"],
            },
        }

    def _oracle_done_work_result(self, *, evidence_paths: list[str] | None = None) -> dict[str, object]:
        return {
            "project_id": "demo-project",
            "task_id": "T001",
            "from": "oracle",
            "phase": "VERIFY",
            "status": "DONE",
            "summary": "Verification complete.",
            "verification": {
                "task_id": "T001",
                "agent": "oracle",
                "timestamp": "2026-06-01T12:00:00Z",
                "performed": True,
                "command": ["python3", "-m", "unittest", "tests/test_main.py"],
                "status": "pass",
                "summary": "All validation checks passed.",
                "evidence_paths": evidence_paths or ["management/validation/T001_REPORT.md"],
            },
        }

    def _workspace_contract(self, *, expected_artifacts: list[str]) -> dict[str, object]:
        return {
            "workspace_root": str(self.project_path),
            "allowed_write_paths": expected_artifacts,
            "expected_artifacts": expected_artifacts,
            "approved_runtime_evidence_roots": [],
        }

    def _artifact_manifest(self, *, expected_artifacts: list[str], evidence_paths: list[str]) -> dict[str, object]:
        return {
            "created": expected_artifacts,
            "changed": [],
            "moved": [],
            "deleted": [],
            "expected_artifacts": expected_artifacts,
            "evidence_paths": evidence_paths,
        }

    def _create_project_artifacts(self, relative_paths: list[str]) -> None:
        for relative in relative_paths:
            path = self.project_path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("ok\n", encoding="utf-8")

    def _child_run_dir(self, from_agent: str, run_id: str, task_id: str = "T001") -> Path:
        return self.workspace_root / from_agent / "runs" / "demo-project" / task_id / run_id

    def _child_signal_envelope(
        self,
        *,
        from_agent: str,
        phase: str,
        run_id: str,
        signal: str = "COMPLETE",
        reason: str | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "project_id": "demo-project",
            "task_id": "T001",
            "from": from_agent,
            "to": "niaobe",
            "phase": phase,
            "signal": signal,
            "run_id": run_id,
        }
        if reason:
            payload["reason"] = reason
        return json.dumps(payload)

    def _write_child_result_file(
        self,
        *,
        from_agent: str,
        run_id: str,
        payload: dict[str, object],
        status: str = "sent",
        reason: str | None = None,
    ) -> Path:
        run_dir = self._child_run_dir(from_agent, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        result: dict[str, object] = {
            "status": status,
            "sent_at": "2026-06-01T12:00:00Z",
            "payload": payload,
        }
        if reason:
            result["reason"] = reason
        (run_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
        return run_dir / "result.json"

    def _child_result_payload(
        self,
        *,
        from_agent: str,
        phase: str,
        instructions: str,
        work_result: dict[str, object] | None = None,
        project_workspace: dict[str, object] | None = None,
        artifact_manifest: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "project_id": "demo-project",
            "task_id": "T001",
            "from": from_agent,
            "to": "niaobe",
            "phase": phase,
            "instructions": instructions,
        }
        if work_result is not None:
            payload["work_result"] = work_result
        if project_workspace is not None:
            payload["project_workspace"] = project_workspace
        if artifact_manifest is not None:
            payload["artifact_manifest"] = artifact_manifest
        return payload

    def _fake_run(self, cmd: list[str], capture_output: bool = True, text: bool = True, timeout: int = 120, *args, **kwargs):
        del capture_output, text, timeout, args, kwargs
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
        self.assertEqual(result["payload"]["work_result"]["status"], "DONE")
        self.assertEqual(result["payload"]["work_result"]["verification"]["status"], "pass")

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
    def test_architect_complete_requests_repair_for_tool_denied_helper_call(self, run_mock: mock.Mock) -> None:
        def fake_run(cmd: list[str], *args: object, **kwargs: object) -> mock.Mock:
            if cmd[:2] == ["bash", str(self.bin_root / "project_write.sh")]:
                return mock.Mock(
                    returncode=20,
                    stdout="",
                    stderr='exec denied: allowlist miss raw_params={"command":"architect_run_task.sh complete"}',
                )
            return self._fake_run(cmd, *args, **kwargs)

        run_mock.side_effect = fake_run
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

        self.assertEqual(exit_code, 20)
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "repair_needed")
        self.assertEqual(state["runtime_engine"], "langgraph")
        self.assertEqual(state["last_error"]["code"], "tool_denied")
        self.assertEqual(state["repair_guard"]["reason"], "tool_denied")

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
        self.assertEqual(
            Path(state_after_prepare["draft_write_root"]),
            prepared.draft_dir.parent.parent.parent / "draft-aliases" / prepared.run_dir.name,
        )
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
        self.assertEqual(state["validation_evidence"]["status"], "pass")
        self.assertIsNone(state["validation_report"])
        self.assertIn("project_exec.sh", state["project_exec"])
        result = json.loads((prepared.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertTrue(result["payload"]["instructions"].startswith("DONE: Artifacts="))
        self.assertEqual(result["payload"]["work_result"]["status"], "DONE")
        self.assertEqual(result["payload"]["work_report"]["status"], "DONE")
        self.assertEqual(result["payload"]["work_result"]["verification"]["status"], "pass")
        self.assertEqual(state["last_runtime_outcome"]["outcome"], "ACCEPTED")
        self.assertEqual(state["last_runtime_outcome"]["signal"], "COMPLETE")
        self.assertEqual(state["outbound_work_report"]["status"], "DONE")
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
        self.assertIn("REPORT_ACTION=After drafts and MANIFEST_WRITE_FILE exist, run NEXT_REQUIRED with RUN_DIR.", output)
        self.assertNotIn("VALIDATION_COMMAND=", output)
        self.assertIn("ACTION_REQUIRED=", output)
        self.assertIn("BLOCK_COMMAND=", output)
        self.assertIn("NEXT_ACTIONS_BEGIN", output)
        self.assertIn("WORK_ORDER_TRUNCATED=no", output)
        self.assertNotIn("SUBTEAM_MODE=", output)
        self.assertNotIn("SPAWN_TASK_BEGIN", output)

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_dispatch_sends_task_packet_without_agent_prepare(self, run_mock: mock.Mock) -> None:
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

        state = dispatch_artifact_task(MORPHEUS_CONTRACT, envelope)

        task_packet = Path(state["task_packet_file"]).read_text(encoding="utf-8")
        self.assertIn("TASK_PACKET_BEGIN", task_packet)
        self.assertIn("RUNTIME_MODEL=AgentTaskRuntime", task_packet)
        self.assertIn("MANIFEST_SCHEMA_BEGIN", task_packet)
        self.assertIn("REPORT_COMMAND=", task_packet)
        self.assertIn("REPORT_DESTINATION=", task_packet)
        self.assertIn("WORK_REPORT_SCHEMA_BEGIN", task_packet)
        self.assertIn("TEST_COMMAND=python3 -m unittest tests/test_main.py", task_packet)
        self.assertIn("RUNTIME_VALIDATION=REPORT_COMMAND imports drafts and runs project_exec", task_packet)
        self.assertIn("PATH_INVARIANT=REPORT_COMMAND and BLOCK_COMMAND take RUN_DIR only", task_packet)
        self.assertNotIn("VALIDATION_COMMAND=", task_packet)
        self.assertNotIn("Run the validation command", task_packet)
        self.assertNotIn("validation_report", task_packet)
        self.assertNotIn("COMPLETE_COMMAND=", task_packet)
        self.assertNotIn("morpheus_run_task.sh prepare", task_packet)
        runtime_state = agent_task_runtime_state(Path(state["task_packet_file"]).parent)
        self.assertEqual(runtime_state.agent_role, "morpheus")
        self.assertEqual(runtime_state.required_outputs, ("README.md", "src/main.py", "tests/test_main.py"))
        send_calls = [
            call for call in run_mock.call_args_list if call.args and call.args[0][:4] == ["openclaw", "gateway", "call", "sessions.send"]
        ]
        self.assertEqual(len(send_calls), 1)
        send_params = session_send_params(send_calls[0])
        self.assertIn("TASK_PACKET_BEGIN", str(send_params["message"]))
        session_key = str(send_params["key"])
        self.assertTrue(session_key.startswith("agent:morpheus:run:"))
        self.assertNotEqual(session_key, "agent:morpheus:main")
        self.assertEqual(state["dispatch_session_key"], session_key)
        self.assertEqual(state["dispatch_task_scoped_session"], True)
        self.assertTrue(Path(str(state["dispatch_session_file"])).is_file())
        registry = json.loads(
            (self.openclaw_root / "agents" / "morpheus" / "sessions" / "sessions.json").read_text(encoding="utf-8")
        )
        self.assertIn(session_key, registry)
        self.assertEqual(registry[session_key]["usageFamilyKey"], "agent:morpheus:main")
        self.assertEqual(registry[session_key]["systemSent"], False)

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_dispatches_use_distinct_task_sessions(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        first_envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "morpheus",
                "phase": "IMPLEMENT",
                "instructions": "Implement the first task.",
            }
        )
        second_envelope = json.dumps(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "niaobe",
                "to": "morpheus",
                "phase": "IMPLEMENT",
                "instructions": "Implement the second task.",
            }
        )

        first_state = dispatch_artifact_task(MORPHEUS_CONTRACT, first_envelope)
        second_state = dispatch_artifact_task(MORPHEUS_CONTRACT, second_envelope)

        self.assertNotEqual(first_state["dispatch_session_key"], second_state["dispatch_session_key"])
        self.assertTrue(str(first_state["dispatch_session_key"]).startswith("agent:morpheus:run:"))
        self.assertTrue(str(second_state["dispatch_session_key"]).startswith("agent:morpheus:run:"))
        registry = json.loads(
            (self.openclaw_root / "agents" / "morpheus" / "sessions" / "sessions.json").read_text(encoding="utf-8")
        )
        self.assertIn(first_state["dispatch_session_key"], registry)
        self.assertIn(second_state["dispatch_session_key"], registry)
        self.assertIn("agent:morpheus:main", registry)

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_report_with_draft_root_fails_visibly(self, run_mock: mock.Mock) -> None:
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
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            rc = main_for_artifact_contract(
                MORPHEUS_CONTRACT,
                ["report", state["draft_write_root"]],
            )

        output = stdout.getvalue()
        self.assertEqual(rc, 20)
        self.assertIn("WORKER_RUNTIME_FAILED:", output)
        self.assertIn("RUN_DIR", output)
        self.assertIn("DRAFT_WRITE_ROOT", output)

    @mock.patch("agent_runner.complete_artifact_run_graph")
    def test_morpheus_report_command_routes_to_graph_completion(self, graph_mock: mock.Mock) -> None:
        graph_mock.return_value = {}
        run_dir = self.project_path / "runs" / "morpheus-report"
        run_dir.mkdir(parents=True, exist_ok=True)

        exit_code = main_for_artifact_contract(MORPHEUS_CONTRACT, ["report", str(run_dir)])

        self.assertEqual(exit_code, 0)
        graph_mock.assert_called_once_with(MORPHEUS_CONTRACT, run_dir)

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_resume_sends_missing_work_continuation(self, run_mock: mock.Mock) -> None:
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
        state = dispatch_artifact_task(MORPHEUS_CONTRACT, envelope)
        run_dir = Path(state["task_packet_file"]).parent
        draft_dir = Path(state["draft_dir"])
        (draft_dir / "src").mkdir(parents=True, exist_ok=True)
        (draft_dir / "src/main.py").write_text("def main():\n    return 0\n", encoding="utf-8")

        resumed = resume_artifact_task(MORPHEUS_CONTRACT, run_dir)

        continuation = Path(resumed["last_recovery_file"]).read_text(encoding="utf-8")
        self.assertIn("TASK_CONTINUATION_BEGIN", continuation)
        self.assertIn("manifest.json", continuation)
        self.assertIn("README.md", continuation)
        self.assertIn("tests/test_main.py", continuation)
        self.assertEqual(resumed["recovery_attempts"], 1)
        send_calls = [
            call for call in run_mock.call_args_list if call.args and call.args[0][:4] == ["openclaw", "gateway", "call", "sessions.send"]
        ]
        self.assertEqual(len(send_calls), 2)
        dispatch_key = str(session_send_params(send_calls[0])["key"])
        resume_key = str(session_send_params(send_calls[1])["key"])
        self.assertTrue(dispatch_key.startswith("agent:morpheus:run:"))
        self.assertEqual(resume_key, dispatch_key)
        self.assertEqual(resumed["dispatch_session_key"], dispatch_key)

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_advance_completes_when_artifacts_are_ready(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        prepared = self._prepare_morpheus_artifacts()

        state = advance_artifact_task(MORPHEUS_CONTRACT, prepared.run_dir)

        self.assertEqual(state["status"], "sent")
        self.assertEqual(state["runtime_engine"], "langgraph")
        self.assertEqual(state["validation_evidence"]["status"], "pass")
        self.assertEqual(state["last_runtime_outcome"]["outcome"], "ACCEPTED")

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_advance_marks_repair_required_when_artifacts_are_missing(self, run_mock: mock.Mock) -> None:
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
        state = dispatch_artifact_task(MORPHEUS_CONTRACT, envelope)
        run_dir = Path(state["task_packet_file"]).parent

        advanced = advance_artifact_task(MORPHEUS_CONTRACT, run_dir)

        self.assertEqual(advanced["status"], "awaiting_artifacts")
        self.assertEqual(advanced["last_runtime_outcome"]["outcome"], "REPAIR_REQUIRED")
        self.assertEqual(advanced["repair_feedback"]["code"], "missing_artifact_work")
        self.assertIn("manifest.json", advanced["repair_feedback"]["reason"])
        self.assertTrue(Path(advanced["last_recovery_file"]).is_file())

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
        self.assertIn("Read CONTEXT_FILE only if required implementation details are missing", output)
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
    def test_morpheus_block_writes_contract_blocked_work_result(self, run_mock: mock.Mock) -> None:
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

        state = block_artifact_run(
            MORPHEUS_CONTRACT,
            prepared.run_dir,
            code="capability_gap",
            reason="Required package is unavailable.",
        )

        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["last_runtime_outcome"]["outcome"], "BLOCKED")
        result = json.loads((prepared.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["payload"]["work_result"]["status"], "BLOCKED")
        self.assertEqual(result["payload"]["work_report"]["status"], "BLOCKED")
        self.assertEqual(result["signal"]["signal"], "BLOCKED")

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_outcome_handler_records_needs_review(self, run_mock: mock.Mock) -> None:
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
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))

        outcome = handle_artifact_work_report_outcome(
            MORPHEUS_CONTRACT,
            prepared.run_dir,
            state,
            {
                "task_id": "T001",
                "agent": "morpheus",
                "status": "NEEDS_REVIEW",
                "summary": "Need review before writing implementation artifacts.",
                "changed_files": [],
                "verification": None,
                "repair_attempts": [],
                "next_owner": "niaobe",
                "blocker": {
                    "reason": "Task scope conflicts with architecture constraints.",
                },
                "artifact_manifest": None,
            },
        )

        self.assertEqual(outcome.outcome, "NEEDS_REVIEW")
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "needs_review")
        self.assertEqual(state["last_runtime_outcome"]["outcome"], "NEEDS_REVIEW")
        result = json.loads((prepared.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["work_report"]["status"], "NEEDS_REVIEW")

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_exhausted_repair_budget_blocks_with_work_result(self, run_mock: mock.Mock) -> None:
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
        state_path = prepared.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["completion_attempts"] = 5
        state_path.write_text(json.dumps(state), encoding="utf-8")

        with self.assertRaises(WorkerRuntimeError):
            complete_artifact_run(MORPHEUS_CONTRACT, prepared.run_dir)

        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["last_runtime_outcome"]["outcome"], "BLOCKED")
        result = json.loads((prepared.run_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["payload"]["work_result"]["status"], "BLOCKED")
        self.assertEqual(result["signal"]["signal"], "BLOCKED")

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
        self.assertEqual(state["last_runtime_outcome"]["outcome"], "REPAIR_REQUIRED")
        self.assertEqual(state["repair_feedback"]["code"], "missing_draft")
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
        run_id = "20260601T120000Z-arch01"
        payload = self._child_result_payload(
            from_agent="architect",
            phase="DESIGN",
            instructions="DONE: management/architecture/T001.md written for T001.",
            work_result=self._architect_done_work_result(),
            project_workspace=self._workspace_contract(expected_artifacts=["management/architecture/T001.md"]),
            artifact_manifest=self._artifact_manifest(
                expected_artifacts=["management/architecture/T001.md"],
                evidence_paths=["management/architecture/T001.md"],
            ),
        )
        self._write_child_result_file(from_agent="architect", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="architect", phase="DESIGN", run_id=run_id)
        self._create_project_artifacts(["management/architecture/T001.md"])

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "sent")
        self.assertIn('"to":"morpheus"', state["handoff_envelope"])
        self.assertIn('"phase":"IMPLEMENT"', state["handoff_envelope"])
        self.assertIn('"task_id":"T001"', state["handoff_envelope"])
        self.assertEqual(state["result_payload"]["accepted_work_result"]["status"], "DONE")

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_morpheus_done_delegates_to_oracle(
        self, run_mock: mock.Mock
    ) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120001Z-morpheus01"
        payload = self._child_result_payload(
            from_agent="morpheus",
            phase="IMPLEMENT",
            instructions="DONE: Artifacts=README.md, src/main.py, tests/test_main.py.",
            work_result=self._morpheus_done_work_result(),
            project_workspace=self._workspace_contract(expected_artifacts=["README.md", "src/main.py", "tests/test_main.py"]),
            artifact_manifest=self._artifact_manifest(
                expected_artifacts=["README.md", "src/main.py", "tests/test_main.py"],
                evidence_paths=["README.md", "src/main.py", "tests/test_main.py"],
            ),
        )
        self._write_child_result_file(from_agent="morpheus", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="morpheus", phase="IMPLEMENT", run_id=run_id)
        self._create_project_artifacts(["README.md", "src/main.py", "tests/test_main.py"])

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "sent")
        self.assertIn('"to":"oracle"', state["handoff_envelope"])
        self.assertIn('"phase":"VERIFY"', state["handoff_envelope"])
        self.assertIn('"task_id":"T001"', state["handoff_envelope"])
        self.assertEqual(state["result_payload"]["accepted_work_result"]["status"], "DONE")

    @mock.patch("worker_runtime.subprocess.run")
    def test_tiny_markdown_counter_done_in_workspace_is_accepted(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120002Z-tiny01"
        payload = self._child_result_payload(
            from_agent="morpheus",
            phase="IMPLEMENT",
            instructions="DONE: Artifacts=README.md, src/main.py, tests/test_main.py.",
            work_result=self._morpheus_done_work_result(),
            project_workspace=self._workspace_contract(expected_artifacts=["README.md", "src/main.py", "tests/test_main.py"]),
            artifact_manifest=self._artifact_manifest(
                expected_artifacts=["README.md", "src/main.py", "tests/test_main.py"],
                evidence_paths=["README.md", "src/main.py", "tests/test_main.py"],
            ),
        )
        self._write_child_result_file(from_agent="morpheus", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="morpheus", phase="IMPLEMENT", run_id=run_id)
        self._create_project_artifacts(["README.md", "src/main.py", "tests/test_main.py"])

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "sent")
        self.assertIn('"to":"oracle"', state["handoff_envelope"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_architect_done_without_work_result_requests_repair(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120003Z-arch02"
        payload = self._child_result_payload(
            from_agent="architect",
            phase="DESIGN",
            instructions="DONE: management/architecture/T001.md written for T001.",
        )
        self._write_child_result_file(from_agent="architect", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="architect", phase="DESIGN", run_id=run_id)
        self._create_project_artifacts(["management/validation/T001_REPORT.md"])

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "repair_requested")
        self.assertEqual(state["result_payload"]["code"], "work_result_invalid")
        self.assertIn("REPAIR_REQUIRED[work_result_invalid]", state["result_payload"]["repair_feedback"])
        self.assertIn('"work_result": {', state["result_payload"]["repair_feedback"])
        write_state_calls = [
            call
            for call in run_mock.call_args_list
            if call.args and call.args[0][:2] == ["bash", str(self.bin_root / "write_state.sh")]
        ]
        self.assertEqual(write_state_calls, [])
        handoff_calls = [
            call
            for call in run_mock.call_args_list
            if call.args and call.args[0][:2] == ["bash", str(self.bin_root / "handoff.sh")]
        ]
        self.assertFalse(any(len(call.args[0]) > 3 and call.args[0][3] == "morpheus" for call in handoff_calls))

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_architect_done_non_object_work_result_requests_repair(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120004Z-arch03"
        payload = self._child_result_payload(
            from_agent="architect",
            phase="DESIGN",
            instructions="DONE: management/architecture/T001.md written for T001.",
            work_result="invalid",
            project_workspace=self._workspace_contract(expected_artifacts=["management/architecture/T001.md"]),
            artifact_manifest=self._artifact_manifest(
                expected_artifacts=["management/architecture/T001.md"],
                evidence_paths=["management/architecture/T001.md"],
            ),
        )
        self._write_child_result_file(from_agent="architect", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="architect", phase="DESIGN", run_id=run_id)
        self._create_project_artifacts(["management/architecture/T001.md"])

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "repair_requested")
        self.assertEqual(state["result_payload"]["code"], "work_result_invalid")
        self.assertIn("work_result must be a JSON object", state["result_payload"]["reason"])
        self.assertIn('"work_result": {', state["result_payload"]["repair_feedback"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_morpheus_done_without_work_result_requests_repair(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120005Z-morpheus02"
        payload = self._child_result_payload(
            from_agent="morpheus",
            phase="IMPLEMENT",
            instructions="DONE: Artifacts=README.md, src/main.py, tests/test_main.py.",
        )
        self._write_child_result_file(from_agent="morpheus", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="morpheus", phase="IMPLEMENT", run_id=run_id)
        self._create_project_artifacts(["management/validation/T001_REPORT.md"])

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "repair_requested")
        self.assertEqual(state["result_payload"]["code"], "work_result_invalid")
        self.assertIn("REPAIR_REQUIRED[work_result_invalid]", state["result_payload"]["repair_feedback"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_morpheus_done_without_artifact_manifest_requests_repair(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120006Z-morpheus03"
        payload = self._child_result_payload(
            from_agent="morpheus",
            phase="IMPLEMENT",
            instructions="DONE: Artifacts=README.md, src/main.py, tests/test_main.py.",
            work_result=self._morpheus_done_work_result(),
            project_workspace=self._workspace_contract(expected_artifacts=["README.md", "src/main.py", "tests/test_main.py"]),
        )
        self._write_child_result_file(from_agent="morpheus", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="morpheus", phase="IMPLEMENT", run_id=run_id)

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "repair_requested")
        self.assertEqual(state["result_payload"]["code"], "work_result_invalid")
        self.assertIn("DONE requires artifact_manifest", state["result_payload"]["reason"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_morpheus_done_with_empty_artifact_manifest_requests_repair(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120007Z-morpheus04"
        payload = self._child_result_payload(
            from_agent="morpheus",
            phase="IMPLEMENT",
            instructions="DONE: Artifacts=README.md, src/main.py, tests/test_main.py.",
            work_result=self._morpheus_done_work_result(),
            project_workspace=self._workspace_contract(expected_artifacts=["README.md", "src/main.py", "tests/test_main.py"]),
            artifact_manifest={
                "created": [],
                "changed": [],
                "moved": [],
                "deleted": [],
                "expected_artifacts": ["README.md", "src/main.py", "tests/test_main.py"],
                "evidence_paths": ["README.md", "src/main.py", "tests/test_main.py"],
            },
        )
        self._write_child_result_file(from_agent="morpheus", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="morpheus", phase="IMPLEMENT", run_id=run_id)
        self._create_project_artifacts(["README.md", "src/main.py", "tests/test_main.py"])

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "repair_requested")
        self.assertEqual(state["result_payload"]["code"], "work_result_invalid")

    @mock.patch("worker_runtime.subprocess.run")
    def test_morpheus_required_artifacts_are_data_driven_from_workspace_contract(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        artifact = "docs/output.md"
        run_id = "20260601T120008Z-morpheus05"
        payload = self._child_result_payload(
            from_agent="morpheus",
            phase="IMPLEMENT",
            instructions=f"DONE: Artifacts={artifact}.",
            work_result=self._morpheus_done_work_result(evidence_paths=[artifact]),
            project_workspace=self._workspace_contract(expected_artifacts=[artifact]),
            artifact_manifest=self._artifact_manifest(
                expected_artifacts=[artifact],
                evidence_paths=[artifact],
            ),
        )
        self._write_child_result_file(from_agent="morpheus", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="morpheus", phase="IMPLEMENT", run_id=run_id)
        self._create_project_artifacts([artifact])

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "sent")
        verify_calls = [
            call
            for call in run_mock.call_args_list
            if call.args and call.args[0][:2] == ["bash", str(self.bin_root / "verify_artifact.sh")]
        ]
        verify_commands = [" ".join(call.args[0]) for call in verify_calls]
        self.assertTrue(any(f" {artifact} " in f" {cmd} " for cmd in verify_commands))
        self.assertFalse(any(" README.md " in f" {cmd} " for cmd in verify_commands))

    @mock.patch("worker_runtime.subprocess.run")
    def test_tiny_markdown_counter_done_wrong_workspace_location_requests_repair(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        wrong_workspace = str(self.project_path.parent / "wrong-location")
        run_id = "20260601T120009Z-morpheus06"
        payload = self._child_result_payload(
            from_agent="morpheus",
            phase="IMPLEMENT",
            instructions="DONE: Artifacts=README.md, src/main.py, tests/test_main.py.",
            work_result=self._morpheus_done_work_result(),
            project_workspace={
                "workspace_root": wrong_workspace,
                "allowed_write_paths": ["README.md", "src/main.py", "tests/test_main.py"],
                "expected_artifacts": ["README.md", "src/main.py", "tests/test_main.py"],
                "approved_runtime_evidence_roots": [],
            },
            artifact_manifest=self._artifact_manifest(
                expected_artifacts=["README.md", "src/main.py", "tests/test_main.py"],
                evidence_paths=["README.md", "src/main.py", "tests/test_main.py"],
            ),
        )
        self._write_child_result_file(from_agent="morpheus", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="morpheus", phase="IMPLEMENT", run_id=run_id)
        self._create_project_artifacts(["management/validation/T001_REPORT.md"])

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "repair_requested")
        self.assertEqual(state["result_payload"]["code"], "work_result_invalid")
        self.assertIn("workspace_root", state["result_payload"]["reason"])

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
        run_id = "20260601T120010Z-morpheus07"
        payload = self._child_result_payload(
            from_agent="morpheus",
            phase="IMPLEMENT",
            instructions="DONE: Artifacts=README.md, src/main.py.",
            work_result=self._morpheus_done_work_result(evidence_paths=["README.md", "src/main.py", "tests/test_main.py"]),
            project_workspace=self._workspace_contract(expected_artifacts=["README.md", "src/main.py", "tests/test_main.py"]),
            artifact_manifest=self._artifact_manifest(
                expected_artifacts=["README.md", "src/main.py", "tests/test_main.py"],
                evidence_paths=["README.md", "src/main.py", "tests/test_main.py"],
            ),
        )
        self._write_child_result_file(from_agent="morpheus", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="morpheus", phase="IMPLEMENT", run_id=run_id)
        self._create_project_artifacts(["README.md", "src/main.py", "tests/test_main.py"])

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
        run_id = "20260601T120011Z-oracle01"
        payload = self._child_result_payload(
            from_agent="oracle",
            phase="VERIFY",
            instructions="PASS: task verification complete.",
            work_result=self._oracle_done_work_result(),
            project_workspace=self._workspace_contract(expected_artifacts=["management/validation/T001_REPORT.md"]),
            artifact_manifest=self._artifact_manifest(
                expected_artifacts=["management/validation/T001_REPORT.md"],
                evidence_paths=["management/validation/T001_REPORT.md"],
            ),
        )
        self._write_child_result_file(from_agent="oracle", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="oracle", phase="VERIFY", run_id=run_id)
        self._create_project_artifacts(["management/validation/T001_REPORT.md"])

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "done")
        self.assertEqual(state["result_payload"]["status"], "done")
        self.assertEqual(state["result_payload"]["accepted_work_result"]["status"], "DONE")
        write_state_calls = [
            call
            for call in run_mock.call_args_list
            if call.args and call.args[0][:2] == ["bash", str(self.bin_root / "write_state.sh")]
        ]
        self.assertTrue(any("DONE" in call.args[0] for call in write_state_calls))

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_oracle_pass_without_work_result_requests_repair(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120012Z-oracle02"
        payload = self._child_result_payload(
            from_agent="oracle",
            phase="VERIFY",
            instructions="PASS: task verification complete.",
        )
        self._write_child_result_file(from_agent="oracle", run_id=run_id, payload=payload)
        envelope = self._child_signal_envelope(from_agent="oracle", phase="VERIFY", run_id=run_id)

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "repair_requested")
        self.assertEqual(state["result_payload"]["code"], "work_result_invalid")

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_signal_without_result_file_requests_repair(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120013Z-morpheus08"
        envelope = self._child_signal_envelope(from_agent="morpheus", phase="IMPLEMENT", run_id=run_id)

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "repair_requested")
        self.assertEqual(state["result_payload"]["code"], "missing_result_json")
        self.assertIn("result.json", state["result_payload"]["reason"])
        self.assertIn("REPAIR_REQUIRED[child_result_invalid]", state["result_payload"]["repair_feedback"])
        self.assertIn("Required result.json shape", state["result_payload"]["repair_feedback"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_signal_with_invalid_result_json_requests_repair(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120014Z-morpheus09"
        run_dir = self._child_run_dir("morpheus", run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text("{bad json", encoding="utf-8")
        envelope = self._child_signal_envelope(from_agent="morpheus", phase="IMPLEMENT", run_id=run_id)

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "repair_requested")
        self.assertEqual(state["result_payload"]["code"], "result_json_invalid")
        self.assertIn("invalid JSON", state["result_payload"]["reason"])
        self.assertIn("REPAIR_REQUIRED[child_result_invalid]", state["result_payload"]["repair_feedback"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_signal_with_non_object_result_json_requests_repair(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120015Z-morpheus10"
        run_dir = self._child_run_dir("morpheus", run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(json.dumps(["not", "object"]), encoding="utf-8")
        envelope = self._child_signal_envelope(from_agent="morpheus", phase="IMPLEMENT", run_id=run_id)

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "repair_requested")
        self.assertEqual(state["result_payload"]["code"], "result_json_invalid")
        self.assertIn("must contain a JSON object", state["result_payload"]["reason"])

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_blocked_uses_result_json_not_signal_prose(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120016Z-morpheus11"
        payload = self._child_result_payload(
            from_agent="morpheus",
            phase="IMPLEMENT",
            instructions="Result payload summary should not override work_result blocker.",
            work_result={
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "morpheus",
                "phase": "IMPLEMENT",
                "status": "BLOCKED",
                "summary": "Implementation blocked.",
                "reason": "Required package is unavailable in allowed tools.",
                "next_action": "Smith should re-scope the task or approve the dependency.",
            },
        )
        self._write_child_result_file(from_agent="morpheus", run_id=run_id, payload=payload, status="blocked")
        envelope = self._child_signal_envelope(
            from_agent="morpheus",
            phase="IMPLEMENT",
            run_id=run_id,
            signal="BLOCKED",
            reason="Envelope prose should be ignored.",
        )

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["result_payload"]["reason"], "Required package is unavailable in allowed tools.")
        self.assertEqual(
            state["result_payload"]["next_action"],
            "Smith should re-scope the task or approve the dependency.",
        )
        self.assertEqual(state["result_payload"]["accepted_work_result"]["status"], "BLOCKED")
        sent_calls = [
            call
            for call in run_mock.call_args_list
            if call.args and call.args[0][:4] == ["openclaw", "gateway", "call", "sessions.send"]
        ]
        sent_joined = "\n".join(" ".join(call.args[0]) for call in sent_calls)
        self.assertIn("Required package is unavailable", sent_joined)
        self.assertNotIn("Envelope prose should be ignored", sent_joined)

    @mock.patch("worker_runtime.subprocess.run")
    def test_niaobe_child_blocked_without_work_result_requests_repair(self, run_mock: mock.Mock) -> None:
        run_mock.side_effect = self._fake_run
        run_id = "20260601T120017Z-morpheus12"
        payload = self._child_result_payload(
            from_agent="morpheus",
            phase="IMPLEMENT",
            instructions="BLOCKED: Missing dependency.",
        )
        self._write_child_result_file(from_agent="morpheus", run_id=run_id, payload=payload, status="blocked")
        envelope = self._child_signal_envelope(
            from_agent="morpheus",
            phase="IMPLEMENT",
            run_id=run_id,
            signal="BLOCKED",
        )

        state = continue_child_result(envelope)

        self.assertEqual(state["status"], "repair_requested")
        self.assertEqual(state["result_payload"]["code"], "work_result_invalid")
        self.assertIn("work_result", state["result_payload"]["repair_feedback"])

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
        sent_joined = [" ".join(call.args[0]) for call in sent_calls]
        self.assertTrue(any("signal" in command and "COMPLETE" in command for command in sent_joined))
        self.assertTrue(any("run_id" in command for command in sent_joined))

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
        self.assertEqual(state["status"], "awaiting_artifacts")
        self.assertIn("management/PLAN.md", state["required_artifact_paths"])
        self.assertIn("management/tasks/T001.md", state["required_artifact_paths"])
        self.assertIn("smith_plan_project.sh complete", state["next_required"])
        self.assertIn("smith_plan_project.sh block", state["block_command"])
        self.assertIn("Do not stop after prepare", state["action_required"])
        self.assertTrue(state["next_actions"])
        handoff = json.loads(prepared.handoff_file.read_text(encoding="utf-8"))
        self.assertEqual(handoff["manifest_schema"]["active_task"], "T001")
        self.assertIn("required_artifact_paths", handoff)
        self.assertIn("block_command", handoff)
        self.assertIn("next_actions", handoff)

    @mock.patch("worker_runtime.subprocess.run")
    def test_smith_planning_prepare_prints_explicit_action_contract(self, run_mock: mock.Mock) -> None:
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

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            prepare_planning_run(SMITH_PLANNING_CONTRACT, envelope)

        output = stdout.getvalue()
        self.assertIn("DRAFT_WRITE_ROOT=", output)
        self.assertIn("MANIFEST_WRITE_FILE=", output)
        self.assertIn("REQUIRED_ARTIFACT_PATHS=", output)
        self.assertIn("MANIFEST_SCHEMA_BEGIN", output)
        self.assertIn("BLOCK_COMMAND=", output)
        self.assertIn("NEXT_REQUIRED=", output)
        self.assertIn("ACTION_REQUIRED=Do not stop after prepare.", output)
        self.assertIn("NEXT_ACTIONS_BEGIN", output)
        self.assertIn("1. Read WORK_ORDER and CONTEXT_FILE; do not stop after reading.", output)
        self.assertIn("NEXT_ACTIONS_END", output)

    @mock.patch("worker_runtime.subprocess.run")
    def test_smith_planning_prepare_keeps_missing_drafts_actionable(self, run_mock: mock.Mock) -> None:
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
        state = json.loads((prepared.run_dir / "state.json").read_text(encoding="utf-8"))

        self.assertEqual(state["status"], "awaiting_artifacts")
        self.assertFalse(state["project_state_written"])
        self.assertIn("smith_plan_project.sh complete", state["next_required"])
        self.assertIn("smith_plan_project.sh block", state["block_command"])
        self.assertIn("Do not stop after prepare", state["action_required"])
        self.assertFalse((prepared.run_dir / "result.json").exists())

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
