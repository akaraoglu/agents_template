from __future__ import annotations

import unittest

from openclaw_agents.runtime.dispatcher import RuntimeDispatcher
from openclaw_agents.runtime.worker_runner import RuntimeWorker

from tests.helpers import ControlPlaneHarness, drain_worker, queue_task, seed_project


class BuiltinLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = ControlPlaneHarness()

    def tearDown(self) -> None:
        self.harness.cleanup()

    def test_builtin_morpheus_loop_completes_and_internal_results_are_not_mirrored(self) -> None:
        store = self.harness.store
        workspace = self.harness.tmp_path / "P_morpheus_loop"
        workspace.mkdir(parents=True, exist_ok=True)
        seed_project(
            store,
            project_id="P_morpheus_loop",
            goal="Deliver a deterministic software package",
            current_phase="software_orchestration",
            current_owner_agent="niobe",
            next_action={"type": "ORCHESTRATE_SOFTWARE", "target_agent": "morpheus"},
            workspace_ref=str(workspace),
        )
        task = store.record_task(
            project_id="P_morpheus_loop",
            from_agent="niobe",
            to_agent="morpheus",
            task_type="ORCHESTRATE_SOFTWARE",
            title="Run the software loop",
            goal="Deliver a deterministic software package",
            priority="MEDIUM",
            context={"suggested_files": ["src/feature.py", "tests/test_feature.py"]},
            expected_output={"artifact_type": "software_delivery_package"},
            return_to="requesting_agent",
        )
        dispatcher = RuntimeDispatcher(store, state_dir=self.harness.state_dir)
        queue_task(dispatcher, task)

        worker = RuntimeWorker(store, state_dir=self.harness.state_dir, default_executor="builtin")
        seen = drain_worker(worker, limit=20)

        self.assertEqual(store.get_task(task["task_id"])["status"], "SUCCESS")
        child_tasks = store.list_child_tasks(task["task_id"])
        self.assertEqual(
            [item["task_type"] for item in child_tasks],
            ["PLAN_SOFTWARE_TASK", "IMPLEMENT_SOFTWARE_TASK", "TEST_SOFTWARE_TASK"],
        )
        self.assertTrue(all(item["status"] == "SUCCESS" for item in child_tasks))

        artifact_types = [
            item["artifact_type"]
            for item in store.fetchall(
                "SELECT artifact_type FROM artifacts WHERE project_id = ? ORDER BY created_at ASC",
                ("P_morpheus_loop",),
            )
        ]
        self.assertIn("software_delivery_package", artifact_types)
        self.assertIn("test_execution_report", artifact_types)

        mirror_candidates = {item["task_id"] for item in store.list_result_mirror_candidates()}
        self.assertIn(task["task_id"], mirror_candidates)
        self.assertFalse(any(item["task_id"] in mirror_candidates for item in child_tasks))
        self.assertTrue(any(item["agent_id"] == "morpheus" and item["status"] == "SUCCESS" for item in seen))

    def test_builtin_project_loop_reroutes_oracle_implementation_failure_back_to_morpheus(self) -> None:
        store = self.harness.store
        workspace = self.harness.tmp_path / "P_project_verification_failure"
        workspace.mkdir(parents=True, exist_ok=True)
        seed_project(
            store,
            project_id="P_project_verification_failure",
            goal="Route verification failures back to implementation",
            current_phase="intake",
            current_owner_agent="agent_smith",
            project_status="NEW",
            next_action={"type": "FRAME_PROJECT", "target_agent": "agent_smith"},
            workspace_ref=str(workspace),
        )
        frame_task = store.record_task(
            project_id="P_project_verification_failure",
            from_agent="human",
            to_agent="agent_smith",
            task_type="FRAME_PROJECT",
            title="Frame the project",
            goal="Route verification failures back to implementation",
            priority="MEDIUM",
            context={
                "suggested_files": ["src/repair.py", "tests/test_repair.py"],
                "force_verification_result": "FAIL",
                "verification_defect_category": "implementation",
            },
            expected_output={"artifact_type": "project_charter"},
            return_to="requesting_agent",
        )
        dispatcher = RuntimeDispatcher(store, state_dir=self.harness.state_dir)
        queue_task(dispatcher, frame_task)

        worker = RuntimeWorker(store, state_dir=self.harness.state_dir, default_executor="builtin")
        seen = drain_worker(worker, limit=24)

        morpheus_tasks = store.fetchall(
            "SELECT task_id, status FROM tasks WHERE project_id = ? AND to_agent = 'morpheus' ORDER BY opened_at ASC",
            ("P_project_verification_failure",),
        )
        oracle_tasks = store.fetchall(
            "SELECT task_id, status FROM tasks WHERE project_id = ? AND to_agent = 'oracle' ORDER BY opened_at ASC",
            ("P_project_verification_failure",),
        )
        niobe_tasks = store.fetchall(
            "SELECT task_id, status FROM tasks WHERE project_id = ? AND to_agent = 'niobe' ORDER BY opened_at ASC",
            ("P_project_verification_failure",),
        )
        project = store.get_project("P_project_verification_failure")

        self.assertGreaterEqual(len(morpheus_tasks), 2)
        self.assertGreaterEqual(len(oracle_tasks), 1)
        self.assertEqual(len(niobe_tasks), 1)
        assert project is not None
        self.assertEqual(project["project_status"], "ACTIVE")
        self.assertIn(project["current_phase"], {"project_implementation", "software_orchestration"})
        self.assertTrue(any(item["agent_id"] == "oracle" and item["status"] == "SUCCESS" for item in seen))
        self.assertIn(morpheus_tasks[-1]["status"], {"PENDING", "RUNNING", "SUCCESS"})

    def test_builtin_morpheus_loop_blocks_before_implementation_when_workspace_is_missing(self) -> None:
        store = self.harness.store
        seed_project(
            store,
            project_id="P_morpheus_missing_workspace",
            goal="Do not dispatch implementation without a workspace",
            current_phase="software_orchestration",
            current_owner_agent="niobe",
            next_action={"type": "ORCHESTRATE_SOFTWARE", "target_agent": "morpheus"},
        )
        task = store.record_task(
            project_id="P_morpheus_missing_workspace",
            from_agent="niobe",
            to_agent="morpheus",
            task_type="ORCHESTRATE_SOFTWARE",
            title="Run the software loop without a workspace",
            goal="Do not dispatch implementation without a workspace",
            priority="MEDIUM",
            context={"suggested_files": ["src/feature.py"]},
            expected_output={"artifact_type": "software_delivery_package"},
            return_to="requesting_agent",
        )
        dispatcher = RuntimeDispatcher(store, state_dir=self.harness.state_dir)
        queue_task(dispatcher, task)

        worker = RuntimeWorker(store, state_dir=self.harness.state_dir, default_executor="builtin")
        drain_worker(worker, limit=10)

        self.assertEqual(store.get_task(task["task_id"])["status"], "BLOCKED")
        child_tasks = store.list_child_tasks(task["task_id"])
        self.assertEqual([item["task_type"] for item in child_tasks], ["PLAN_SOFTWARE_TASK"])
        self.assertEqual(child_tasks[0]["status"], "SUCCESS")
        escalation = store.fetchall(
            "SELECT artifact_type FROM artifacts WHERE project_id = ? AND task_id = ? ORDER BY created_at ASC",
            ("P_morpheus_missing_workspace", task["task_id"]),
        )
        self.assertIn("escalation_packet", [item["artifact_type"] for item in escalation])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
