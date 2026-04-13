from __future__ import annotations

import json
import os
import stat
import sys
import unittest
from pathlib import Path

import yaml

from openclaw_agents.runtime.dispatcher import RuntimeDispatcher
from openclaw_agents.runtime.openclaw_workspace_executor import OpenClawWorkspaceExecutor
from openclaw_agents.runtime.worker_runner import RuntimeWorker

from tests.helpers import ControlPlaneHarness, queue_task, seed_project


class OpenClawWorkspaceExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = ControlPlaneHarness()

    def tearDown(self) -> None:
        self.harness.cleanup()

    def _write_fake_openclaw(self) -> Path:
        script = self.harness.tmp_path / "fake_openclaw.py"
        state_path = self.harness.tmp_path / "fake_openclaw_state.json"
        state_path.write_text(json.dumps({"agents": {}}))
        script.write_text(
            """
import json
import sys
from pathlib import Path

state_path = Path(__file__).with_name("fake_openclaw_state.json")
state = json.loads(state_path.read_text())
args = sys.argv[1:]

def save() -> None:
    state_path.write_text(json.dumps(state, sort_keys=True))

if args[:3] == ["agents", "list", "--json"]:
    print(json.dumps(list(state["agents"].values())))
    raise SystemExit(0)

if len(args) >= 8 and args[0] == "agents" and args[1] == "add":
    agent_id = args[2]
    workspace = args[args.index("--workspace") + 1]
    model = args[args.index("--model") + 1]
    record = {
        "id": agent_id,
        "workspace": workspace,
        "agentDir": f"/tmp/{agent_id}/agent",
        "model": model,
        "bindings": 0,
    }
    state["agents"][agent_id] = record
    save()
    print(json.dumps(record))
    raise SystemExit(0)

if args and args[0] == "agent":
    agent_id = args[args.index("--agent") + 1]
    session_id = args[args.index("--session-id") + 1]
    message = args[args.index("--message") + 1]
    agent = state["agents"][agent_id]
    workspace = Path(agent["workspace"])
    if agent_id.endswith("implementer-" + agent_id.split("-")[-1]):
        target = workspace / "src" / "implemented.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("print('implemented')\\n")
        visible = {
            "status": "SUCCESS",
            "summary": "Implemented the requested workspace change.",
            "findings": ["updated src/implemented.py"],
            "build_notes": "No build step required in fake backend.",
            "known_limitations": [],
            "handoff_notes_for_tester": ["run the smoke test"],
        }
    else:
        target = workspace / "tests" / "test_runtime.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_runtime():\\n    assert True\\n")
        visible = {
            "status": "SUCCESS",
            "summary": "Executed the requested validation.",
            "findings": ["smoke test passed"],
            "commands_run": ["python3 -m unittest -q"],
            "result": "FAIL" if "force_fail" in message else "PASS",
            "failures": ["detected implementation defect"] if "force_fail" in message else [],
            "failure_cause": "IMPLEMENTATION_DEFECT" if "force_fail" in message else "PASS",
            "coverage_notes": ["fake backend validation"],
        }
    payload = {
        "runId": "run-backend",
        "status": "ok",
        "summary": "completed",
        "result": {
            "payloads": [{"text": json.dumps(visible), "mediaUrl": None}],
            "meta": {
                "agentMeta": {
                    "sessionId": session_id,
                    "provider": "ollama",
                    "model": agent["model"],
                }
            },
        },
    }
    print(json.dumps(payload))
    raise SystemExit(0)

raise SystemExit(f"unsupported args: {args}")
""".strip()
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        wrapper = self.harness.tmp_path / "openclaw"
        wrapper.write_text(f"#!/usr/bin/env bash\nexec {sys.executable} {script} \"$@\"\n")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
        return wrapper

    def _write_harvest_openclaw(self) -> Path:
        script = self.harness.tmp_path / "harvest_openclaw.py"
        state_path = self.harness.tmp_path / "harvest_openclaw_state.json"
        state_path.write_text(json.dumps({"agents": {}}))
        script.write_text(
            """
import json
import sys
import time
from pathlib import Path

state_path = Path(__file__).with_name("harvest_openclaw_state.json")
state = json.loads(state_path.read_text())
args = sys.argv[1:]

def save() -> None:
    state_path.write_text(json.dumps(state, sort_keys=True))

if args[:3] == ["agents", "list", "--json"]:
    print(json.dumps(list(state["agents"].values())))
    raise SystemExit(0)

if len(args) >= 8 and args[0] == "agents" and args[1] == "add":
    agent_id = args[2]
    workspace = args[args.index("--workspace") + 1]
    model = args[args.index("--model") + 1]
    agent_root = Path(__file__).with_name("harvest_agents") / agent_id
    record = {
        "id": agent_id,
        "workspace": workspace,
        "agentDir": str(agent_root / "agent"),
        "model": model,
        "bindings": 0,
    }
    (agent_root / "agent").mkdir(parents=True, exist_ok=True)
    state["agents"][agent_id] = record
    save()
    print(json.dumps(record))
    raise SystemExit(0)

if args and args[0] == "agent":
    agent_id = args[args.index("--agent") + 1]
    workspace = Path(state["agents"][agent_id]["workspace"])
    sessions_dir = Path(state["agents"][agent_id]["agentDir"]).parent / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    target = workspace / "src" / "harvested.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("print('harvested')\\n")
    visible = {
        "status": "SUCCESS",
        "summary": "Recovered result from session state.",
        "findings": ["updated src/harvested.py"],
        "build_notes": "harvested path",
        "known_limitations": [],
        "handoff_notes_for_tester": ["verify the harvested file"],
    }
    session_file = sessions_dir / "session-harvested.jsonl"
    session_file.write_text(
        "\\n".join(
            [
                json.dumps({"type": "session", "id": "session-harvested"}),
                json.dumps({"type": "model_change", "provider": "ollama", "modelId": "gemma4:31b"}),
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "text", "text": json.dumps(visible)}],
                        },
                    }
                ),
            ]
        )
        + "\\n"
    )
    (sessions_dir / "sessions.json").write_text(
        json.dumps(
            {
                f"agent:{agent_id}:main": {
                    "sessionId": "session-harvested",
                    "updatedAt": 1,
                    "provider": "ollama",
                    "model": "gemma4:31b",
                    "sessionFile": str(session_file),
                    "status": "done",
                }
            },
            sort_keys=True,
        )
    )
    time.sleep(2.0)
    raise SystemExit(0)

raise SystemExit(f"unsupported args: {args}")
""".strip()
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        wrapper = self.harness.tmp_path / "harvest_openclaw"
        wrapper.write_text(f"#!/usr/bin/env bash\nexec {sys.executable} {script} \"$@\"\n")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
        return wrapper

    def _seed_workspace_project(self, project_id: str, *, to_agent: str, task_type: str, goal: str, context: dict[str, object], expected_output: dict[str, object]) -> tuple[Path, dict[str, object]]:
        store = self.harness.store
        workspace_ref = self.harness.tmp_path / project_id
        workspace_ref.mkdir(parents=True, exist_ok=True)
        seed_project(
            store,
            project_id=project_id,
            goal=goal,
            current_phase="software_implementation",
            current_owner_agent="morpheus",
            next_action={"type": task_type, "target_agent": to_agent},
            workspace_ref=str(workspace_ref),
        )
        store.upsert(
            "workspace_states",
            {
                "workspace_ref": str(workspace_ref),
                "project_id": project_id,
                "repo_root": str(workspace_ref),
                "branch_or_worktree_id": "main",
                "last_clean_commit_or_checkpoint": "checkpoint-1",
                "is_consistent": True,
            },
            conflict_columns=["workspace_ref"],
        )
        task = store.record_task(
            project_id=project_id,
            from_agent="morpheus",
            to_agent=to_agent,
            task_type=task_type,
            title=f"{task_type} for {project_id}",
            goal=goal,
            priority="MEDIUM",
            context=context,
            expected_output=expected_output,
            return_to="requesting_agent",
        )
        return workspace_ref, task

    def test_implementer_executor_provisions_backend_agent_and_tracks_changed_files(self) -> None:
        fake_openclaw = self._write_fake_openclaw()
        workspace_ref, task = self._seed_workspace_project(
            "P_impl_backend",
            to_agent="implementer",
            task_type="IMPLEMENT_SOFTWARE_TASK",
            goal="Implement the requested feature",
            context={"plan_summary": {"implementation_steps": ["edit src/implemented.py"]}},
            expected_output={"artifact_type": "code_change"},
        )
        dispatcher = RuntimeDispatcher(self.harness.store, state_dir=self.harness.state_dir)
        queue_task(dispatcher, task)
        run = self.harness.store.list_pending_runtime_runs(agent_id="implementer")[0]
        packet = yaml.safe_load(Path(run["log_ref"]).read_text())
        response_path = self.harness.tmp_path / "implementer_response.yaml"
        log_path = self.harness.tmp_path / "implementer_response.log"

        executor = OpenClawWorkspaceExecutor(self.harness.store, openclaw_bin=str(fake_openclaw))
        response = executor.execute(
            packet=packet,
            response_path=response_path,
            log_path=log_path,
            timeout_seconds=60,
        )

        self.assertEqual(response["status"], "SUCCESS")
        artifact = response["artifacts_out"][0]
        self.assertEqual(artifact["artifact_type"], "code_change")
        self.assertIn("src/implemented.py", artifact["payload"]["changed_files"])
        self.assertTrue((workspace_ref / "src" / "implemented.py").exists())
        self.assertTrue(log_path.with_suffix(".agents.log").exists())

    def test_worker_openclaw_workspace_executor_records_tester_failure_report(self) -> None:
        fake_openclaw = self._write_fake_openclaw()
        _workspace_ref, task = self._seed_workspace_project(
            "P_test_backend",
            to_agent="tester",
            task_type="TEST_SOFTWARE_TASK",
            goal="Validate the implementation",
            context={"latest_test_report": "force_fail"},
            expected_output={"artifact_type": "test_execution_report"},
        )
        dispatcher = RuntimeDispatcher(self.harness.store, state_dir=self.harness.state_dir)
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
                    },
                    "agents": {
                        "tester": {
                            "executor": "openclaw_workspace",
                            "openclaw_bin": str(fake_openclaw),
                        }
                    },
                },
                sort_keys=False,
            )
        )
        worker = RuntimeWorker(
            self.harness.store,
            worker_config_path=worker_config_path,
            state_dir=self.harness.state_dir,
        )

        result = worker.process_once(agent_id="tester")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "SUCCESS")
        payload = yaml.safe_load(Path(result.response_file).read_text())
        artifact = payload["artifacts_out"][0]
        self.assertEqual(artifact["artifact_type"], "test_execution_report")
        self.assertEqual(artifact["payload"]["result"], "FAIL")
        self.assertEqual(artifact["payload"]["failure_cause"], "IMPLEMENTATION_DEFECT")
        self.assertIn("python3 -m unittest -q", artifact["payload"]["commands_run"])

    def test_executor_harvests_session_result_after_cli_timeout(self) -> None:
        harvest_openclaw = self._write_harvest_openclaw()
        workspace_ref, task = self._seed_workspace_project(
            "P_harvest_backend",
            to_agent="implementer",
            task_type="IMPLEMENT_SOFTWARE_TASK",
            goal="Implement a harvested workspace change",
            context={"plan_summary": {"implementation_steps": ["edit src/harvested.py"]}},
            expected_output={"artifact_type": "code_change"},
        )
        dispatcher = RuntimeDispatcher(self.harness.store, state_dir=self.harness.state_dir)
        queue_task(dispatcher, task)
        run = self.harness.store.list_pending_runtime_runs(agent_id="implementer")[0]
        packet = yaml.safe_load(Path(run["log_ref"]).read_text())

        executor = OpenClawWorkspaceExecutor(self.harness.store, openclaw_bin=str(harvest_openclaw))
        response_path = self.harness.tmp_path / "harvest_response.yaml"
        log_path = self.harness.tmp_path / "harvest_response.log"
        response = executor.execute(
            packet=packet,
            response_path=response_path,
            log_path=log_path,
            timeout_seconds=1,
            config={"session_grace_seconds": 2},
        )

        self.assertEqual(response["status"], "SUCCESS")
        self.assertTrue((workspace_ref / "src" / "harvested.py").exists())
        self.assertIn("src/harvested.py", response["artifacts_out"][0]["payload"]["changed_files"])
        self.assertIn("harvested_from_session: True", log_path.read_text())

    def test_worker_missing_workspace_is_blocked_not_failed(self) -> None:
        store = self.harness.store
        seed_project(
            store,
            project_id="P_missing_workspace",
            goal="Require a workspace before implementation",
            current_phase="software_implementation",
            current_owner_agent="morpheus",
            next_action={"type": "IMPLEMENT_SOFTWARE_TASK", "target_agent": "implementer"},
        )
        task = store.record_task(
            project_id="P_missing_workspace",
            from_agent="morpheus",
            to_agent="implementer",
            task_type="IMPLEMENT_SOFTWARE_TASK",
            title="IMPLEMENT_SOFTWARE_TASK for P_missing_workspace",
            goal="Require a workspace before implementation",
            priority="MEDIUM",
            context={"plan_summary": {"implementation_steps": ["edit src/main.py"]}},
            expected_output={"artifact_type": "code_change"},
            return_to="requesting_agent",
        )
        dispatcher = RuntimeDispatcher(store, state_dir=self.harness.state_dir)
        queue_task(dispatcher, task)
        worker_config_path = self.harness.tmp_path / "blocked_worker_config.yaml"
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
                        "implementer": {
                            "executor": "openclaw_workspace",
                        }
                    },
                },
                sort_keys=False,
            )
        )

        worker = RuntimeWorker(
            store,
            worker_config_path=worker_config_path,
            state_dir=self.harness.state_dir,
        )
        result = worker.process_once(agent_id="implementer")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "BLOCKED")
        payload = yaml.safe_load(Path(result.response_file).read_text())
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertIn("workspace_ref", payload["summary"])
