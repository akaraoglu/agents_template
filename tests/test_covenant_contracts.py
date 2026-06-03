from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "AgenticTeam" / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from covenant_contracts import (
    ContractValidationError,
    validate_done_workspace_contract,
    validate_project_workspace,
    validate_envelope_work_result,
    validate_task_pack,
    validate_verification_evidence,
    validate_work_report,
    validate_work_result,
)


class VerificationEvidenceTests(unittest.TestCase):
    def _valid_payload(self) -> dict[str, object]:
        return {
            "task_id": "T001",
            "agent": "morpheus",
            "timestamp": "2026-06-01T12:00:00Z",
            "performed": True,
            "command": ["python3", "-m", "pytest", "tests/test_main.py"],
            "status": "pass",
            "summary": "All tests passed.",
            "evidence_paths": ["tests/test_main.py", "README.md"],
        }

    def test_verification_evidence_accepts_valid_payload(self) -> None:
        evidence = validate_verification_evidence(self._valid_payload())
        self.assertEqual(evidence.task_id, "T001")
        self.assertEqual(evidence.status, "pass")
        self.assertEqual(evidence.command, ["python3", "-m", "pytest", "tests/test_main.py"])

    def test_verification_evidence_rejects_missing_command(self) -> None:
        payload = self._valid_payload()
        payload["command"] = []
        with self.assertRaises(ContractValidationError):
            validate_verification_evidence(payload)

    def test_verification_evidence_rejects_failed_status(self) -> None:
        payload = self._valid_payload()
        payload["status"] = "fail"
        with self.assertRaises(ContractValidationError):
            validate_verification_evidence(payload)

    def test_verification_evidence_rejects_missing_timestamp(self) -> None:
        payload = self._valid_payload()
        payload["timestamp"] = ""
        with self.assertRaises(ContractValidationError):
            validate_verification_evidence(payload)

    def test_verification_evidence_rejects_invalid_task_reference(self) -> None:
        payload = self._valid_payload()
        payload["task_id"] = "task-one"
        with self.assertRaises(ContractValidationError):
            validate_verification_evidence(payload)


