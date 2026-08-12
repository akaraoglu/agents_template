from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from codexteam_tools.v2 import (
    AcceptanceCriterion,
    ActorRef,
    CorruptStore,
    EvidenceType,
    LeadDecision,
    PipelineRuntime,
    RevisionConflict,
    V2ProjectStore,
    WorkItem,
    Mailbox,
    MailboxMessage,
    workspace_manifest,
    stage_revision_is_valid,
    PipelineRevision,
    FrozenStageDigest,
    ParentStageDigest,
    pipeline_stage_digest,
    compile_pipeline,
    load_catalog,
)


NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)


def lead() -> ActorRef:
    return ActorRef(actor_id="lead", kind="project_lead")


def item() -> WorkItem:
    return WorkItem(
        schema_version="2.0",
        kind="work_item",
        work_item_id="work-1",
        title="Canary",
        objective="Test runtime",
        acceptance_criteria=(AcceptanceCriterion(id="criterion", statement="Pass", required_evidence_types=(EvidenceType.TEST_OUTPUT,)),),
        approved_scope=("src/**",),
    )


def decision(subject) -> LeadDecision:
    return LeadDecision(
        schema_version="2.0",
        kind="lead_decision",
        decision_id="decision-1",
        decision="approve",
        subject=subject,
        rationale="Approved",
        decided_by=lead(),
        decided_at=NOW,
    )


def test_event_replay_cas_truncated_tail_and_corruption(tmp_path) -> None:
    store = V2ProjectStore(tmp_path)
    first = store.append_event("run", {"type": "one"}, expected_version=0)
    assert store.append_event("run", {"type": "two"}, expected_version=1).previous_event_digest == first.digest
    assert store.append_event("run", {"type": "two"}, expected_version=1).sequence == 2
    assert len(store.replay_events("run")) == 2
    with pytest.raises(RevisionConflict):
        store.append_event("run", {"type": "stale"}, expected_version=0)
    state = store.replace_state("run", {"status": "one"}, expected_revision=0)
    assert store.replace_state("run", {"status": "one"}, expected_revision=0) == state
    assert store.replace_state("run", {"status": "two"}, expected_revision=1, expected_digest=state.digest).revision == 2
    with pytest.raises(RevisionConflict):
        store.replace_state("run", {}, expected_revision=1)
    event_path = store.root / "events/run.jsonl"
    with event_path.open("ab") as stream:
        stream.write(b'{"incomplete":')
    assert len(store.replay_events("run")) == 2
    with event_path.open("ab") as stream:
        stream.write(b'not-json\n')
    with pytest.raises(CorruptStore):
        store.replay_events("run")


def test_pipeline_initialization_replay_revision_conflict_and_impossible_transition(tmp_path) -> None:
    catalog = load_catalog("v2")
    compiled = compile_pipeline(catalog, item(), (), lead(), NOW)
    runtime = PipelineRuntime(V2ProjectStore(tmp_path), catalog=catalog)
    projected = runtime.initialize("run-1", compiled.plan, decision(compiled.refs.plan), created_at=NOW)
    assert projected.state_revision == 1
    assert projected.stages[0].status == "ready"
    assert runtime.replay("run-1") == projected
    with pytest.raises(ValueError, match="impossible"):
        runtime.succeed("run-1", projected.stages[0].stage_id, expected_state_revision=1)
    with pytest.raises(RevisionConflict):
        runtime.block("run-1", projected.stages[0].stage_id, expected_state_revision=0, detail="stale")


