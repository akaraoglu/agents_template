from __future__ import annotations

import os
import signal
import stat
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from .canonical import canonical_sha256
from .evidence import EvidenceManager, _walk_workspace, evidence_is_fresh, workspace_manifest
from .models import (
    ActorRef,
    AssuranceDomain,
    AssuranceReport,
    Assignment,
    CandidateReport,
    ChangeSet,
    CriterionResult,
    EvidenceType,
    MachineVerificationSpec,
    ProjectManifest,
    RecordRef,
    ReviewDecision,
    RoleInstance,
    RunBinding,
    VerificationPlan,
    VerificationReceipt,
    VerificationRun,
    WorkItem,
    PipelineRevision,
    pipeline_stage_digest,
)
from .storage import V2ProjectStore


def _now() -> datetime:
    return datetime.now(timezone.utc)


def receipt_is_fresh(
    receipt: VerificationReceipt,
    candidate: CandidateReport,
    change_set: ChangeSet,
    workspace: ProjectManifest,
    plan: VerificationPlan | None = None,
) -> bool:
    return (
        receipt.candidate.digest == canonical_sha256(candidate)
        and receipt.candidate.record_id == candidate.candidate_report_id
        and receipt.change_set.digest == canonical_sha256(change_set)
        and receipt.change_set.record_id == change_set.change_set_id
        and receipt.workspace_digest == workspace.root_digest
        and change_set.final_manifest_digest == workspace.root_digest
        and (plan is None or (receipt.plan.digest == canonical_sha256(plan) and receipt.plan.record_id == plan.verification_plan_id))
    )


