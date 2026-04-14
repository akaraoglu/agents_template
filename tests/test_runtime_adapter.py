from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from openclaw_agents.runtime.external_executor import ExecutionContextBuilder
from openclaw_agents.runtime.artifact_serializers import ArtifactSerializer
from openclaw_agents.runtime.dispatcher import RuntimeDispatcher
from openclaw_agents.runtime.worker_runner import RuntimeWorker

from tests.helpers import ControlPlaneHarness, queue_task, seed_project


class PromptSubprocessExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = ControlPlaneHarness()

    def tearDown(self) -> None:
        self.harness.cleanup()

    def test_prompt_subprocess_executor_builds_context_and_records_response(self) -> None:
        store = self.harness.store
        workspace_ref = self.harness.tmp_path / "workspace"
        workspace_ref.mkdir(parents=True, exist_ok=True)
        seed_project(
            store,
            project_id="P_prompt_subprocess",
            goal="Design a project with external executor context",
            current_phase="project_design",
            current_owner_agent="niobe",
            next_action={"type": "DESIGN_ARCHITECTURE", "target_agent": "architect"},
            workspace_ref=str(workspace_ref),
        )
        store.upsert(
            "workspace_states",
            {
                "workspace_ref": str(workspace_ref),
                "project_id": "P_prompt_subprocess",
                "repo_root": str(workspace_ref),
                "branch_or_worktree_id": "main",
                "last_clean_commit_or_checkpoint": "checkpoint-1",
                "is_consistent": True,
            },
            conflict_columns=["workspace_ref"],
        )
        serializer = ArtifactSerializer(store)
        serializer.serialize(
            project_id="P_prompt_subprocess",
            artifact_type="project_charter",
            payload={
                "problem_statement": "Design a project with external executor context",
                "acceptance_criteria": ["Produce an architecture specification"],
            },
            task_id=None,
            produced_by_agent="agent_smith",
            workspace_ref=str(workspace_ref),
            filename="charter.yaml",
        )
        task = store.record_task(
            project_id="P_prompt_subprocess",
            from_agent="niobe",
            to_agent="architect",
            task_type="DESIGN_ARCHITECTURE",
            title="Design the project",
            goal="Design a project with external executor context",
            priority="MEDIUM",
            context={"requirements": ["Produce an architecture specification"]},
            expected_output={"artifact_type": "architecture_spec"},
            return_to="requesting_agent",
        )
        dispatcher = RuntimeDispatcher(store, state_dir=self.harness.state_dir)
        queue_task(dispatcher, task)

        script_path = self.harness.tmp_path / "prompt_subprocess_executor.py"
        script_path.write_text(
            """
import json
import os
from pathlib import Path

import yaml

context = json.loads(Path(os.environ["OPENCLAW_EXECUTION_CONTEXT"]).read_text())
assert context["agent"]["agent_id"] == "architect"
assert "Architect" in context["agent"]["prompt_text"]
assert context["project_record"]["project_id"] == "P_prompt_subprocess"
assert context["input_artifacts"][0]["artifact_type"] == "project_charter"

response = {
    "task_id": context["task_envelope"]["task_id"],
    "project_id": context["task_envelope"]["project_id"],
    "agent": context["agent"]["agent_id"],
    "status": "SUCCESS",
    "summary": "Prompt subprocess executor produced an architecture spec.",
    "artifacts_out": [
        {
            "artifact_type": "architecture_spec",
            "ref": "inline://architect-external-spec",
            "payload": {
                "summary": "External architecture spec",
                "system_shape": "External prompt-aware subprocess path",
            },
        }
    ],
    "findings": ["external executor used prompt and context"],
    "next_action": {"type": "RETURN_TO_REQUESTER", "reason": "architecture complete", "target_agent": "niobe"},
    "risks": [],
    "trace": {"run_id": context["task_envelope"]["metadata"]["run_id"]},
}
Path(os.environ["OPENCLAW_RESPONSE_FILE"]).write_text(yaml.safe_dump(response, sort_keys=False))
""".strip()
        )

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
                            "command": [sys.executable, str(script_path)],
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
        result = worker.process_once(agent_id="architect")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.status, "SUCCESS")

        response_path = Path(result.response_file)
        context_path = response_path.with_suffix(".context.json")
        context = json.loads(context_path.read_text())
        self.assertEqual(context["context_scope"], "project")
        self.assertEqual(context["context_root"]["root_path"], str(workspace_ref))
        self.assertEqual(context["context_root"]["project_root"], str(workspace_ref))
        self.assertTrue(context["agent"]["prompt_path"].endswith("prompts/architect.md"))
        self.assertEqual(context["model"]["profile"], "ollama_reasoning")
        self.assertEqual(context["model"]["model_hint"], "gemma4:31b")
        self.assertEqual(context["workspace_state"]["workspace_ref"], str(workspace_ref))
        self.assertEqual(context["input_artifacts"][0]["artifact_type"], "project_charter")
        self.assertEqual(context["context_payload"]["scope"], "project")
        self.assertEqual(context["context_payload"]["task"]["task_type"], "DESIGN_ARCHITECTURE")
        self.assertEqual(context["context_payload"]["project"]["project_id"], "P_prompt_subprocess")

        response_payload = yaml.safe_load(response_path.read_text())
        self.assertEqual(response_payload["agent"], "architect")
        persisted_task = store.get_task(task["task_id"])
        assert persisted_task is not None
        self.assertEqual(persisted_task["status"], "SUCCESS")
        persisted_project = store.get_project("P_prompt_subprocess")
        assert persisted_project is not None
        self.assertEqual(persisted_project["current_owner_agent"], "niobe")

    def test_running_handoff_closes_attempt_and_run_but_keeps_parent_task_open(self) -> None:
        store = self.harness.store
        workspace_ref = self.harness.tmp_path / "workspace"
        workspace_ref.mkdir(parents=True, exist_ok=True)
        seed_project(
            store,
            project_id="P_running_handoff",
            goal="Keep the parent task open while closing the handoff attempt",
            current_phase="project_orchestration",
            current_owner_agent="niobe",
            next_action={"type": "ORCHESTRATE_PROJECT", "target_agent": "niobe"},
            workspace_ref=str(workspace_ref),
        )
        task = store.record_task(
            project_id="P_running_handoff",
            from_agent="agent_smith",
            to_agent="niobe",
            task_type="ORCHESTRATE_PROJECT",
            title="Advance the project",
            goal="Keep the parent task open while closing the handoff attempt",
            priority="MEDIUM",
            context={},
            expected_output={"artifact_type": "project_status_report"},
            return_to="requesting_agent",
        )
        dispatcher = RuntimeDispatcher(store, state_dir=self.harness.state_dir)
        receipt = dispatcher.dispatch_plan(
            type(
                "Plan",
                (),
                {
                    "project_id": task["project_id"],
                    "task_id": task["task_id"],
                    "target_agent": task["to_agent"],
                    "task_type": task["task_type"],
                    "reply_stream": "projects",
                    "reply_topic": "running_handoff",
                    "reason": task["goal"],
                },
            )()
        )

        response = {
            "task_id": task["task_id"],
            "project_id": task["project_id"],
            "agent": "niobe",
            "status": "RUNNING",
            "summary": "Niobe queued Architect and is waiting for the design result.",
            "artifacts_out": [
                {
                    "artifact_type": "project_status_report",
                    "ref": "inline://niobe-status-running-handoff",
                    "payload": {
                        "project_id": task["project_id"],
                        "task_id": task["task_id"],
                        "state": "WAITING_RESULT",
                        "summary": "Niobe queued Architect and is waiting for the design result.",
                        "evidence_received": [],
                        "next_action": {
                            "type": "WAIT_FOR_EXTERNAL",
                            "reason": "Architect is producing the architecture specification.",
                            "target_agent": "architect",
                        },
                        "safe_to_pause_or_switch": True,
                    },
                }
            ],
            "findings": ["child task dispatched"],
            "next_action": {
                "type": "WAIT_FOR_EXTERNAL",
                "reason": "Architect is producing the architecture specification.",
                "target_agent": "architect",
            },
            "risks": [],
            "trace": {"run_id": receipt.run_id},
        }

        dispatcher.record_response(response)

        attempt = store.get_latest_task_attempt(task["task_id"])
        assert attempt is not None
        self.assertEqual(attempt["status"], "SUCCESS")
        self.assertIsNotNone(attempt["finished_at"])

        run = store.get_agent_run(receipt.run_id)
        assert run is not None
        self.assertEqual(run["result_status"], "SUCCESS")
        self.assertIsNotNone(run["ended_at"])

        persisted_task = store.get_task(task["task_id"])
        assert persisted_task is not None
        self.assertEqual(persisted_task["status"], "RUNNING")
        self.assertIsNone(persisted_task["closed_at"])

        persisted_project = store.get_project(task["project_id"])
        assert persisted_project is not None
        self.assertEqual(persisted_project["runtime_status"], "WAITING_EXTERNAL")
        self.assertEqual(persisted_project["current_owner_agent"], "architect")

    def test_execution_context_builder_uses_task_scope_for_software_roles(self) -> None:
        store = self.harness.store
        projects_root = self.harness.tmp_path / "projects"
        workspace_ref = projects_root / "P_task_scope"
        workspace_ref.mkdir(parents=True, exist_ok=True)
        seed_project(
            store,
            project_id="P_task_scope",
            goal="Implement a focused software task",
            current_phase="software_implementation",
            current_owner_agent="morpheus",
            next_action={"type": "IMPLEMENT_SOFTWARE_TASK", "target_agent": "implementer"},
            workspace_ref=str(workspace_ref),
        )
        store.upsert(
            "workspace_states",
            {
                "workspace_ref": str(workspace_ref),
                "project_id": "P_task_scope",
                "repo_root": str(workspace_ref),
                "branch_or_worktree_id": "main",
                "last_clean_commit_or_checkpoint": "checkpoint-2",
                "is_consistent": True,
            },
            conflict_columns=["workspace_ref"],
        )
        serializer = ArtifactSerializer(store)
        serializer.serialize(
            project_id="P_task_scope",
            artifact_type="project_charter",
            payload={
                "problem_statement": "Build a focused implementation path",
                "acceptance_criteria": ["Implement the requested function"],
            },
            produced_by_agent="agent_smith",
            workspace_ref=str(workspace_ref),
        )
        serializer.serialize(
            project_id="P_task_scope",
            artifact_type="architecture_spec",
            payload={
                "summary": "Use a single module in the project workspace.",
                "constraints": ["Keep implementation in the project folder only."],
            },
            produced_by_agent="architect",
            workspace_ref=str(workspace_ref),
        )
        plan_artifact = serializer.serialize(
            project_id="P_task_scope",
            artifact_type="software_task_plan",
            payload={
                "summary": "Implement fibonacci and cover representative inputs.",
                "implementation_steps": ["Add fibonacci function", "Add CLI entry point"],
                "test_obligations": ["Cover 0, 1, 5, 10, negative input"],
            },
            produced_by_agent="planner",
            workspace_ref=str(workspace_ref),
        )
        serializer.serialize(
            project_id="P_task_scope",
            artifact_type="verification_report",
            payload={
                "summary": "Older verification output that should not be part of task context.",
                "result": "PASS",
            },
            produced_by_agent="oracle",
            workspace_ref=str(workspace_ref),
        )
        parent_task = store.record_task(
            project_id="P_task_scope",
            from_agent="niobe",
            to_agent="morpheus",
            task_type="ORCHESTRATE_SOFTWARE",
            title="Drive software delivery",
            goal="Deliver the requested software change",
            priority="MEDIUM",
            context={"software_goal": "Build fibonacci support"},
            expected_output={"artifact_type": "software_delivery_package"},
            return_to="requesting_agent",
        )
        task = store.record_task(
            project_id="P_task_scope",
            parent_task_id=parent_task["task_id"],
            from_agent="morpheus",
            to_agent="implementer",
            task_type="IMPLEMENT_SOFTWARE_TASK",
            title="Implement the code change",
            goal="Implement fibonacci support",
            priority="MEDIUM",
            context={
                "software_goal": "Build fibonacci support",
                "suggested_files": ["fibonacci.py", "test_fibonacci.py"],
                "plan_summary": {
                    "summary": "Implement core function then CLI.",
                    "implementation_steps": ["Add fibonacci()", "Add cli()"],
                    "test_obligations": ["Test positive and negative inputs"],
                },
            },
            expected_output={"artifact_type": "code_change"},
            return_to="requesting_agent",
        )
        dispatcher = RuntimeDispatcher(store, state_dir=self.harness.state_dir)
        receipt = dispatcher.dispatch_plan(
            type(
                "Plan",
                (),
                {
                    "project_id": task["project_id"],
                    "task_id": task["task_id"],
                    "target_agent": task["to_agent"],
                    "task_type": task["task_type"],
                    "reply_stream": "projects",
                    "reply_topic": "project/P_task_scope",
                    "reason": task["goal"],
                },
            )()
        )
        packet = yaml.safe_load(Path(receipt.packet_ref).read_text())
        builder = ExecutionContextBuilder(store)

        with patch.dict(
            os.environ,
            {"OPENCLAW_PROJECT_WORKSPACES_DIR": str(projects_root)},
            clear=False,
        ):
            context = builder.build(packet)

        self.assertEqual(context["context_scope"], "task")
        self.assertEqual(context["context_root"]["root_path"], str(workspace_ref))
        self.assertEqual(context["context_root"]["project_root"], str(workspace_ref))
        self.assertIsNone(context["context_root"]["workspace_root"])
        self.assertEqual(context["context_payload"]["scope"], "task")
        self.assertEqual(context["context_payload"]["project"]["project_id"], "P_task_scope")
        self.assertNotIn("workspace_ref", context["context_payload"]["project"])
        relevant_types = [item["artifact_type"] for item in context["relevant_artifacts"]]
        self.assertIn("software_task_plan", relevant_types)
        self.assertIn("architecture_spec", relevant_types)
        self.assertIn("project_charter", relevant_types)
        self.assertNotIn("verification_report", relevant_types)
        self.assertIn(plan_artifact["ref"], [item["ref"] for item in context["input_artifacts"]])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
