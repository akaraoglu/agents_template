from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import yaml

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
        self.assertTrue(context["agent"]["prompt_path"].endswith("prompts/architect.md"))
        self.assertEqual(context["model"]["profile"], "ollama_reasoning")
        self.assertEqual(context["model"]["model_hint"], "gemma4:31b")
        self.assertEqual(context["workspace_state"]["workspace_ref"], str(workspace_ref))
        self.assertEqual(context["input_artifacts"][0]["artifact_type"], "project_charter")

        response_payload = yaml.safe_load(response_path.read_text())
        self.assertEqual(response_payload["agent"], "architect")
        persisted_task = store.get_task(task["task_id"])
        assert persisted_task is not None
        self.assertEqual(persisted_task["status"], "SUCCESS")
        persisted_project = store.get_project("P_prompt_subprocess")
        assert persisted_project is not None
        self.assertEqual(persisted_project["current_owner_agent"], "niobe")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