class WorkResultTests(unittest.TestCase):
    def _verification(self) -> dict[str, object]:
        return {
            "task_id": "T001",
            "agent": "morpheus",
            "timestamp": "2026-06-01T12:00:00Z",
            "performed": True,
            "command": ["python3", "-m", "pytest", "tests/test_main.py"],
            "status": "pass",
            "summary": "All tests passed.",
            "evidence_paths": ["tests/test_main.py", "README.md"],
        }

    def test_work_result_accepts_done_with_evidence(self) -> None:
        result = validate_work_result(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "morpheus",
                "phase": "IMPLEMENT",
                "status": "DONE",
                "summary": "Implementation complete.",
                "verification": self._verification(),
            }
        )
        self.assertEqual(result.status, "DONE")
        self.assertIsNotNone(result.verification)

    def test_work_result_rejects_done_without_evidence(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_work_result(
                {
                    "project_id": "demo-project",
                    "task_id": "T001",
                    "from": "morpheus",
                    "phase": "IMPLEMENT",
                    "status": "DONE",
                    "summary": "Implementation complete.",
                }
            )

    def test_work_result_accepts_blocked_with_reason(self) -> None:
        result = validate_work_result(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "morpheus",
                "phase": "IMPLEMENT",
                "status": "BLOCKED",
                "summary": "Missing dependency.",
                "reason": "Dependency is unavailable in allowed environment.",
                "next_action": "Provide dependency or relax policy.",
            }
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.reason, "Dependency is unavailable in allowed environment.")

    def test_work_result_accepts_failed_with_reason(self) -> None:
        result = validate_work_result(
            {
                "project_id": "demo-project",
                "task_id": "T001",
                "from": "morpheus",
                "phase": "IMPLEMENT",
                "status": "FAILED",
                "summary": "Runtime command failed.",
                "reason": "project_exec.sh returned helper_failed.",
            }
        )
        self.assertEqual(result.status, "FAILED")

    def test_work_result_rejects_malformed_payload(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_work_result(
                {
                    "project_id": "",
                    "task_id": "T001",
                    "from": "morpheus",
                    "phase": "IMPLEMENT",
                    "status": "DONE",
                    "summary": "bad",
                    "verification": {"task_id": "T001"},
                }
            )


class RuntimeValidationHelperTests(unittest.TestCase):
    def _valid_envelope(self) -> dict[str, object]:
        return {
            "project_id": "demo-project",
            "task_id": "T001",
            "from": "morpheus",
            "to": "niaobe",
            "phase": "IMPLEMENT",
            "instructions": "DONE: Artifacts=README.md.",
            "work_result": {
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
                    "command": ["python3", "-m", "pytest", "tests/test_main.py"],
                    "status": "pass",
                    "summary": "All tests passed.",
                    "evidence_paths": ["tests/test_main.py", "README.md"],
                },
            },
        }

    def test_runtime_helper_accepts_matching_done_result(self) -> None:
        result = validate_envelope_work_result(
            self._valid_envelope(),
            expected_from="morpheus",
            expected_phase="IMPLEMENT",
            required_status="DONE",
        )
        self.assertEqual(result.status, "DONE")

    def test_runtime_helper_rejects_missing_work_result(self) -> None:
        envelope = self._valid_envelope()
        envelope.pop("work_result")
        with self.assertRaisesRegex(ContractValidationError, "missing required field: work_result"):
            validate_envelope_work_result(envelope, expected_from="morpheus", expected_phase="IMPLEMENT", required_status="DONE")

    def test_runtime_helper_rejects_non_object_work_result(self) -> None:
        envelope = self._valid_envelope()
        envelope["work_result"] = "bad"
        with self.assertRaisesRegex(ContractValidationError, "work_result must be a JSON object"):
            validate_envelope_work_result(envelope, expected_from="morpheus", expected_phase="IMPLEMENT", required_status="DONE")

    def test_runtime_helper_rejects_phase_mismatch(self) -> None:
        envelope = self._valid_envelope()
        work = envelope["work_result"]
        assert isinstance(work, dict)
        work["phase"] = "DESIGN"
        with self.assertRaises(ContractValidationError):
            validate_envelope_work_result(envelope, expected_from="morpheus", expected_phase="IMPLEMENT", required_status="DONE")