class VerificationExecutor:
    def __init__(self, store: V2ProjectStore) -> None:
        self.store = store
        self.evidence = EvidenceManager(store)

    @staticmethod
    def _relative_cwd(relative: str | None) -> str:
        if relative is None or relative == ".":
            return "."
        if relative.startswith("/") or "\\" in relative or any(part in {"", ".", ".."} for part in relative.split("/")):
            raise ValueError("verification cwd must be project-relative")
        return relative

    def _copy_snapshot(self, destination: Path) -> None:
        destination.mkdir(mode=0o700)
        root_fd = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            def copy(relative: str, source_fd: int, metadata: os.stat_result) -> None:
                parts = relative.split("/")
                parent_fd = os.dup(root_fd)
                try:
                    for part in parts[:-1]:
                        try:
                            os.mkdir(part, mode=0o700, dir_fd=parent_fd)
                        except FileExistsError:
                            pass
                        child_fd = os.open(
                            part,
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=parent_fd,
                        )
                        os.close(parent_fd)
                        parent_fd = child_fd
                    output_fd = os.open(
                        parts[-1],
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        metadata.st_mode & 0o777,
                        dir_fd=parent_fd,
                    )
                    try:
                        while chunk := os.read(source_fd, 1024 * 1024):
                            view = memoryview(chunk)
                            while view:
                                written = os.write(output_fd, view)
                                view = view[written:]
                        os.fchmod(output_fd, metadata.st_mode & 0o777)
                    finally:
                        os.close(output_fd)
                finally:
                    os.close(parent_fd)

            _walk_workspace(self.store.project, copy)
        finally:
            os.close(root_fd)

    @staticmethod
    def _trusted_bwrap() -> str:
        for candidate in ("/usr/bin/bwrap", "/bin/bwrap"):
            try:
                path = Path(candidate)
                metadata = path.stat(follow_symlinks=True)
                resolved = path.resolve(strict=True)
            except OSError:
                continue
            if (
                resolved.is_relative_to((Path("/usr/bin")))
                and stat.S_ISREG(metadata.st_mode)
                and metadata.st_uid == 0
                and not metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            ):
                return str(resolved)
        raise OSError("trusted bubblewrap executable is unavailable")

    @classmethod
    def _communicate(
        cls,
        command: Sequence[str],
        snapshot: Path,
        cwd: str,
        timeout: float,
    ) -> tuple[int, bytes, bytes]:
        sandbox_cwd = "/workspace" if cwd == "." else f"/workspace/{cwd}"
        executable = command[0]
        try:
            resolved_executable = Path(executable).resolve(strict=True) if Path(executable).is_absolute() else None
        except OSError:
            resolved_executable = None
        if resolved_executable is not None and resolved_executable.is_relative_to((Path("/usr"))):
            executable = str(resolved_executable)
        mounts = []
        for source in ("/usr", "/bin", "/lib", "/lib64"):
            try:
                metadata = os.stat(source)
            except FileNotFoundError:
                continue
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise OSError(f"verification runtime root is not trusted: {source}")
            mounts.extend(("--ro-bind", source, source))
        process = subprocess.Popen(
            (
                cls._trusted_bwrap(),
                "--die-with-parent",
                "--unshare-all",
                "--new-session",
                "--tmpfs",
                "/",
                *mounts,
                "--tmpfs",
                "/tmp",
                "--dir",
                "/tmp/home",
                "--bind",
                str(snapshot),
                "/workspace",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--chdir",
                sandbox_cwd,
                "--",
                executable,
                *command[1:],
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=True,
            env={
                "HOME": "/tmp/home",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "PATH": "/usr/bin:/bin",
                "PYTHONDONTWRITEBYTECODE": "1",
                "TMPDIR": "/tmp",
            },
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
            return process.returncode, stdout, stderr
        except subprocess.TimeoutExpired as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            drained_stdout, drained_stderr = process.communicate()
            process.wait()
            return 124, drained_stdout, drained_stderr + f"\ncommand timed out after {timeout:g}s\n".encode()
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            process.wait()
            raise

    def execute(
        self,
        plan: VerificationPlan,
        candidate: CandidateReport,
        change_set: ChangeSet,
        *,
        issued_by: ActorRef,
        producer_role_instance_id: str | None = None,
        criterion_commands: Mapping[str, Sequence[int]],
        timeout_seconds: float = 60.0,
        cwd: str | None = None,
        workspace: ProjectManifest | None = None,
        issued_at: datetime | None = None,
        recorded_at: datetime | None = None,
    ) -> VerificationReceipt:
        if timeout_seconds <= 0:
            raise ValueError("verification timeout must be positive")
        criterion_ids = tuple(item.criterion_id for item in plan.criteria)
        if set(criterion_commands) != set(criterion_ids):
            raise ValueError("criterion_commands must explicitly map every and only plan criterion")
        for criterion_id, indexes in criterion_commands.items():
            if len(indexes) != len(set(indexes)) or any(type(index) is not int or index < 0 or index >= len(plan.commands) for index in indexes):
                raise ValueError(f"invalid command mapping for criterion {criterion_id!r}")
        current = workspace_manifest(self.store.project)
        if workspace is not None and workspace.root_digest != current.root_digest:
            raise ValueError("supplied workspace manifest is stale")
        if candidate.change_set is None:
            raise ValueError("verification requires a writing-stage candidate")
        if change_set.final_manifest_digest != current.root_digest:
            raise ValueError("cumulative ChangeSet is stale for the current workspace")
        work_item = cast(WorkItem, self.store.resolve(candidate.work_item))
        if plan.work_item != candidate.work_item:
            raise ValueError("verification plan work_item does not match the candidate")
        criteria = {item.id: item for item in work_item.acceptance_criteria}
        planned = {item.criterion_id: item for item in plan.criteria}
        if set(planned) != set(criteria):
            raise ValueError("verification plan criteria must exactly cover the WorkItem")
        for criterion_id, criterion in criteria.items():
            if (
                planned[criterion_id].statement != criterion.statement
                or set(planned[criterion_id].required_evidence_types) != set(criterion.required_evidence_types)
                or planned[criterion_id].verification != criterion.verification
            ):
                raise ValueError("verification plan criterion does not match the WorkItem")
        for criterion_id, criterion in criteria.items():
            verifier_command = cast(
                MachineVerificationSpec, criterion.verification
            ).verifier_argv
            mapped_commands = tuple(
                plan.commands[index] for index in criterion_commands[criterion_id]
            )
            if verifier_command not in mapped_commands:
                raise ValueError(
                    f"criterion {criterion_id!r} does not execute its declared verifier command"
                )
        producer = cast(RoleInstance, self.store.resolve(candidate.role_instance))
        producer_id = producer.role_instance_id
        if producer_role_instance_id is not None and producer_role_instance_id != producer_id:
            raise ValueError("caller producer identity does not match the resolved candidate producer")
        if issued_by.kind != "agent" or issued_by.role_instance_id is None:
            raise ValueError("verification issuer must be an agent role")
        verifier = cast(RoleInstance, self.store.read_record("role_instance", issued_by.role_instance_id))
        verifier_assignment = cast(Assignment, self.store.resolve(verifier.assignment))
        revision = cast(PipelineRevision, self.store.resolve(candidate.pipeline_revision))
        verifier_stage = next((item for item in revision.stages if item.stage_id == verifier.stage_id), None)
        if (
            verifier_assignment.stage != "verification"
            or verifier_assignment.work_item != candidate.work_item
            or verifier.pipeline_revision != candidate.pipeline_revision
            or verifier_stage is None
            or verifier_stage.stage != "verification"
            or verifier.stage_spec_digest != pipeline_stage_digest(verifier_stage)
            or verifier.role_instance_id == producer_id
        ):
            raise ValueError("verification issuer must be an independent verifier-stage role for the candidate revision")
        plan_ref = self.store.write_immutable(plan, plan.verification_plan_id)
        candidate_ref = self.store.write_immutable(candidate, candidate.candidate_report_id)
        change_ref = self.store.write_immutable(change_set, change_set.change_set_id)
        command_results: list[VerificationRun] = []
        command_refs: list[RecordRef] = []
        relative_cwd = self._relative_cwd(cwd)
        with tempfile.TemporaryDirectory(prefix="codexteam-v2-verify-") as temporary:
            snapshot = Path(temporary) / "workspace"
            self._copy_snapshot(snapshot)
            if not (snapshot if relative_cwd == "." else snapshot / relative_cwd).is_dir():
                raise ValueError("verification cwd must be an existing project directory")
            if workspace_manifest(snapshot).root_digest != current.root_digest:
                raise ValueError("verification snapshot digest does not match its source")
            for index, command in enumerate(plan.commands):
                if not command:
                    raise ValueError("verification commands must be nonempty argv arrays")
                started_at = recorded_at or _now()
                started = time.monotonic()
                try:
                    exit_code, stdout, stderr = self._communicate(command, snapshot, relative_cwd, timeout_seconds)
                except OSError as exc:
                    exit_code = 127
                    stdout = b""
                    stderr = f"unable to execute command: {exc}\n".encode()
                expected_stdout = next(
                    (
                        item.verification.expected_stdout.encode()
                        for item in plan.criteria
                        if item.verification is not None and tuple(item.verification.verifier_argv) == tuple(command)
                    ),
                    None,
                )
                if exit_code == 0 and expected_stdout is not None and stdout != expected_stdout:
                    exit_code = 1
                    stderr += b"verification stdout did not match the criterion contract\n"
                finished_at = recorded_at or _now()
                duration = 0.0 if recorded_at is not None else max(0.0, time.monotonic() - started)
                identity = canonical_sha256(
                    {
                        "candidate": candidate_ref,
                        "command": command,
                        "index": index,
                        "plan": plan_ref,
                        "started_at": started_at,
                        "workspace_digest": current.root_digest,
                    }
                )
                stdout_artifact, stdout_ref = self.evidence.write_artifact(
                    stdout,
                    EvidenceType.TEST_OUTPUT,
                    issued_by,
                    created_at=finished_at,
                    evidence_id=f"verification-{identity}-stdout",
                )
                stderr_artifact, stderr_ref = self.evidence.write_artifact(
                    stderr,
                    EvidenceType.TEST_OUTPUT,
                    issued_by,
                    created_at=finished_at,
                    evidence_id=f"verification-{identity}-stderr",
                )
                del stdout_artifact, stderr_artifact
                run = VerificationRun(
                    schema_version="2.0",
                    kind="verification_run",
                    verification_run_id=f"verification-run-{identity}",
                    plan=plan_ref,
                    candidate=candidate_ref,
                    change_set=change_ref,
                    workspace_digest=current.root_digest,
                    command=tuple(command),
                    exit_code=exit_code,
                    duration_seconds=duration,
                    evidence=(stdout_ref, stderr_ref),
                    started_at=started_at,
                    finished_at=finished_at,
                )
                command_results.append(run)
                command_refs.append(self.store.write_immutable(run, run.verification_run_id))
        final_workspace = workspace_manifest(self.store.project)
        if final_workspace.root_digest != current.root_digest:
            raise ValueError("verification commands changed the workspace")
        results: list[CriterionResult] = []
        for criterion_id in criterion_ids:
            indexes = tuple(criterion_commands[criterion_id])
            evidence = tuple(reference for index in indexes for reference in command_results[index].evidence)
            if not indexes:
                disposition = "not_run"
            elif all(command_results[index].exit_code == 0 for index in indexes) and set(
                planned[criterion_id].required_evidence_types
            ) <= {EvidenceType.TEST_OUTPUT}:
                disposition = "pass"
            else:
                disposition = "fail"
            results.append(
                CriterionResult(
                    criterion_id=criterion_id,
                    command_indexes=indexes,
                    disposition=disposition,
                    evidence=evidence,
                )
            )
        bindings = tuple(
            RunBinding(
                run=reference,
                plan=plan_ref,
                candidate=candidate_ref,
                change_set=change_ref,
                workspace_digest=current.root_digest,
            )
            for reference in command_refs
        )
        if not bindings:
            raise ValueError("verification plan must contain at least one command")
        accepted = all(result.disposition == "pass" for result in results)
        receipt_identity = canonical_sha256(
            {
                "candidate": candidate_ref,
                "change_set": change_ref,
                "criterion_results": results,
                "plan": plan_ref,
                "run_bindings": bindings,
                "workspace_digest": current.root_digest,
            }
        )
        receipt = VerificationReceipt(
            schema_version="2.0",
            kind="verification_receipt",
            verification_receipt_id=f"verification-receipt-{receipt_identity}",
            plan=plan_ref,
            candidate=candidate_ref,
            change_set=change_ref,
            workspace_digest=current.root_digest,
            run_bindings=bindings,
            criterion_ids=criterion_ids,
            criterion_results=tuple(results),
            accepted=accepted,
            producer_role_instance_id=producer_id,
            issued_by=issued_by,
            issued_at=issued_at or _now(),
        )
        self.store.write_immutable(receipt, receipt.verification_receipt_id)
        return receipt

    run = execute


def validate_assurance_report(
    report: AssuranceReport,
    candidate: CandidateReport,
    required_domains: Sequence[AssuranceDomain],
) -> None:
    if report.candidate.record_id != candidate.candidate_report_id or report.candidate.digest != canonical_sha256(candidate):
        raise ValueError("assurance report is not bound to the candidate")
    expected = set(required_domains)
    actual = {item.domain for item in report.dispositions}
    if actual != expected:
        raise ValueError("assurance report must exactly cover the selected domains")
    if any(item.disposition != "pass" for item in report.dispositions):
        raise ValueError("all selected assurance domains must pass")
    if any(finding.unresolved_blocking for item in report.dispositions for finding in item.findings):
        raise ValueError("assurance report contains unresolved blocking findings")


def validate_review_decision(
    review: ReviewDecision,
    candidate: CandidateReport,
    receipts: Sequence[VerificationReceipt],
    assurance: AssuranceReport,
    required_domains: Sequence[AssuranceDomain],
    workspace: ProjectManifest,
    change_set: ChangeSet,
) -> None:
    candidate_digest = canonical_sha256(candidate)
    if review.candidate.record_id != candidate.candidate_report_id or review.candidate.digest != candidate_digest:
        raise ValueError("review decision is not bound to the candidate")
    if review.decision != "ACCEPT":
        raise ValueError("candidate review must ACCEPT")
    if any(finding.unresolved_blocking for finding in review.findings):
        raise ValueError("accepted review contains unresolved blocking findings")
    validate_assurance_report(assurance, candidate, required_domains)
    expected_receipts = {item.record_id: item.digest for item in review.verification_receipts}
    supplied_receipts = {
        item.verification_receipt_id: canonical_sha256(item) for item in receipts if item.accepted
    }
    if (
        not expected_receipts
        or len(expected_receipts) != len(review.verification_receipts)
        or len(supplied_receipts) != len(receipts)
        or expected_receipts != supplied_receipts
    ):
        raise ValueError("review must reference exactly the supplied accepted verification receipts")
    if any(not receipt_is_fresh(item, candidate, change_set, workspace) for item in receipts):
        raise ValueError("review references a stale verification receipt")
    assurance_ref = RecordRef(
        record_id=assurance.assurance_report_id,
        kind="assurance_report",
        digest=canonical_sha256(assurance),
    )
    if assurance_ref not in review.evidence:
        raise ValueError("review evidence must include the accepted assurance report")


__all__ = [
    "VerificationExecutor",
    "receipt_is_fresh",
    "validate_assurance_report",
    "validate_review_decision",
]
