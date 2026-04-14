from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from openclaw_agents.database.store import utc_now
from openclaw_agents.runtime.artifact_serializers import ArtifactSerializer
from openclaw_agents.runtime.dispatcher import RuntimeDispatcher
from openclaw_agents.scheduler.management_writer import WorkspaceManagementWriter

from tests.helpers import ControlPlaneHarness, seed_project


class WorkspaceManagementWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = ControlPlaneHarness()

    def tearDown(self) -> None:
        self.harness.cleanup()

    def _seed_workspace_state(self, project_id: str, workspace_ref: Path) -> None:
        self.harness.store.upsert(
            "workspace_states",
            {
                "workspace_ref": str(workspace_ref),
                "project_id": project_id,
                "repo_root": str(workspace_ref),
                "branch_or_worktree_id": workspace_ref.name,
                "last_clean_commit_or_checkpoint": "checkpoint-1",
                "is_consistent": True,
                "last_validated_at": utc_now(),
                "last_validation_summary": "test workspace ready",
            },
            conflict_columns=["workspace_ref"],
        )

    def test_sync_project_repairs_missing_scaffold_and_renders_management_files(self) -> None:
        workspace_ref = self.harness.tmp_path / "projects" / "P_manage"
        (workspace_ref / "fibonacci-demo").mkdir(parents=True, exist_ok=True)
        (workspace_ref / "fibonacci-demo" / "fibonacci.py").write_text("def fibonacci(n):\n    return n\n")

        seed_project(
            self.harness.store,
            project_id="P_manage",
            goal="Build a fibonacci command-line tool",
            current_phase="software_implementation",
            current_owner_agent="implementer",
            runtime_status="WAITING_EXTERNAL",
            next_action={
                "type": "WAIT_FOR_EXTERNAL",
                "reason": "Implementer is applying the software change.",
                "target_agent": "implementer",
            },
            workspace_ref=str(workspace_ref),
        )
        self._seed_workspace_state("P_manage", workspace_ref)

        serializer = ArtifactSerializer(self.harness.store)
        serializer.serialize(
            project_id="P_manage",
            artifact_type="project_charter",
            payload={
                "problem_statement": "Build a fibonacci command-line tool",
                "goals": ["Add a CLI tool", "Support representative fibonacci inputs"],
                "acceptance_criteria": ["Input 10 returns 55", "Negative input fails clearly"],
            },
            produced_by_agent="agent_smith",
            workspace_ref=str(workspace_ref),
        )
        serializer.serialize(
            project_id="P_manage",
            artifact_type="architecture_spec",
            payload={
                "summary": "Single-project CLI with implementation and tests inside the project folder.",
                "system_shape": "Single-module Python CLI with tests.",
                "constraints": ["Keep all files in the project workspace.", "Verify with automated tests."],
            },
            produced_by_agent="architect",
            workspace_ref=str(workspace_ref),
        )
        self.harness.store.record_task(
            project_id="P_manage",
            from_agent="agent_smith",
            to_agent="niaobe",
            task_type="ORCHESTRATE_PROJECT",
            title="Drive the project loop",
            goal="Build a fibonacci command-line tool",
            priority="MEDIUM",
            status="RUNNING",
            return_to="requesting_agent",
            task_id="T_parent_niaobe",
        )
        self.harness.store.record_task(
            project_id="P_manage",
            parent_task_id="T_parent_niaobe",
            from_agent="niaobe",
            to_agent="morpheus",
            task_type="ORCHESTRATE_SOFTWARE",
            title="Deliver the software package",
            goal="Build a fibonacci command-line tool",
            priority="MEDIUM",
            status="RUNNING",
            return_to="niaobe",
            task_id="T_morpheus_active",
        )
        self.harness.store.record_task(
            project_id="P_manage",
            parent_task_id="T_morpheus_active",
            from_agent="morpheus",
            to_agent="implementer",
            task_type="IMPLEMENT_SOFTWARE_TASK",
            title="Implement fibonacci",
            goal="Implement the fibonacci CLI and tests",
            priority="MEDIUM",
            status="RUNNING",
            return_to="morpheus",
            task_id="T_implementer_active",
        )

        writer = WorkspaceManagementWriter(self.harness.store)
        result = writer.sync_project("P_manage")

        self.assertIsNotNone(result)
        self.assertTrue((workspace_ref / "PROJECT.md").exists())
        self.assertTrue((workspace_ref / "management" / "STATUS.md").exists())
        self.assertTrue((workspace_ref / "management" / "BACKLOG.md").exists())
        self.assertTrue((workspace_ref / "management" / "MILESTONES.md").exists())
        self.assertTrue((workspace_ref / "management" / "DECISIONS.md").exists())
        self.assertTrue((workspace_ref / "management" / "TEST_REPORT.md").exists())

        status_text = (workspace_ref / "management" / "STATUS.md").read_text()
        backlog_text = (workspace_ref / "management" / "BACKLOG.md").read_text()
        decisions_text = (workspace_ref / "management" / "DECISIONS.md").read_text()

        self.assertIn("software_implementation", status_text)
        self.assertIn("implementer", status_text)
        self.assertIn("IMPLEMENT_SOFTWARE_TASK", backlog_text)
        self.assertIn("ORCHESTRATE_SOFTWARE", backlog_text)
        self.assertIn("Single-module Python CLI with tests", decisions_text)

    def test_dispatch_and_response_sync_management_projection(self) -> None:
        workspace_ref = self.harness.tmp_path / "projects" / "P_dispatch_sync"
        seed_project(
            self.harness.store,
            project_id="P_dispatch_sync",
            goal="Design and deliver a fibonacci project",
            current_phase="project_design",
            current_owner_agent="architect",
            next_action={
                "type": "DESIGN_ARCHITECTURE",
                "reason": "Architect is producing the design.",
                "target_agent": "architect",
            },
            workspace_ref=str(workspace_ref),
        )
        self._seed_workspace_state("P_dispatch_sync", workspace_ref)

        serializer = ArtifactSerializer(self.harness.store)
        serializer.serialize(
            project_id="P_dispatch_sync",
            artifact_type="project_charter",
            payload={
                "problem_statement": "Design and deliver a fibonacci project",
                "goals": ["Deliver a fibonacci implementation"],
                "acceptance_criteria": ["Produce an architecture spec before implementation"],
            },
            produced_by_agent="agent_smith",
            workspace_ref=str(workspace_ref),
        )
        task = self.harness.store.record_task(
            project_id="P_dispatch_sync",
            from_agent="niaobe",
            to_agent="architect",
            task_type="DESIGN_ARCHITECTURE",
            title="Design the fibonacci system",
            goal="Design and deliver a fibonacci project",
            priority="MEDIUM",
            context={"requirements": ["Produce an architecture spec before implementation"]},
            expected_output={"artifact_type": "architecture_spec"},
            return_to="requesting_agent",
            task_id="T_design_sync",
        )
        dispatcher = RuntimeDispatcher(self.harness.store, state_dir=self.harness.state_dir)

        receipt = dispatcher.dispatch_plan(
            SimpleNamespace(
                project_id=task["project_id"],
                task_id=task["task_id"],
                target_agent=task["to_agent"],
                task_type=task["task_type"],
                reply_stream="projects",
                reply_topic="design-sync",
                reason=task["goal"],
            )
        )

        status_text = (workspace_ref / "management" / "STATUS.md").read_text()
        backlog_text = (workspace_ref / "management" / "BACKLOG.md").read_text()
        self.assertIn("DESIGN_ARCHITECTURE", status_text)
        self.assertIn("T_design_sync", backlog_text)

        dispatcher.record_response(
            {
                "task_id": task["task_id"],
                "project_id": task["project_id"],
                "agent": task["to_agent"],
                "status": "SUCCESS",
                "summary": "Architect completed the fibonacci design.",
                "artifacts_out": [
                    {
                        "artifact_type": "architecture_spec",
                        "ref": "inline://architecture-design-sync",
                        "payload": {
                            "summary": "Use a single Python module with a CLI wrapper.",
                            "system_shape": "Single Python module plus tests.",
                            "constraints": ["Keep implementation and tests in the project folder."],
                        },
                    }
                ],
                "findings": ["Use a single Python module with tests."],
                "next_action": {
                    "type": "RETURN_TO_REQUESTER",
                    "reason": "Architecture is ready for Niaobe.",
                    "target_agent": "niaobe",
                },
                "risks": [],
                "trace": {"run_id": receipt.run_id},
            }
        )

        milestones_text = (workspace_ref / "management" / "MILESTONES.md").read_text()
        decisions_text = (workspace_ref / "management" / "DECISIONS.md").read_text()
        self.assertIn("Architecture", milestones_text)
        self.assertIn("`DONE`", milestones_text)
        self.assertIn("Single Python module plus tests.", decisions_text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
