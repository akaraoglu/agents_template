from __future__ import annotations

from datetime import datetime, timezone
import os

import pytest

import sys
import time

from codexteam_tools.v2 import (
    AcceptanceCriterion,
    ActorRef,
    Assignment,
    CandidateReport,
    ChangeSet,
    CriterionDisposition,
    EvidenceType,
    EvidenceManager,
    LeadDecision,
    MachineVerificationSpec,
    PipelineRevision,
    RecordRef,
    VerificationCriterion,
    VerificationExecutor,
    VerificationPlan,
    V2ProjectStore,
    WorkItem,
    build_role_instance,
    canonical_sha256,
    derive_change_set,
    compile_pipeline,
    compose_change_sets,
    load_catalog,
    pipeline_stage_digest,
    workspace_manifest,
    validate_change_attribution,
)


NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)


def test_manifest_change_set_tracks_preexisting_baseline(tmp_path) -> None:
    (tmp_path / "dirty.txt").write_text("already dirty", encoding="utf-8")
    base = workspace_manifest(tmp_path, created_at=NOW)
    (tmp_path / "dirty.txt").write_text("candidate edit", encoding="utf-8")
    (tmp_path / "new.txt").write_text("new", encoding="utf-8")
    final = workspace_manifest(tmp_path, created_at=NOW)
    changed = derive_change_set(base, final, created_at=NOW)
    assert [(entry.path, entry.action) for entry in changed.entries] == [("dirty.txt", "modify"), ("new.txt", "create")]


def test_writing_stage_change_sets_compose_without_hidden_changes(tmp_path) -> None:
    base = workspace_manifest(tmp_path, created_at=NOW)
    (tmp_path / "architecture.md").write_text("architecture", encoding="utf-8")
    architecture_manifest = workspace_manifest(tmp_path, created_at=NOW)
    architecture = derive_change_set(base, architecture_manifest, created_at=NOW)
    (tmp_path / "ux.md").write_text("ux", encoding="utf-8")
    ux_manifest = workspace_manifest(tmp_path, created_at=NOW)
    ux = derive_change_set(architecture_manifest, ux_manifest, created_at=NOW)
    cumulative = derive_change_set(base, ux_manifest, created_at=NOW)
    assert compose_change_sets(base, [architecture, ux]).entries == cumulative.entries
    validate_change_attribution(base, cumulative, [architecture, ux])
    hidden = derive_change_set(base, architecture_manifest, created_at=NOW)
    with pytest.raises(ValueError, match="unattributed"):
        validate_change_attribution(base, hidden, [architecture, ux])


def test_manifest_and_change_ids_include_timestamp_and_idempotency_namespace(tmp_path) -> None:
    (tmp_path / "source.txt").write_text("one", encoding="utf-8")
    first = workspace_manifest(tmp_path, created_at=NOW)
    same = workspace_manifest(tmp_path, created_at=NOW)
    later = workspace_manifest(tmp_path, created_at=NOW.replace(second=1))
    assert first == same
    assert first.manifest_id != later.manifest_id
    assert derive_change_set(first, first, created_at=NOW).change_set_id != derive_change_set(
        first, first, created_at=NOW.replace(second=1)
    ).change_set_id
    store = V2ProjectStore(tmp_path)
    store.write_immutable(first, "capture-1")
    assert (store.root / "records/_idempotency/project_manifest/capture-1.json").is_file()
    assert not (store.root / "records/project_manifest/idempotency-capture-1.json").exists()


def test_manifest_excludes_kernel_metadata_and_rejects_symlinks(tmp_path) -> None:
    runtime = tmp_path / ".codexteam/v2/runtime"
    runtime.mkdir(parents=True)
    (runtime / "lock").write_text("metadata", encoding="utf-8")
    (tmp_path / "source.txt").write_text("source", encoding="utf-8")
    assert tuple(item.path for item in workspace_manifest(tmp_path, created_at=NOW).entries) == ("source.txt",)
    (tmp_path / "link").symlink_to(tmp_path / "source.txt")
    with pytest.raises(ValueError, match="symlinks"):
        workspace_manifest(tmp_path, created_at=NOW)


