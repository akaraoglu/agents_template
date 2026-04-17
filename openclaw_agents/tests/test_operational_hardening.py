import tempfile
import unittest
from pathlib import Path

from openclaw_agents.communication.zulip_gateway import ZulipGateway


class OperationalHardeningTest(unittest.TestCase):
    def test_gateway_uses_system_and_projects_layout_under_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime_root = Path(temp_dir) / "clawspace"
            gateway = ZulipGateway(base_dir=runtime_root)
            project = gateway.project_provisioning.create_project_surface(
                name="Layout Atlas",
                summary="Layout validation.",
                requested_by="master@example.com",
            )

            self.assertEqual(gateway.state_store.path, runtime_root / "system" / "state" / "state_store.json")
            self.assertEqual(gateway.mapping_store.path, runtime_root / "system" / "state" / "message_mappings.json")
            self.assertEqual(gateway.dedupe_store.path, runtime_root / "system" / "state" / "event_dedupe.json")
            self.assertEqual(gateway.workspace_service.workspace_root, runtime_root / "projects")
            self.assertTrue(project["workspace_path"].startswith(str(runtime_root / "projects" / project["id"])))
            self.assertEqual(gateway.command_runner.allowed_root, runtime_root.resolve())

    def test_command_runner_blocks_destructive_command_and_audits_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")

            with self.assertRaises(ValueError):
                gateway.command_runner.run("rm -rf /tmp/whatever", actor_agent="neo")

            audits = gateway.audit_log.tail(limit=5, action_type="workspace_command")
            self.assertTrue(any(row["outcome"] == "blocked" for row in audits))

    def test_project_scoped_command_runner_blocks_escape_to_other_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")
            project_a = gateway.project_provisioning.create_project_surface(
                name="Project A",
                summary="Sandbox A.",
                requested_by="master@example.com",
            )
            project_b = gateway.project_provisioning.create_project_surface(
                name="Project B",
                summary="Sandbox B.",
                requested_by="master@example.com",
            )
            project_a_root = gateway.workspace_service.resolve_workspace(project_a["id"])
            project_b_root = gateway.workspace_service.resolve_workspace(project_b["id"])

            with self.assertRaises(ValueError):
                gateway.command_runner.run(
                    "pwd",
                    cwd=project_b_root,
                    actor_agent="implementer",
                    project_id=project_a["id"],
                    allowed_root=project_a_root,
                )

    def test_ops_diagnostics_include_execution_and_audit_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")
            project = gateway.project_provisioning.create_project_surface(
                name="Ops Atlas",
                summary="Diagnostics coverage.",
                requested_by="master@example.com",
            )
            handoff = gateway.artifact_ref_service.persist_execution_handoff(
                gateway.artifact_ref_service.build_execution_handoff(
                    project=project,
                    approved_summary="Start execution.",
                )
            )
            gateway.execution_state.start_execution(handoff["handoff_id"], actor_agent="niaobe")
            snapshot = gateway.ops_diagnostics.diagnostics_snapshot()

            self.assertEqual(snapshot["projects"], 1)
            self.assertEqual(snapshot["handoffs"]["total"], 1)
            self.assertEqual(snapshot["execution_states"]["in_progress"], 1)
            self.assertGreaterEqual(snapshot["audit_entries"], 0)

    def test_restart_preserves_execution_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir) / "runtime"
            gateway = ZulipGateway(base_dir=base_dir)
            project = gateway.project_provisioning.create_project_surface(
                name="Restart Atlas",
                summary="Restart persistence.",
                requested_by="master@example.com",
            )
            handoff = gateway.artifact_ref_service.persist_execution_handoff(
                gateway.artifact_ref_service.build_execution_handoff(
                    project=project,
                    approved_summary="Persist execution state.",
                )
            )
            gateway.execution_state.start_execution(handoff["handoff_id"], actor_agent="niaobe")

            restarted = ZulipGateway(base_dir=base_dir)
            execution_state = restarted.execution_state.get_execution_state_for_handoff(handoff["handoff_id"])
            assert execution_state is not None
            self.assertEqual(execution_state["status"], "IN_PROGRESS")
            self.assertEqual(restarted.state_store.get_handoff(handoff["handoff_id"])["status"], "IN_PROGRESS")


if __name__ == "__main__":
    unittest.main()