class WorkspaceArtifactContractTests(unittest.TestCase):
    def _work_result_done(self, *, evidence_paths: list[str]) -> object:
        return validate_work_result(
            {
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
                    "command": ["python3", "-m", "pytest", "tests/test_main.py"],
                    "status": "pass",
                    "summary": "All tests passed.",
                    "evidence_paths": evidence_paths,
                },
            }
        )

    def _workspace_payload(self, workspace_root: Path, *, runtime_root: Path | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "workspace_root": str(workspace_root),
            "allowed_write_paths": ["README.md", "src/main.py", "tests/test_main.py"],
            "expected_artifacts": ["README.md", "src/main.py", "tests/test_main.py"],
            "approved_runtime_evidence_roots": [],
        }
        if runtime_root is not None:
            payload["approved_runtime_evidence_roots"] = [str(runtime_root)]
        return payload

    def _manifest_payload(self, *, evidence_paths: list[str], created: list[str] | None = None) -> dict[str, object]:
        return {
            "created": created or ["README.md", "src/main.py", "tests/test_main.py"],
            "changed": [],
            "moved": [],
            "deleted": [],
            "expected_artifacts": ["README.md", "src/main.py", "tests/test_main.py"],
            "evidence_paths": evidence_paths,
        }

    def _touch_expected_artifacts(self, workspace_root: Path) -> None:
        for relative in ("README.md", "src/main.py", "tests/test_main.py"):
            path = workspace_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("ok\n", encoding="utf-8")

    def test_workspace_contract_accepts_valid_artifact_paths_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            self._touch_expected_artifacts(workspace_root)
            work_result = self._work_result_done(evidence_paths=["tests/test_main.py"])
            validate_done_workspace_contract(
                workspace_payload=self._workspace_payload(workspace_root),
                artifact_manifest_payload=self._manifest_payload(evidence_paths=["tests/test_main.py"]),
                work_result=work_result,
                artifact_exists=Path.exists,
            )

    def test_workspace_contract_rejects_missing_expected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            for relative in ("README.md", "src/main.py"):
                path = workspace_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ok\n", encoding="utf-8")
            work_result = self._work_result_done(evidence_paths=["tests/test_main.py"])
            with self.assertRaises(ContractValidationError):
                validate_done_workspace_contract(
                    workspace_payload=self._workspace_payload(workspace_root),
                    artifact_manifest_payload=self._manifest_payload(evidence_paths=["tests/test_main.py"]),
                    work_result=work_result,
                    artifact_exists=Path.exists,
                )

    def test_workspace_contract_rejects_artifact_path_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            workspace = validate_project_workspace(self._workspace_payload(workspace_root))
            with self.assertRaises(ContractValidationError):
                from covenant_contracts import validate_artifact_manifest

                validate_artifact_manifest(
                    {
                        "created": ["../evil.py"],
                        "changed": [],
                        "moved": [],
                        "deleted": [],
                        "expected_artifacts": ["README.md", "src/main.py", "tests/test_main.py"],
                        "evidence_paths": ["tests/test_main.py"],
                    },
                    workspace=workspace,
                )

    def test_workspace_contract_rejects_evidence_path_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            outside = Path(tmp) / "outside.log"
            outside.write_text("x\n", encoding="utf-8")
            work_result = self._work_result_done(evidence_paths=[str(outside)])
            with self.assertRaises(ContractValidationError):
                validate_done_workspace_contract(
                    workspace_payload=self._workspace_payload(workspace_root),
                    artifact_manifest_payload=self._manifest_payload(evidence_paths=[str(outside)]),
                    work_result=work_result,
                    artifact_exists=Path.exists,
                )

    def test_workspace_contract_allows_approved_runtime_evidence_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            runtime_root = Path(tmp) / "runtime"
            workspace_root.mkdir(parents=True, exist_ok=True)
            runtime_root.mkdir(parents=True, exist_ok=True)
            self._touch_expected_artifacts(workspace_root)
            runtime_log = runtime_root / "logs" / "exec.log"
            runtime_log.parent.mkdir(parents=True, exist_ok=True)
            runtime_log.write_text("ok\n", encoding="utf-8")
            work_result = self._work_result_done(evidence_paths=[str(runtime_log)])
            validate_done_workspace_contract(
                workspace_payload=self._workspace_payload(workspace_root, runtime_root=runtime_root),
                artifact_manifest_payload=self._manifest_payload(evidence_paths=[str(runtime_log)]),
                work_result=work_result,
                artifact_exists=Path.exists,
            )

    def test_workspace_contract_rejects_changed_files_without_artifact_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            self._touch_expected_artifacts(workspace_root)
            work_result = self._work_result_done(evidence_paths=["tests/test_main.py"])
            with self.assertRaisesRegex(ContractValidationError, "DONE requires artifact_manifest"):
                validate_done_workspace_contract(
                    workspace_payload=self._workspace_payload(workspace_root),
                    artifact_manifest_payload=None,
                    work_result=work_result,
                    artifact_exists=Path.exists,
                )

    def test_workspace_contract_rejects_empty_artifact_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            self._touch_expected_artifacts(workspace_root)
            work_result = self._work_result_done(evidence_paths=["tests/test_main.py"])
            with self.assertRaisesRegex(ContractValidationError, "declare at least one changed artifact"):
                validate_done_workspace_contract(
                    workspace_payload=self._workspace_payload(workspace_root),
                    artifact_manifest_payload={
                        "created": [],
                        "changed": [],
                        "moved": [],
                        "deleted": [],
                        "expected_artifacts": ["README.md", "src/main.py", "tests/test_main.py"],
                        "evidence_paths": ["tests/test_main.py"],
                    },
                    work_result=work_result,
                    artifact_exists=Path.exists,
                )