def test_manifest_and_snapshot_fail_closed_on_directory_replacement(tmp_path, monkeypatch) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside", encoding="utf-8")
    original_open = os.open

    def race(project):
        source = project / "source"
        swapped = False

        def replace_directory(path, flags, mode=0o777, *, dir_fd=None):
            nonlocal swapped
            if path == "source" and dir_fd is not None and not swapped:
                swapped = True
                source.rename(project / "source-original")
                source.symlink_to(outside, target_is_directory=True)
            return original_open(path, flags, mode, dir_fd=dir_fd)

        return replace_directory

    project = tmp_path / "manifest-project"
    (project / "source").mkdir(parents=True)
    (project / "source/inside.txt").write_text("inside", encoding="utf-8")
    monkeypatch.setattr(os, "open", race(project))
    with pytest.raises(ValueError, match="opened safely|changed during traversal"):
        workspace_manifest(project, created_at=NOW)

    monkeypatch.setattr(os, "open", original_open)
    snapshot_project = tmp_path / "snapshot-project"
    (snapshot_project / "source").mkdir(parents=True)
    (snapshot_project / "source/inside.txt").write_text("inside", encoding="utf-8")
    executor = VerificationExecutor(V2ProjectStore(snapshot_project))
    destination = tmp_path / "snapshot"
    monkeypatch.setattr(os, "open", race(snapshot_project))
    with pytest.raises(ValueError, match="opened safely|changed during traversal"):
        executor._copy_snapshot(destination)
    assert not (destination / "source/secret.txt").exists()


def verification_fixture(tmp_path, commands, *, expected_stdout=""):
    (tmp_path / "source.txt").write_text("candidate", encoding="utf-8")
    store = V2ProjectStore(tmp_path)
    catalog = load_catalog("v2")
    lead = ActorRef(actor_id="lead", kind="project_lead")
    work = WorkItem(
        schema_version="2.0",
        kind="work_item",
        work_item_id="work-1",
        title="Verify",
        objective="Exercise isolated verification",
        acceptance_criteria=(
            AcceptanceCriterion(
                id="criterion",
                statement="Pass",
                required_evidence_types=(EvidenceType.TEST_OUTPUT,),
                verification=MachineVerificationSpec(
                    verifier_argv=commands[0],
                    argv=commands[0],
                    expected_stdout=expected_stdout,
                ),
            ),
        ),
        approved_scope=("project/**",),
    )
    compiled = compile_pipeline(catalog, work, (), lead, NOW)
    plan_decision = LeadDecision(
        schema_version="2.0",
        kind="lead_decision",
        decision_id="plan-decision",
        decision="approve",
        subject=compiled.refs.plan,
        rationale="Approve",
        decided_by=lead,
        decided_at=NOW,
    )
    decision_ref = store.write_immutable(plan_decision, plan_decision.decision_id)
    store.write_immutable(work, work.work_item_id)
    store.write_immutable(compiled.plan, compiled.plan.plan_id)
    revision = PipelineRevision(
        schema_version="2.0",
        kind="pipeline_revision",
        revision_id="revision-1",
        plan=compiled.refs.plan,
        revision_number=1,
        stages=compiled.plan.stages,
        frozen_stage_ids=(),
        frozen_stage_digests=(),
        parent_stage_digests=(),
        applies_from_stage=compiled.plan.stages[0].stage_id,
        reason="Initial",
        approving_decision=decision_ref,
        created_at=NOW,
    )
    revision_ref = store.write_immutable(revision, revision.revision_id)
    roles = {}
    for stage_name in ("implementation", "verification"):
        stage = next(item for item in revision.stages if item.stage == stage_name)
        assignment = Assignment(
            schema_version="2.0",
            kind="assignment",
            assignment_id=f"assignment-{stage_name}",
            work_item=compiled.refs.work_item,
            stage=stage.stage,
            agent_spec=stage.agent_spec,
            scope=("project/**",),
        )
        store.write_immutable(assignment, assignment.assignment_id)
        role = build_role_instance(
            catalog,
            assignment=assignment,
            work_item=work,
            pipeline_revision=revision,
            stage_spec=stage,
            attempt_id=f"attempt-{stage_name}",
        )
        store.write_immutable(role, role.role_instance_id)
        roles[stage_name] = (assignment, role)
    base = workspace_manifest(tmp_path, created_at=NOW)
    change = derive_change_set(base, base, created_at=NOW)
    change_ref = store.write_immutable(change, change.change_set_id)
    evidence = RecordRef(record_id="candidate-evidence", kind="evidence_artifact", digest="a" * 64)
    candidate = CandidateReport(
        schema_version="2.0",
        kind="candidate_report",
        candidate_report_id="candidate-1",
        work_item=compiled.refs.work_item,
        pipeline_revision=revision_ref,
        assignment=store.reference(roles["implementation"][0]),
        role_instance=store.reference(roles["implementation"][1]),
        stage="implementation",
        stage_id="implementation",
        stage_spec_digest=pipeline_stage_digest(next(item for item in revision.stages if item.stage == "implementation")),
        attempt_id=roles["implementation"][1].attempt_id,
        context_pack=RecordRef(record_id="context-1", kind="context_pack", digest="b" * 64),
        change_set=change_ref,
        outcome="succeeded",
        criterion_ids=("criterion",),
        criterion_dispositions=(CriterionDisposition(criterion_id="criterion", disposition="claimed_satisfied", evidence=(evidence,), evidence_types=(EvidenceType.TEST_OUTPUT,)),),
        evidence=(evidence,),
        produced_at=NOW,
    )
    plan = VerificationPlan(
        schema_version="2.0",
        kind="verification_plan",
        verification_plan_id="verification-plan-1",
        work_item=candidate.work_item,
        criteria=(VerificationCriterion(
            criterion_id="criterion",
            statement="Pass",
            required_evidence_types=(EvidenceType.TEST_OUTPUT,),
            verification=MachineVerificationSpec(
                verifier_argv=commands[0],
                argv=commands[0],
                expected_stdout=expected_stdout,
            ),
        ),),
        commands=commands,
        created_at=NOW,
    )
    store.write_immutable(candidate, candidate.candidate_report_id)
    verifier = ActorRef(
        actor_id="verifier",
        kind="agent",
        role_instance_id=roles["verification"][1].role_instance_id,
    )
    return VerificationExecutor(store), plan, candidate, change, verifier


