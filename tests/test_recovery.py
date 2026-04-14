from __future__ import annotations

import unittest
from pathlib import Path

from openclaw_agents.scheduler.control_commands import ControlCommandService
from openclaw_agents.scheduler.lease_manager import LeaseManager
from openclaw_agents.scheduler.recovery_manager import RecoveryManager
from openclaw_agents.scheduler.snapshot_store import SnapshotStore
from openclaw_agents.scheduler.workspace_validator import WorkspaceValidator

from tests.helpers import ControlPlaneHarness, init_git_workspace, run_git, seed_project


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = ControlPlaneHarness()
        self.project_id = "P_recovery"
        self.workspace, self.head = init_git_workspace(self.harness.tmp_path / "repo")
        self._seed_workspace_project()

    def tearDown(self) -> None:
        self.harness.cleanup()

    def _seed_workspace_project(
        self,
        *,
        branch_or_worktree_id: str = "main",
        checkpoint: str | None = None,
    ) -> None:
        checkpoint = checkpoint or self.head
        seed_project(
            self.harness.store,
            project_id=self.project_id,
            goal="Validate recovery behavior",
            current_phase="software_orchestration",
            current_owner_agent="niobe",
            workspace_ref=str(self.workspace),
            next_action={"type": "ORCHESTRATE_SOFTWARE", "target_agent": "morpheus"},
        )
        self.harness.store.upsert(
            "workspace_states",
            {
                "workspace_ref": str(self.workspace),
                "project_id": self.project_id,
                "repo_root": str(self.workspace),
                "branch_or_worktree_id": branch_or_worktree_id,
                "last_clean_commit_or_checkpoint": checkpoint,
                "is_consistent": True,
            },
            conflict_columns=["workspace_ref"],
        )

    def _capture_snapshot(self) -> dict:
        return SnapshotStore(self.harness.store).capture_project_snapshot(
            self.project_id,
            captured_by="niobe",
            latest_human_summary="safe boundary",
        )

    def test_workspace_validator_flags_dirty_tree_and_ignores_generated_artifacts(self) -> None:
        (self.workspace / "artifacts" / "incoming").mkdir(parents=True, exist_ok=True)
        (self.workspace / "artifacts" / "incoming" / "packet.yaml").write_text("packet: true\n")
        (self.workspace / ".agents").mkdir(parents=True, exist_ok=True)
        (self.workspace / ".agents" / "state.json").write_text("{}\n")
        (self.workspace / "README.md").write_text("seed\nchanged\n")

        result = WorkspaceValidator(self.harness.store).validate_project(self.project_id)

        self.assertFalse(result.ok)
        self.assertIn("workspace_dirty_tracked_files", result.issues)
        self.assertNotIn("workspace_has_untracked_files", result.issues)
        self.assertEqual(result.details["dirty_tracked_files"], ["README.md"])
        self.assertEqual(result.details["untracked_files"], [])

    def test_workspace_validator_flags_branch_and_checkpoint_reference_mismatch(self) -> None:
        self.harness.store.update(
            "workspace_states",
            {
                "branch_or_worktree_id": "feature/recovery-check",
                "last_clean_commit_or_checkpoint": "deadbeef",
            },
            where_clause="workspace_ref = ?",
            where_params=[str(self.workspace)],
        )

        result = WorkspaceValidator(self.harness.store).validate_project(self.project_id)

        self.assertFalse(result.ok)
        self.assertIn("workspace_branch_or_worktree_mismatch", result.issues)
        self.assertIn("workspace_checkpoint_reference_missing", result.issues)

    def test_missing_snapshot_blocks_resume_and_persists_recovery_event(self) -> None:
        manager = RecoveryManager(self.harness.store)

        assessment = manager.assess_resume(self.project_id, orchestrator_id="niobe")

        self.assertFalse(assessment.ok)
        self.assertIn("missing_snapshot", assessment.issues)
        event = self.harness.store.get_recovery_event(assessment.recovery_event_id or "")
        assert event is not None
        self.assertEqual(event["failure_mode"], "resume_readiness_failed")
        self.assertEqual(event["details_json"]["latest_snapshot_id"], None)

    def test_recovery_assessment_blocks_dirty_workspace_and_records_details(self) -> None:
        self._capture_snapshot()
        (self.workspace / "README.md").write_text("seed\nbroken change\n")

        assessment = RecoveryManager(self.harness.store).assess_resume(self.project_id, orchestrator_id="niobe")

        self.assertFalse(assessment.ok)
        self.assertIn("workspace_dirty_tracked_files", assessment.issues)
        project = self.harness.store.get_project(self.project_id)
        schedule = self.harness.store.get_scheduling_record(self.project_id)
        assert project is not None
        assert schedule is not None
        self.assertEqual(project["runtime_status"], "BLOCKED")
        self.assertEqual(schedule["queue_state"], "blocked")
        self.assertEqual(schedule["waiting_reason"], "recovery_required")
        event = self.harness.store.get_recovery_event(assessment.recovery_event_id or "")
        assert event is not None
        self.assertIn("workspace_dirty_tracked_files", event["details_json"]["issues"])
        self.assertEqual(
            event["details_json"]["workspace_validation"]["details"]["dirty_tracked_files"],
            ["README.md"],
        )

    def test_resume_succeeds_after_manual_workspace_repair(self) -> None:
        self._capture_snapshot()
        (self.workspace / "README.md").write_text("seed\nbroken change\n")
        recovery_manager = RecoveryManager(self.harness.store)
        first = recovery_manager.assess_resume(self.project_id, orchestrator_id="niobe")
        self.assertFalse(first.ok)

        run_git(self.workspace, "checkout", "--", "README.md")
        validator = WorkspaceValidator(self.harness.store)
        validation = validator.validate_project(self.project_id)
        self.assertTrue(validation.ok)

        result = ControlCommandService(self.harness.store).resume_project(
            self.project_id,
            requested_by="operator",
            orchestrator_id="niobe",
        )

        self.assertEqual(result.status, "APPLIED")
        project = self.harness.store.get_project(self.project_id)
        schedule = self.harness.store.get_scheduling_record(self.project_id)
        assert project is not None
        assert schedule is not None
        self.assertEqual(project["runtime_status"], "READY")
        self.assertEqual(schedule["queue_state"], "active_recovery")
        self.assertTrue(schedule["eligible_for_scheduling"])

    def test_recovery_assessment_rejects_active_lease_and_running_run(self) -> None:
        self._capture_snapshot()
        LeaseManager(self.harness.store).acquire("niobe", self.project_id, run_id="run_live")

        assessment = RecoveryManager(self.harness.store).assess_resume(self.project_id, orchestrator_id="niobe")

        self.assertFalse(assessment.ok)
        self.assertIn("active_orchestrator_lease_present", assessment.issues)
        self.assertIn("active_agent_runs_present", assessment.issues)
        self.assertEqual(assessment.details["active_leases"][0]["orchestrator_id"], "niobe")
        self.assertEqual(assessment.details["active_agent_runs"][0]["run_id"], "run_live")

    def test_forced_interrupt_records_latest_snapshot_reference(self) -> None:
        snapshot = self._capture_snapshot()

        event = RecoveryManager(self.harness.store).record_forced_interrupt(
            self.project_id,
            orchestrator_id="niobe",
            reason="operator forced switch",
        )

        self.assertEqual(event["failure_mode"], "forced_interrupt")
        self.assertEqual(event["details_json"]["latest_snapshot_id"], snapshot["snapshot_id"])
        self.assertTrue(event["details_json"]["requires_recovery_assessment"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
