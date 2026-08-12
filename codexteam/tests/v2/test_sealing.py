from __future__ import annotations

from datetime import datetime, timezone

import pytest

from codexteam_tools.v2 import (
    AcceptanceCriterion,
    ActorRef,
    Assignment,
    AssuranceDisposition,
    AssuranceDomain,
    AssuranceReport,
    CandidateReport,
    CandidateSeal,
    ContextPack,
    CriterionDisposition,
    CriterionResult,
    EvidenceType,
    EvidenceManager,
    FrozenStageDigest,
    LeadDecision,
    MachineVerificationSpec,
    ParentStageDigest,
    PipelineRevision,
    PipelineRunProjection,
    PipelineRuntime,
    RecordRef,
    ReviewDecision,
    RunBinding,
    StageProjection,
    VerificationReceipt,
    VerificationCriterion,
    VerificationPlan,
    VerificationRun,
    V2ProjectStore,
    WorkItem,
    build_role_instance,
    canonical_sha256,
    close_candidate,
    compile_pipeline,
    derive_change_set,
    load_catalog,
    pipeline_stage_digest,
    replay_closure,
    render_candidate,
    render_pipeline,
    seal_candidate,
    workspace_manifest,
    write_view,
)


NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)


def ref(kind: str, identifier: str, digest: str = "a" * 64) -> RecordRef:
    return RecordRef(record_id=identifier, kind=kind, digest=digest)


def test_deterministic_views_are_non_authoritative_and_idempotent(tmp_path) -> None:
    revision = ref("pipeline_revision", "revision-1")
    projection = PipelineRunProjection(
        run_id="run-1",
        plan=ref("pipeline_plan", "plan-1"),
        pipeline_revision=revision,
        state_revision=1,
        stages=(StageProjection(stage_id="discovery", status="ready", stage_spec_digest="b" * 64, pipeline_revision=revision),),
    )
    assert render_pipeline(projection) == render_pipeline(projection)
    assert b"canonical-authority: false" in render_pipeline(projection)
    store = V2ProjectStore(tmp_path)
    write_view(store, "pipeline", render_pipeline(projection))
    first = (store.root / "views/pipeline.md").read_bytes()
    write_view(store, "pipeline", render_pipeline(projection))
    assert (store.root / "views/pipeline.md").read_bytes() == first