class TaskPackWorkReportTests(unittest.TestCase):
    def _task_pack_payload(self, workspace_root: Path, *, role: str = "morpheus") -> dict[str, object]:
        return {
            "project_id": "demo-project",
            "workspace_root": str(workspace_root),
            "task_id": "T001",
            "role": role,
            "goal": "Implement the first task.",
            "acceptance_criteria": ["Required files exist.", "Verification passes."],
            "allowed_write_paths": ["README.md", "src/main.py", "tests/test_main.py"],
            "expected_artifacts": ["README.md", "src/main.py", "tests/test_main.py"],
            "relevant_files": ["CURRENT_TASK.md"],
            "available_tools": ["shell", "write_file"],
            "recommended_verification": ["python3", "-m", "unittest", "tests/test_main.py"],
            "previous_failure": None,
            "repair_budget": 2,
            "report_destination": "covenant://work-report",
            "approved_runtime_evidence_roots": [],
        }

    def _verification_payload(self) -> dict[str, object]:
        return {
            "task_id": "T001",
            "agent": "morpheus",
            "timestamp": "2026-06-01T12:00:00Z",
            "performed": True,
            "command": ["python3", "-m", "unittest", "tests/test_main.py"],
            "status": "pass",
            "summary": "All tests passed.",
            "evidence_paths": ["tests/test_main.py"],
        }

    def _done_report_payload(self) -> dict[str, object]:
        return {
            "task_id": "T001",
            "agent": "morpheus",
            "status": "DONE",
            "summary": "Implementation complete.",
            "changed_files": ["README.md", "src/main.py", "tests/test_main.py"],
            "verification": self._verification_payload(),
            "repair_attempts": [],
            "next_owner": None,
            "blocker": None,
        }

    def _touch_expected_artifacts(self, workspace_root: Path) -> None:
        for relative in ("README.md", "src/main.py", "tests/test_main.py"):
            path = workspace_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("ok\n", encoding="utf-8")

    def test_task_pack_accepts_valid_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            task_pack = validate_task_pack(self._task_pack_payload(workspace_root))
            self.assertEqual(task_pack.task_id, "T001")
            self.assertEqual(task_pack.role, "morpheus")
            self.assertEqual(task_pack.report_destination, "covenant://work-report")
            self.assertEqual(task_pack.expected_artifacts, ["README.md", "src/main.py", "tests/test_main.py"])

    def test_task_pack_accepts_same_shape_for_core_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            for role in ("smith", "architect", "morpheus", "oracle"):
                payload = self._task_pack_payload(workspace_root, role=role)
                payload["allowed_write_paths"] = ["management/PLAN.md"]
                payload["expected_artifacts"] = ["management/PLAN.md"]
                task_pack = validate_task_pack(payload)
                self.assertEqual(task_pack.role, role)

    def test_task_pack_rejects_missing_report_destination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            payload = self._task_pack_payload(workspace_root)
            payload.pop("report_destination")
            with self.assertRaisesRegex(ContractValidationError, "report_destination"):
                validate_task_pack(payload)

    def test_task_pack_rejects_boolean_repair_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            payload = self._task_pack_payload(workspace_root)
            payload["repair_budget"] = True
            with self.assertRaisesRegex(ContractValidationError, "repair_budget"):
                validate_task_pack(payload)

    def test_work_report_accepts_done_with_existing_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            self._touch_expected_artifacts(workspace_root)
            task_pack = validate_task_pack(self._task_pack_payload(workspace_root))
            report = validate_work_report(self._done_report_payload(), task_pack=task_pack)
            self.assertEqual(report.status, "DONE")
            self.assertIsNotNone(report.verification)
            self.assertIsNotNone(report.artifact_manifest)

    def test_work_report_rejects_done_without_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            self._touch_expected_artifacts(workspace_root)
            task_pack = validate_task_pack(self._task_pack_payload(workspace_root))
            report_payload = self._done_report_payload()
            report_payload.pop("verification")
            with self.assertRaisesRegex(ContractValidationError, "verification"):
                validate_work_report(report_payload, task_pack=task_pack)

    def test_work_report_rejects_changed_file_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            self._touch_expected_artifacts(workspace_root)
            task_pack = validate_task_pack(self._task_pack_payload(workspace_root))
            report_payload = self._done_report_payload()
            report_payload["changed_files"] = ["../evil.py"]
            with self.assertRaisesRegex(ContractValidationError, "changed_files\\[0\\] contains invalid segment"):
                validate_work_report(report_payload, task_pack=task_pack)

    def test_work_report_rejects_changed_file_outside_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            self._touch_expected_artifacts(workspace_root)
            task_pack = validate_task_pack(self._task_pack_payload(workspace_root))
            report_payload = self._done_report_payload()
            report_payload["changed_files"] = ["docs/notes.md"]
            with self.assertRaisesRegex(ContractValidationError, "outside allowed_write_paths"):
                validate_work_report(report_payload, task_pack=task_pack)

    def test_work_report_rejects_missing_required_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            for relative in ("README.md", "src/main.py"):
                path = workspace_root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("ok\n", encoding="utf-8")
            task_pack = validate_task_pack(self._task_pack_payload(workspace_root))
            with self.assertRaisesRegex(ContractValidationError, "expected artifacts are missing"):
                validate_work_report(self._done_report_payload(), task_pack=task_pack)

    def test_work_report_accepts_blocked_with_actionable_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            task_pack = validate_task_pack(self._task_pack_payload(workspace_root))
            report = validate_work_report(
                {
                    "task_id": "T001",
                    "agent": "morpheus",
                    "status": "BLOCKED",
                    "summary": "Cannot continue.",
                    "changed_files": [],
                    "repair_attempts": [],
                    "next_owner": "niaobe",
                    "blocker": {
                        "reason": "Required dependency is unavailable.",
                        "next_action": "Provide the dependency or change the task.",
                    },
                },
                task_pack=task_pack,
            )
            self.assertEqual(report.status, "BLOCKED")
            self.assertEqual(report.blocker["next_action"], "Provide the dependency or change the task.")

    def test_work_report_rejects_blocked_without_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            task_pack = validate_task_pack(self._task_pack_payload(workspace_root))
            with self.assertRaisesRegex(ContractValidationError, "BLOCKED requires"):
                validate_work_report(
                    {
                        "task_id": "T001",
                        "agent": "morpheus",
                        "status": "BLOCKED",
                        "summary": "Cannot continue.",
                        "changed_files": [],
                        "repair_attempts": [],
                        "blocker": {"reason": "Missing dependency."},
                    },
                    task_pack=task_pack,
                )

    def test_work_report_accepts_needs_review_with_next_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "project"
            workspace_root.mkdir(parents=True, exist_ok=True)
            task_pack = validate_task_pack(self._task_pack_payload(workspace_root))
            report = validate_work_report(
                {
                    "task_id": "T001",
                    "agent": "morpheus",
                    "status": "NEEDS_REVIEW",
                    "summary": "Implementation needs a risk review.",
                    "changed_files": [],
                    "repair_attempts": [],
                    "next_owner": "oracle",
                    "blocker": {"reason": "Security-sensitive behavior changed."},
                },
                task_pack=task_pack,
            )
            self.assertEqual(report.status, "NEEDS_REVIEW")
            self.assertEqual(report.next_owner, "oracle")


if __name__ == "__main__":
    unittest.main()