def test_verification_argv_success_failure_timeout_and_no_shell(tmp_path) -> None:
    commands = (
        (sys.executable, "-c", "print('ok')"),
        (sys.executable, "-c", "raise SystemExit(3)"),
    )
    executor, plan, candidate, change, verifier = verification_fixture(
        tmp_path, commands, expected_stdout="ok\n"
    )
    receipt = executor.execute(
        plan,
        candidate,
        change,
        issued_by=verifier,
        producer_role_instance_id=candidate.role_instance.record_id,
        criterion_commands={"criterion": (0, 1)},
    )
    assert not receipt.accepted
    assert [executor.store.resolve(binding.run).exit_code for binding in receipt.run_bindings] == [0, 3]

    other = tmp_path / "timeout"
    other.mkdir()
    executor, plan, candidate, change, verifier = verification_fixture(
        other, ((sys.executable, "-c", "import time; time.sleep(1)"),)
    )
    receipt = executor.execute(
        plan,
        candidate,
        change,
        issued_by=verifier,
        producer_role_instance_id=candidate.role_instance.record_id,
        criterion_commands={"criterion": (0,)},
        timeout_seconds=0.05,
    )
    assert executor.store.resolve(receipt.run_bindings[0].run).exit_code == 124

    no_shell = tmp_path / "no-shell"
    no_shell.mkdir()
    executor, plan, candidate, change, verifier = verification_fixture(
        no_shell,
        ((sys.executable, "-c", "import sys; print(sys.argv[1])", "$(touch injected)"),),
    )
    executor.execute(
        plan,
        candidate,
        change,
        issued_by=verifier,
        producer_role_instance_id=candidate.role_instance.record_id,
        criterion_commands={"criterion": (0,)},
    )
    assert not (no_shell / "injected").exists()