def test_seal_duplicate_and_closure_replay(tmp_path) -> None:
    (tmp_path / "source.txt").write_text("candidate", encoding="utf-8")
    store = V2ProjectStore(tmp_path)
    with pytest.raises(PermissionError, match="kernel-reserved"):
        store.append_event(
            "candidate-history-forgery",
            {"type": "candidate_processed"},
            expected_version=0,
        )
    catalog = load_catalog("v2")
    lead = ActorRef(actor_id="lead", kind="project_lead")
    work = WorkItem(
        schema_version="2.0",
        kind="work_item",
        work_item_id="work-seal",
        title="Seal canary",
        objective="Exercise resolved sealing",
        acceptance_criteria=(
            AcceptanceCriterion(
                id="criterion",
                statement="Pass",
                required_evidence_types=(EvidenceType.TEST_OUTPUT,),
                verification=MachineVerificationSpec(
                    verifier_argv=("true",), argv=("true",), expected_stdout=""
                ),
            ),
        ),
        approved_scope=("project/**",),
    )
    compiled = compile_pipeline(catalog, work, (), lead, NOW)
    plan_decision = LeadDecision(
        schema_version="2.0",
        kind="lead_decision",
        decision_id="decision-plan",
        decision="approve",
        subject=compiled.refs.plan,
        rationale="Approve plan",
        decided_by=lead,
        decided_at=NOW,
    )
    plan_decision_ref = ref("lead_decision", plan_decision.decision_id, canonical_sha256(plan_decision))
    revision = PipelineRevision(
        schema_version="2.0",
        kind="pipeline_revision",
        revision_id="revision-seal",
        plan=compiled.refs.plan,
        revision_number=1,
        stages=compiled.plan.stages,
        frozen_stage_ids=(),
        frozen_stage_digests=(),
        parent_stage_digests=(),
        applies_from_stage=compiled.plan.stages[0].stage_id,
        reason="Initial revision",
        approving_decision=plan_decision_ref,
        created_at=NOW,
    )
    revision_ref = ref("pipeline_revision", revision.revision_id, canonical_sha256(revision))
    _, evidence = EvidenceManager(store).write_artifact(
        b"passed\n", EvidenceType.TEST_OUTPUT, lead, created_at=NOW, evidence_id="evidence-1"
    )
    base = workspace_manifest(tmp_path, created_at=NOW)
    change = derive_change_set(base, base, created_at=NOW)
    change_ref = ref("change_set", change.change_set_id, canonical_sha256(change))
    roles = []
    assignments = []
    packs = []
    candidates = []
    implementation = None
    for stage in revision.stages:
        assignment = Assignment(
            schema_version="2.0",
            kind="assignment",
            assignment_id=f"assignment-{stage.stage_id}",
            work_item=compiled.refs.work_item,
            stage=stage.stage,
            agent_spec=stage.agent_spec,
            scope=("project/**",),
            assurance_domain=stage.assurance_domain,
        )
        role = build_role_instance(
            catalog,
            assignment=assignment,
            work_item=work,
            pipeline_revision=revision,
            stage_spec=stage,
            attempt_id=f"attempt-{stage.stage_id}",
        )
        assignment_ref = ref("assignment", assignment.assignment_id, canonical_sha256(assignment))
        role_ref = ref("role_instance", role.role_instance_id, canonical_sha256(role))
        pack = ContextPack(
            schema_version="2.0",
            kind="context_pack",
            context_pack_id=f"context-{stage.stage_id}",
            assignment=assignment_ref,
            items=(),
            digest="d" * 64,
        )
        pack_ref = ref("context_pack", pack.context_pack_id, canonical_sha256(pack))
        candidate = CandidateReport(
            schema_version="2.0",
            kind="candidate_report",
            candidate_report_id=f"candidate-{stage.stage_id}",
            work_item=compiled.refs.work_item,
            pipeline_revision=revision_ref,
            assignment=assignment_ref,
            role_instance=role_ref,
            stage=stage.stage,
            stage_id=stage.stage_id,
            stage_spec_digest=pipeline_stage_digest(stage),
            attempt_id=role.attempt_id,
            context_pack=pack_ref,
            change_set=change_ref if stage.stage in {"implementation", "verification"} else None,
            outcome="succeeded",
            criterion_ids=("criterion",),
            criterion_dispositions=(
                CriterionDisposition(
                    criterion_id="criterion",
                    disposition=(
                        "claimed_satisfied"
                        if stage.stage == "implementation"
                        else "verified"
                        if stage.stage == "verification"
                        else "not_evaluated"
                    ),
                    evidence=(evidence,) if stage.stage in {"implementation", "verification"} else (),
                    evidence_types=(EvidenceType.TEST_OUTPUT,) if stage.stage in {"implementation", "verification"} else (),
                ),
            ),
            evidence=(evidence,),
            produced_at=NOW,
        )
        roles.append(role)
        assignments.append(assignment)
        packs.append(pack)
        candidates.append(candidate)
        if stage.stage == "implementation":
            implementation = candidate
    assert implementation is not None
    candidate_ref = ref("candidate_report", implementation.candidate_report_id, canonical_sha256(implementation))
    plan = VerificationPlan(
        schema_version="2.0",
        kind="verification_plan",
        verification_plan_id="verification-plan-1",
        work_item=compiled.refs.work_item,
        criteria=(
                VerificationCriterion(
                    criterion_id="criterion",
                    statement="Pass",
                    required_evidence_types=(EvidenceType.TEST_OUTPUT,),
                    verification=MachineVerificationSpec(
                        verifier_argv=("true",), argv=("true",), expected_stdout=""
                    ),
                ),
        ),
        commands=(("true",),),
        created_at=NOW,
    )
    plan_ref = store.write_immutable(plan, plan.verification_plan_id)
    run = VerificationRun(
        schema_version="2.0",
        kind="verification_run",
        verification_run_id="run-1",
        plan=plan_ref,
        candidate=candidate_ref,
        change_set=change_ref,
        workspace_digest=base.root_digest,
        command=("true",),
        exit_code=0,
        duration_seconds=0.0,
        evidence=(evidence,),
        started_at=NOW,
        finished_at=NOW,
    )
    run_ref = store.write_immutable(run, run.verification_run_id)
    verification_role = next(role for role in roles if role.stage_id == "verification")
    verifier = ActorRef(actor_id="verifier", kind="agent", role_instance_id=verification_role.role_instance_id)
    binding = RunBinding(
        run=run_ref,
        plan=plan_ref,
        candidate=candidate_ref,
        change_set=change_ref,
        workspace_digest=base.root_digest,
    )
    receipt = VerificationReceipt(
        schema_version="2.0",
        kind="verification_receipt",
        verification_receipt_id="receipt-1",
        plan=plan_ref,
        candidate=candidate_ref,
        change_set=change_ref,
        workspace_digest=base.root_digest,
        run_bindings=(binding,),
        criterion_ids=("criterion",),
        criterion_results=(
            CriterionResult(criterion_id="criterion", command_indexes=(0,), disposition="pass", evidence=(evidence,)),
        ),
        accepted=True,
        producer_role_instance_id=implementation.role_instance.record_id,
        issued_by=verifier,
        issued_at=NOW,
    )
    assurance_role = next(role for role in roles if role.stage_id == "assurance")
    auditor = ActorRef(actor_id="auditor", kind="agent", role_instance_id=assurance_role.role_instance_id)
    assurance = AssuranceReport(
        schema_version="2.0",
        kind="assurance_report",
        assurance_report_id="assurance-1",
        candidate=candidate_ref,
        producer_role_instance_id=implementation.role_instance.record_id,
        dispositions=(AssuranceDisposition(domain=AssuranceDomain.SECURITY_PRIVACY, disposition="pass"),),
        auditor=auditor,
        produced_at=NOW,
    )
    assurance_ref = ref("assurance_report", assurance.assurance_report_id, canonical_sha256(assurance))
    receipt_ref = ref("verification_receipt", receipt.verification_receipt_id, canonical_sha256(receipt))
    review_role = next(role for role in roles if role.stage_id == "review")
    reviewer = ActorRef(actor_id="reviewer", kind="agent", role_instance_id=review_role.role_instance_id)
    review = ReviewDecision(
        schema_version="2.0",
        kind="review_decision",
        review_decision_id="review-1",
        candidate=candidate_ref,
        producer_role_instance_id=implementation.role_instance.record_id,
        decision="ACCEPT",
        rationale="Accepted",
        evidence=(assurance_ref,),
        verification_receipts=(receipt_ref,),
        reviewer=reviewer,
        decided_at=NOW,
    )
    lead_decision = LeadDecision(
        schema_version="2.0",
        kind="lead_decision",
        decision_id="decision-seal",
        decision="approve",
        subject=ref("review_decision", review.review_decision_id, canonical_sha256(review)),
        rationale="Approve candidate",
        decided_by=lead,
        decided_at=NOW,
    )
    for record, identifier in (
        (work, work.work_item_id),
        (compiled.plan, compiled.plan.plan_id),
        (plan_decision, plan_decision.decision_id),
        (revision, revision.revision_id),
        (base, base.manifest_id),
        (change, change.change_set_id),
        (receipt, receipt.verification_receipt_id),
        (assurance, assurance.assurance_report_id),
        (review, review.review_decision_id),
        (lead_decision, lead_decision.decision_id),
    ):
        store.write_immutable(record, identifier)
    for record in (*assignments, *roles, *packs, *candidates):
        store.write_immutable(record, store.reference(record).record_id)
    history = f"candidate-history-{work.work_item_id}"
    for candidate in candidates:
        if candidate.change_set is None:
            continue
        candidate_reference = store.reference(candidate)
        candidate_assignment = store.resolve(candidate.assignment)
        candidate_role = store.resolve(candidate.role_instance)
        candidate_pack = store.resolve(candidate.context_pack)
        candidate_revision = store.resolve(candidate.pipeline_revision)
        store._append_event_internal(
            history,
            {
                "assignment": store.reference(candidate_assignment).model_dump(mode="json"),
                "base_manifest": store.reference(base).model_dump(mode="json"),
                "candidate": candidate_reference.model_dump(mode="json"),
                "change_set": candidate.change_set.model_dump(mode="json"),
                "context_pack": store.reference(candidate_pack).model_dump(mode="json"),
                "final_manifest": store.reference(base).model_dump(mode="json"),
                "pipeline_revision": store.reference(candidate_revision).model_dump(mode="json"),
                "role_instance": store.reference(candidate_role).model_dump(mode="json"),
                "stage": candidate.stage,
                "stage_id": candidate.stage_id,
                "type": "candidate_processed",
                "work_item": store.reference(work).model_dump(mode="json"),
            },
            expected_version=len(store.replay_events(history)),
        )
    store.append_event(
        "pipeline-seal",
        {
            "plan": compiled.refs.plan.model_dump(mode="json"),
            "pipeline_revision": revision_ref.model_dump(mode="json"),
            "stages": [
                {"stage_id": stage.stage_id, "stage_spec_digest": pipeline_stage_digest(stage)}
                for stage in revision.stages
            ],
            "type": "initialized",
        },
        expected_version=0,
    )
    runtime_manager = PipelineRuntime(store)
    runtime = runtime_manager.replay("pipeline-seal")
    for role, candidate in zip(roles, candidates, strict=True):
        runtime = runtime_manager.start(
            "pipeline-seal", role.stage_id, role, expected_state_revision=runtime.state_revision
        )
        runtime = runtime_manager.succeed(
            "pipeline-seal",
            role.stage_id,
            store.reference(candidate),
            expected_state_revision=runtime.state_revision,
        )
    first_baseline = store.replay_events(f"stage-evidence-{roles[0].role_instance_id}")[0]
    base = store.resolve(RecordRef.model_validate(first_baseline.payload["base_manifest"]))
    values = dict(
        project_id="project-seal",
        runtime=runtime,
        work_item=work,
        pipeline_revision=revision,
        role_instances=roles,
        context_packs=packs,
        stage_candidates=candidates,
        base_manifest=base,
        cumulative_change_set=change,
        verification_receipts=(receipt,),
        assurance_report=assurance,
        review_decision=review,
        lead_decision=lead_decision,
        sealed_by=lead,
    )
    failed_run = run.model_copy(update={"verification_run_id": "run-failed", "exit_code": 1})
    failed_run_ref = store.write_immutable(failed_run, failed_run.verification_run_id)
    failed_receipt = receipt.model_copy(
        update={
            "verification_receipt_id": "receipt-failed-hidden",
            "run_bindings": (binding.model_copy(update={"run": failed_run_ref}),),
        }
    )
    store.write_immutable(failed_receipt, failed_receipt.verification_receipt_id)
    with pytest.raises(ValueError, match="failed run"):
        seal_candidate(store, **{**values, "verification_receipts": (failed_receipt,)})
    seal = seal_candidate(store, **values)
    assert seal_candidate(store, **values) == seal
    assert replay_closure(store, "project-seal").status == "sealed"
    assert close_candidate(store, seal, closed_by=lead).status == "closed"
    assert replay_closure(V2ProjectStore(tmp_path), "project-seal").status == "closed"
    assert seal_candidate(store, **values) == seal