def test_change_request_requires_stored_request_decision_subject_and_current_work_item(tmp_path) -> None:
    catalog = load_catalog("v2")
    store = V2ProjectStore(tmp_path)
    compiled = compile_pipeline(catalog, item(), (), lead(), NOW)
    runtime = PipelineRuntime(store, catalog=catalog)
    projected = runtime.initialize("run-change", compiled.plan, decision(compiled.refs.plan), created_at=NOW)
    store.write_immutable(item(), item().work_item_id)
    worker = ActorRef(actor_id="worker", kind="agent", role_instance_id="role-worker")
    orchestrator = ActorRef(actor_id="orchestrator", kind="orchestrator")
    request = MailboxMessage(
        schema_version="2.0",
        kind="mailbox_message",
        message_id="change-request",
        sender=worker,
        recipient=orchestrator,
        correlation_id="change",
        idempotency_key="change-request",
        created_at=NOW,
        body={
            "kind": "pipeline_change_request", "requested_stages": (), "rationale": "Keep required stages",
            "discovery_candidate": {
                "record_id": "candidate-discovery", "kind": "candidate_report", "digest": "a" * 64,
            },
        },
    )
    request_ref = Mailbox(store).submit(request, worker, submitted_at=NOW).message
    unrelated = decision(compiled.refs.plan).model_copy(update={"decision_id": "unrelated"})
    with pytest.raises(ValueError, match="approving LeadDecision"):
        runtime.approve_change_request(
            "run-change", request_ref, unrelated, expected_state_revision=projected.state_revision, created_at=NOW
        )
    approval = decision(request_ref).model_copy(update={"decision_id": "approve-request"})
    different = item().model_copy(update={"work_item_id": "different"})
    with pytest.raises(ValueError, match="caller WorkItem"):
        runtime.approve_change_request(
            "run-change",
            request_ref,
            approval,
            different,
            expected_state_revision=projected.state_revision,
            created_at=NOW,
        )
    with pytest.raises(FileNotFoundError):
        runtime.approve_change_request(
            "run-change",
            request_ref,
            approval,
            item(),
            expected_state_revision=projected.state_revision,
            created_at=NOW,
        )