def test_verification_isolates_modify_restore_and_kills_descendants(tmp_path) -> None:
    command = (
        sys.executable,
        "-c",
        "from pathlib import Path; p=Path('source.txt'); old=p.read_text(); p.write_text('mutated'); p.write_text(old)",
    )
    executor, plan, candidate, change, verifier = verification_fixture(tmp_path, (command,))
    receipt = executor.execute(
        plan,
        candidate,
        change,
        issued_by=verifier,
        criterion_commands={"criterion": (0,)},
    )
    assert receipt.accepted
    assert (tmp_path / "source.txt").read_text(encoding="utf-8") == "candidate"

    marker = tmp_path / "detached-marker"
    child = (
        sys.executable,
        "-c",
        "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',\"import time; from pathlib import Path; time.sleep(.2); Path('detached-marker').write_text('bad')\"], start_new_session=True); time.sleep(5)",
    )
    child_root = tmp_path / "child"
    child_root.mkdir()
    marker = child_root / "detached-marker"
    executor, plan, candidate, change, verifier = verification_fixture(child_root, (child,))
    executor.execute(
        plan,
        candidate,
        change,
        issued_by=verifier,
        criterion_commands={"criterion": (0,)},
        timeout_seconds=0.05,
    )
    time.sleep(0.3)
    assert not marker.exists()


def test_verification_rejects_stale_candidate_workspace(tmp_path) -> None:
    executor, plan, candidate, change, verifier = verification_fixture(
        tmp_path, ((sys.executable, "-c", "print('ok')"),)
    )
    (tmp_path / "source.txt").write_text("mutated", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        executor.execute(
            plan,
            candidate,
            change,
            issued_by=verifier,
            producer_role_instance_id=candidate.role_instance.record_id,
            criterion_commands={"criterion": (0,)},
        )


def test_evidence_resolution_rejects_tampered_and_missing_blobs(tmp_path) -> None:
    store = V2ProjectStore(tmp_path)
    manager = EvidenceManager(store)
    _, reference = manager.write_artifact(b"original", EvidenceType.TEST_OUTPUT, ActorRef(actor_id="lead", kind="project_lead"), created_at=NOW)
    blob = store.root / "evidence" / f"{reference.record_id}.bin"
    blob.write_bytes(b"tampered")
    with pytest.raises(Exception, match="integrity mismatch"):
        manager.resolve_artifact(reference)
    blob.unlink()
    with pytest.raises(Exception, match="missing evidence blob"):
        manager.resolve_artifact(reference)


def test_verification_hides_host_secrets_and_ignores_path_bwrap(tmp_path, monkeypatch) -> None:
    secret = tmp_path.parent / "host-secret"
    secret.write_text("do-not-expose", encoding="utf-8")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_bwrap = fake_bin / "bwrap"
    fake_bwrap.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_bwrap.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin))
    command = (
        sys.executable,
        "-c",
        f"from pathlib import Path; raise SystemExit(0 if not Path({str(secret)!r}).exists() else 9)",
    )
    executor, plan, candidate, change, verifier = verification_fixture(tmp_path, (command,))
    receipt = executor.execute(
        plan,
        candidate,
        change,
        issued_by=verifier,
        criterion_commands={"criterion": (0,)},
    )
    assert receipt.accepted


def test_verification_api_rejects_caller_host_mounts(tmp_path) -> None:
    executor, plan, candidate, change, verifier = verification_fixture(
        tmp_path, ((sys.executable, "-c", "raise SystemExit(0)"),)
    )
    with pytest.raises(TypeError, match="tool_roots"):
        executor.execute(
            plan,
            candidate,
            change,
            issued_by=verifier,
            criterion_commands={"criterion": (0,)},
            tool_roots=("/etc",),
        )


def test_verification_rejects_untrusted_bwrap(tmp_path, monkeypatch) -> None:
    executor, plan, candidate, change, verifier = verification_fixture(
        tmp_path, ((sys.executable, "-c", "raise SystemExit(0)"),)
    )

    def unavailable() -> str:
        raise OSError("untrusted bwrap")

    monkeypatch.setattr(type(executor), "_trusted_bwrap", staticmethod(unavailable))
    receipt = executor.execute(
        plan,
        candidate,
        change,
        issued_by=verifier,
        criterion_commands={"criterion": (0,)},
    )
    assert not receipt.accepted
    assert executor.store.resolve(receipt.run_bindings[0].run).exit_code == 127