def test_store_rejects_symlink_ancestor_and_root_replacement(tmp_path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink ancestors"):
        V2ProjectStore(linked)
    project = tmp_path / "project"
    store = V2ProjectStore(project)
    moved = tmp_path / "moved"
    project.rename(moved)
    project.mkdir()
    with pytest.raises(CorruptStore, match="identity changed"):
        store.replay_events("run")


def test_pipeline_initialization_recovers_journaled_timestamp_after_append_failure(tmp_path, monkeypatch) -> None:
    catalog = load_catalog("v2")
    compiled = compile_pipeline(catalog, item(), (), lead(), NOW)
    store = V2ProjectStore(tmp_path)
    runtime = PipelineRuntime(store, catalog=catalog)
    original_append = store.append_event
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("injected append failure")
        return original_append(*args, **kwargs)

    monkeypatch.setattr(store, "append_event", fail_once)
    with pytest.raises(OSError, match="injected"):
        runtime.initialize("recover-run", compiled.plan, decision(compiled.refs.plan))
    journaled = store.journaled_record("pipeline-initialize-recover-run", "pipeline_revision", "recover-run-revision-1")
    assert journaled is not None
    monkeypatch.setattr(store, "append_event", original_append)
    projection = runtime.initialize("recover-run", compiled.plan, decision(compiled.refs.plan))
    assert projection.state_revision == 1
    assert store.resolve(projection.pipeline_revision) == journaled


def test_strict_journal_conflicts_after_interleaving_and_records_does_not_deadlock(tmp_path, monkeypatch) -> None:
    store = V2ProjectStore(tmp_path, lock_timeout=0.1)
    manifest = workspace_manifest(tmp_path, created_at=NOW)
    store.commit_records_event(
        "records-operation",
        ((manifest, manifest.manifest_id),),
        "records",
        {"type": "stored"},
        expected_version=0,
    )
    original = store.append_event

    def fail_strict(*args, **kwargs):
        raise OSError("strict append failed")

    monkeypatch.setattr(store, "append_event", fail_strict)
    with pytest.raises(OSError, match="strict append failed"):
        store.commit_records_event(
            "strict-operation",
            (),
            "pipeline",
            {"type": "strict"},
            expected_version=0,
        )
    monkeypatch.setattr(store, "append_event", original)
    store.append_event("pipeline", {"type": "other"}, expected_version=0)
    with pytest.raises(RevisionConflict):
        store.commit_records_event(
            "strict-operation",
            (),
            "pipeline",
            {"type": "strict"},
            expected_version=0,
        )


def test_safe_store_traversal_fails_closed_on_ancestor_swap(tmp_path, monkeypatch) -> None:
    store = V2ProjectStore(tmp_path)
    manifest = workspace_manifest(tmp_path, created_at=NOW)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    sentinel = outside / f"{manifest.manifest_id}.json"
    sentinel.write_text("external", encoding="utf-8")
    original_open = os.open
    swapped = False

    def swap_before_records(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if path == "records" and dir_fd is not None and not swapped:
            swapped = True
            records = store.root / "records"
            moved = store.root / "records-original"
            records.rename(moved)
            records.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swap_before_records)
    with pytest.raises(Exception, match="opened safely"):
        store.write_immutable(manifest, manifest.manifest_id)
    assert sentinel.read_text(encoding="utf-8") == "external"


def test_stage_baseline_retry_returns_exact_journaled_manifest(tmp_path, monkeypatch) -> None:
    catalog = load_catalog("v2")
    work = item().model_copy(update={"approved_scope": ("project/**",)})
    compiled = compile_pipeline(catalog, work, (), lead(), NOW)
    store = V2ProjectStore(tmp_path)
    store.write_immutable(work, work.work_item_id)
    revision = PipelineRuntime(store, catalog=catalog).initialize(
        "baseline-run", compiled.plan, decision(compiled.refs.plan), created_at=NOW
    )
    revision_record = store.resolve(revision.pipeline_revision)
    stage = revision_record.stages[0]
    from codexteam_tools.v2 import Assignment, build_role_instance, EvidenceManager

    assignment = Assignment(
        schema_version="2.0",
        kind="assignment",
        assignment_id="baseline-assignment",
        work_item=compiled.refs.work_item,
        stage=stage.stage,
        agent_spec=stage.agent_spec,
        scope=("project/**",),
    )
    store.write_immutable(assignment, assignment.assignment_id)
    role = build_role_instance(catalog, assignment=assignment, work_item=work, pipeline_revision=revision_record, stage_spec=stage, attempt_id="baseline-attempt")
    original = store.append_event
    failed = False

    def fail_once(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("baseline append failed")
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "append_event", fail_once)
    manager = EvidenceManager(store)
    with pytest.raises(OSError, match="baseline append failed"):
        manager.begin_stage(stage.stage_id, role)
    journaled = store.journaled_record(
        f"stage-start-{role.role_instance_id}",
        "project_manifest",
        f"manifest-stage-start-{role.role_instance_id}",
    )
    monkeypatch.setattr(store, "append_event", original)
    reference = manager.begin_stage(stage.stage_id, role)
    assert store.resolve(reference) == journaled


def test_frozen_stage_revision_ancestry_accepts_only_proven_ancestors(tmp_path) -> None:
    catalog = load_catalog("v2")
    work = item().model_copy(update={"approved_scope": ("project/**",)})
    compiled = compile_pipeline(catalog, work, ("architecture",), lead(), NOW)
    store = V2ProjectStore(tmp_path)
    approval = decision(compiled.refs.plan).model_copy(update={"decision_id": "ancestry-decision"})
    decision_ref = store.write_immutable(approval, "ancestry-decision")
    first = PipelineRevision(
        schema_version="2.0",
        kind="pipeline_revision",
        revision_id="ancestry-r1",
        plan=compiled.refs.plan,
        revision_number=1,
        stages=compiled.plan.stages,
        frozen_stage_ids=(),
        frozen_stage_digests=(),
        parent_stage_digests=(),
        applies_from_stage=compiled.plan.stages[0].stage_id,
        reason="initial",
        approving_decision=decision_ref,
        created_at=NOW,
    )
    first_ref = store.write_immutable(first, first.revision_id)
    frozen = first.stages[:2]
    second = PipelineRevision(
        schema_version="2.0",
        kind="pipeline_revision",
        revision_id="ancestry-r2",
        plan=compiled.refs.plan,
        revision_number=2,
        parent_revision=first_ref,
        stages=first.stages,
        frozen_stage_ids=tuple(stage.stage_id for stage in frozen),
        frozen_stage_digests=tuple(
            FrozenStageDigest(stage_id=stage.stage_id, stage_spec_digest=pipeline_stage_digest(stage))
            for stage in frozen
        ),
        parent_stage_digests=tuple(
            ParentStageDigest(stage_id=stage.stage_id, digest=pipeline_stage_digest(stage)) for stage in frozen
        ),
        applies_from_stage=first.stages[2].stage_id,
        reason="revise later stages",
        approving_decision=decision_ref,
        created_at=NOW,
    )
    store.write_immutable(second, second.revision_id)
    architecture = frozen[1]
    assert stage_revision_is_valid(
        store, second, first_ref, architecture.stage_id, pipeline_stage_digest(architecture)
    )
    unrelated = first.model_copy(update={"revision_id": "unrelated-r1", "reason": "unrelated"})
    unrelated_ref = store.write_immutable(unrelated, unrelated.revision_id)
    assert not stage_revision_is_valid(
        store, second, unrelated_ref, architecture.stage_id, pipeline_stage_digest(architecture)
    )
