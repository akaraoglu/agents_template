from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Literal, cast

from pydantic import Field

from .canonical import canonical_sha256
from .evidence import EvidenceManager, derive_change_set, validate_change_attribution, workspace_manifest
from .models import (
    ActorRef,
    AssuranceDomain,
    AssuranceReport,
    Assignment,
    CandidateReport,
    CandidateSeal,
    ChangeSet,
    ContractModel,
    ContextPack,
    LeadDecision,
    EvidenceType,
    MachineVerificationSpec,
    PipelineRevision,
    ProjectManifest,
    RecordRef,
    RequiredStageCandidate,
    ReviewDecision,
    RoleInstance,
    VerificationReceipt,
    VerificationPlan,
    VerificationRun,
    WorkItem,
    create_candidate_seal,
    project_path_pattern_matches,
)
from .storage import V2ProjectStore
from .verification import receipt_is_fresh, validate_assurance_report, validate_review_decision
from .pipeline_runtime import PipelineRunProjection, PipelineRuntime, stage_revision_is_valid


class ClosureProjection(ContractModel):
    project_id: str
    status: Literal["unsealed", "sealed", "closed"]
    revision: int = Field(ge=0)
    candidate_seal: RecordRef | None = None
    closed_by: ActorRef | None = None


def _ref(record: object, record_id: str, kind: str) -> RecordRef:
    return RecordRef(record_id=record_id, kind=kind, digest=canonical_sha256(record))


def seal_candidate(
    store: V2ProjectStore,
    *,
    project_id: str,
    runtime: PipelineRunProjection,
    work_item: WorkItem,
    pipeline_revision: PipelineRevision,
    role_instances: Sequence[RoleInstance],
    context_packs: Sequence[ContextPack],
    stage_candidates: Sequence[CandidateReport],
    base_manifest: ProjectManifest,
    cumulative_change_set: ChangeSet,
    verification_receipts: Sequence[VerificationReceipt],
    assurance_report: AssuranceReport,
    review_decision: ReviewDecision,
    lead_decision: LeadDecision,
    sealed_by: ActorRef,
    required_assurance_domains: Sequence[AssuranceDomain] | None = None,
    compiler_version: str = "codexteam-v2-compiler/1",
    sealed_at: datetime | None = None,
) -> CandidateSeal:
    if PipelineRuntime(store).replay(runtime.run_id) != runtime:
        raise ValueError("pipeline runtime projection is stale or not store-derived")
    if runtime.pipeline_revision != store.reference(pipeline_revision) or not runtime.complete:
        raise ValueError("sealing requires the current revision with every runtime stage succeeded")
    supplied_records = (
        work_item,
        pipeline_revision,
        base_manifest,
        cumulative_change_set,
        assurance_report,
        review_decision,
        lead_decision,
        *role_instances,
        *context_packs,
        *stage_candidates,
        *verification_receipts,
    )
    for record in supplied_records:
        reference = store.reference(record)
        if store.resolve(reference) != record:
            raise ValueError(f"sealing input is not the stored immutable {reference.kind} record")
    observed_manifest = workspace_manifest(store.project, created_at=sealed_at or datetime.now(timezone.utc))
    seal_operation = f"seal-{canonical_sha256({
        'compiler_version': compiler_version,
        'project_id': project_id,
        'records': tuple(sorted((store.reference(record) for record in supplied_records), key=lambda item: (item.kind, item.record_id))),
        'sealed_by': sealed_by,
        'workspace_digest': observed_manifest.root_digest,
    })}"
    journaled_manifest = store.journaled_record(seal_operation, "project_manifest", f"manifest-{seal_operation}")
    manifest_time = sealed_at or (
        cast(ProjectManifest, journaled_manifest).created_at
        if journaled_manifest is not None
        else datetime.now(timezone.utc)
    )
    current_manifest = workspace_manifest(
        store.project,
        created_at=manifest_time,
        manifest_id=f"manifest-{seal_operation}",
    )
    if journaled_manifest is not None and journaled_manifest != current_manifest:
        raise ValueError("journaled seal manifest conflicts with the current workspace")
    if cumulative_change_set.base_manifest_digest != base_manifest.root_digest:
        raise ValueError("cumulative ChangeSet does not begin at the supplied base manifest")
    if cumulative_change_set.final_manifest_digest != current_manifest.root_digest:
        raise ValueError("workspace changed after the cumulative ChangeSet was derived")
    observed_change = derive_change_set(base_manifest, current_manifest, created_at=manifest_time)
    if observed_change.entries != cumulative_change_set.entries:
        raise ValueError("cumulative ChangeSet is not derived from the run base and current workspace")
    required_ids = tuple(sorted(stage.stage_id for stage in pipeline_revision.stages))
    candidate_by_stage = {candidate.stage_id: candidate for candidate in stage_candidates}
    if len(candidate_by_stage) != len(stage_candidates) or set(candidate_by_stage) != set(required_ids):
        raise ValueError("stage candidates must exactly cover the pipeline revision")
    revision_ref = _ref(pipeline_revision, pipeline_revision.revision_id, "pipeline_revision")
    work_ref = _ref(work_item, work_item.work_item_id, "work_item")
    roles_by_id = {role.role_instance_id: role for role in role_instances}
    packs_by_id = {pack.context_pack_id: pack for pack in context_packs}
    referenced_role_ids = {candidate.role_instance.record_id for candidate in stage_candidates}
    referenced_pack_ids = {candidate.context_pack.record_id for candidate in stage_candidates}
    if set(roles_by_id) != referenced_role_ids or set(packs_by_id) != referenced_pack_ids:
        raise ValueError("role instances and context packs must exactly cover stage candidate references")
    first_stage_id = pipeline_revision.stages[0].stage_id
    first_candidate = candidate_by_stage[first_stage_id]
    baseline_events = store.replay_events(f"stage-evidence-{first_candidate.role_instance.record_id}")
    if len(baseline_events) != 1 or baseline_events[0].payload.get("type") != "stage_started":
        raise ValueError("run base manifest is not pinned by the first stage-start event")
    run_base_ref = RecordRef.model_validate(baseline_events[0].payload["base_manifest"])
    if run_base_ref != store.reference(base_manifest):
        raise ValueError("supplied base manifest is not the run base manifest")
    evidence_manager = EvidenceManager(store)
    writing_changes: list[ChangeSet] = []
    for current_stage_spec in pipeline_revision.stages:
        stage_id = current_stage_spec.stage_id
        candidate = candidate_by_stage[stage_id]
        if candidate.outcome != "succeeded" or candidate.work_item != work_ref:
            raise ValueError(f"stage candidate {stage_id!r} is not a successful candidate for this revision")
        role = roles_by_id.get(candidate.role_instance.record_id)
        pack = packs_by_id.get(candidate.context_pack.record_id)
        if (
            role is None
            or candidate.role_instance.digest != canonical_sha256(role)
            or role.stage_id != stage_id
            or role.stage_spec_digest != candidate.stage_spec_digest
            or role.attempt_id != candidate.attempt_id
            or candidate.assignment != role.assignment
            or pack is None
            or candidate.context_pack.digest != canonical_sha256(pack)
            or pack.assignment != role.assignment
        ):
            raise ValueError(f"stage candidate {stage_id!r} has unresolved pinned records")
        if candidate.stage != current_stage_spec.stage or candidate.stage_spec_digest != canonical_sha256(current_stage_spec):
            raise ValueError(f"stage candidate {stage_id!r} does not match its revision stage")
        if set(candidate.criterion_ids) != {criterion.id for criterion in work_item.acceptance_criteria}:
            raise ValueError(f"stage candidate {stage_id!r} does not cover the work item criteria")
        resolved_candidate_evidence = {}
        for evidence_ref in candidate.evidence:
            artifact = evidence_manager.resolve_artifact(evidence_ref)
            resolved_candidate_evidence[evidence_ref] = artifact
        assignment = cast(Assignment, store.resolve(candidate.assignment))
        if assignment.work_item != work_ref or assignment.stage != candidate.stage:
            raise ValueError(f"stage candidate {stage_id!r} assignment is not bound to the WorkItem")
        if candidate.change_set is not None:
            candidate_change = cast(ChangeSet, store.resolve(candidate.change_set))
            if any(
                not any(project_path_pattern_matches(pattern, entry.path) for pattern in assignment.scope)
                for entry in candidate_change.entries
            ):
                raise ValueError(f"stage candidate {stage_id!r} changes paths outside assignment scope")
            if any(
                not any(project_path_pattern_matches(pattern, entry.path) for pattern in work_item.approved_scope)
                for entry in candidate_change.entries
            ):
                raise ValueError(f"stage candidate {stage_id!r} changes paths outside WorkItem approved scope")
            if candidate.stage in {"architecture", "ux", "implementation", "verification"}:
                writing_changes.append(candidate_change)
        criterion_by_id = {criterion.id: criterion for criterion in work_item.acceptance_criteria}
        allowed_dispositions = {
            "implementation": {"claimed_satisfied", "unsatisfied"},
            "verification": {"verified", "unsatisfied"},
            "discovery": {"not_evaluated", "unsatisfied"},
            "architecture": {"not_evaluated", "unsatisfied"},
            "ux": {"not_evaluated", "unsatisfied"},
            "assurance": {"not_evaluated", "unsatisfied"},
            "review": {"not_evaluated", "unsatisfied"},
        }[candidate.stage]
        for disposition in candidate.criterion_dispositions:
            if disposition.disposition not in allowed_dispositions:
                raise ValueError(f"stage candidate {stage_id!r} uses a stage-inappropriate criterion disposition")
            if not set(disposition.evidence) <= resolved_candidate_evidence.keys():
                raise ValueError(f"stage candidate {stage_id!r} criterion uses undeclared evidence")
            actual_types = {resolved_candidate_evidence[reference].evidence_type for reference in disposition.evidence}
            if actual_types != set(disposition.evidence_types):
                raise ValueError(f"stage candidate {stage_id!r} declares incorrect evidence types")
            if disposition.disposition == "verified" and not set(
                criterion_by_id[disposition.criterion_id].required_evidence_types
            ) <= actual_types:
                raise ValueError(f"stage candidate {stage_id!r} lacks required criterion evidence")
        runtime_stage = next((item for item in runtime.stages if item.stage_id == stage_id), None)
        candidate_ref = store.reference(candidate)
        if (
            runtime_stage is None
            or runtime_stage.status != "succeeded"
            or runtime_stage.pipeline_revision != candidate.pipeline_revision
            or runtime_stage.active_role_instance != candidate.role_instance
            or runtime_stage.attempt_id != candidate.attempt_id
            or runtime_stage.candidate != candidate_ref
        ):
            raise ValueError(f"stage candidate {stage_id!r} is not the active successful runtime candidate")
        if (
            role.pipeline_revision != candidate.pipeline_revision
            or not stage_revision_is_valid(
                store,
                pipeline_revision,
                candidate.pipeline_revision,
                stage_id,
                candidate.stage_spec_digest,
            )
        ):
            raise ValueError(f"stage role {stage_id!r} is not pinned to a valid current or frozen ancestor revision")
    implementation = next((candidate for candidate in stage_candidates if candidate.stage == "implementation"), None)
    if implementation is None or implementation.change_set is None:
        raise ValueError("pipeline requires an implementation ChangeSet")
    change_ref = _ref(cumulative_change_set, cumulative_change_set.change_set_id, "change_set")
    attributed_history: list[ChangeSet] = []
    seen_stage_changes: set[tuple[str, RecordRef]] = set()
    for event in store.replay_events(
        f"candidate-history-{work_item.work_item_id}"
    ):
        payload = event.payload
        if payload.get("type") != "candidate_processed":
            raise ValueError("candidate history contains an unsupported event")
        candidate_value = payload.get("candidate")
        historical_candidate = cast(
            CandidateReport,
            store.resolve(RecordRef.model_validate(candidate_value)),
        )
        if historical_candidate.work_item != work_ref:
            raise ValueError("candidate history contains another WorkItem")
        historical_assignment = cast(
            Assignment,
            store.resolve(RecordRef.model_validate(payload.get("assignment"))),
        )
        historical_role = cast(
            RoleInstance,
            store.resolve(RecordRef.model_validate(payload.get("role_instance"))),
        )
        historical_pack = cast(
            ContextPack,
            store.resolve(RecordRef.model_validate(payload.get("context_pack"))),
        )
        historical_revision = cast(
            PipelineRevision,
            store.resolve(RecordRef.model_validate(payload.get("pipeline_revision"))),
        )
        historical_base = cast(
            ProjectManifest,
            store.resolve(RecordRef.model_validate(payload.get("base_manifest"))),
        )
        historical_final = cast(
            ProjectManifest,
            store.resolve(RecordRef.model_validate(payload.get("final_manifest"))),
        )
        if (
            RecordRef.model_validate(payload.get("work_item")) != work_ref
            or historical_assignment.work_item != work_ref
            or historical_assignment.stage != historical_candidate.stage
            or historical_candidate.assignment != store.reference(historical_assignment)
            or historical_candidate.role_instance != store.reference(historical_role)
            or historical_role.assignment != historical_candidate.assignment
            or historical_role.pipeline_revision != historical_candidate.pipeline_revision
            or historical_role.stage_id != historical_candidate.stage_id
            or historical_role.stage_spec_digest != historical_candidate.stage_spec_digest
            or historical_role.attempt_id != historical_candidate.attempt_id
            or historical_candidate.context_pack != store.reference(historical_pack)
            or historical_pack.assignment != historical_candidate.assignment
            or historical_candidate.pipeline_revision != store.reference(historical_revision)
        ):
            raise ValueError("candidate history provenance is inconsistent")
        if (
            historical_candidate.stage
            in {"architecture", "ux", "implementation", "verification"}
            and historical_candidate.change_set is not None
        ):
            stage_change = (
                historical_candidate.stage_id,
                historical_candidate.change_set,
            )
            if stage_change in seen_stage_changes:
                # Receipt promotion replaces semantic verification metadata but
                # does not represent another workspace mutation.
                continue
            seen_stage_changes.add(stage_change)
            historical_change = cast(
                ChangeSet, store.resolve(historical_candidate.change_set)
            )
            rederived = derive_change_set(
                historical_base,
                historical_final,
                created_at=historical_change.created_at,
                change_set_id=historical_change.change_set_id,
            )
            if RecordRef.model_validate(payload.get("change_set")) != store.reference(
                historical_change
            ) or rederived != historical_change:
                raise ValueError("candidate history ChangeSet reference is inconsistent")
            attributed_history.append(historical_change)
    if not attributed_history:
        raise ValueError("pipeline event history contains no attributed writing-stage changes")
    validate_change_attribution(
        base_manifest,
        cumulative_change_set,
        tuple(attributed_history),
    )
    producer_id = roles_by_id[implementation.role_instance.record_id].role_instance_id
    verification_candidate = next(candidate for candidate in stage_candidates if candidate.stage == "verification")
    assurance_candidate = next(candidate for candidate in stage_candidates if candidate.stage == "assurance")
    review_candidate = next(candidate for candidate in stage_candidates if candidate.stage == "review")
    if not verification_receipts or any(
        not receipt.accepted
        or not receipt_is_fresh(receipt, implementation, cumulative_change_set, current_manifest)
        for receipt in verification_receipts
    ):
        raise ValueError("all required verification receipts must be accepted and fresh")
    criterion_by_id = {criterion.id: criterion for criterion in work_item.acceptance_criteria}
    expected_criterion_ids = set(criterion_by_id)
    receipt_evidence_by_criterion: dict[str, list[RecordRef]] = {
        criterion_id: [] for criterion_id in expected_criterion_ids
    }
    for receipt in verification_receipts:
        plan = cast(VerificationPlan, store.resolve(receipt.plan))
        if plan.work_item != work_ref or {item.criterion_id for item in plan.criteria} != expected_criterion_ids:
            raise ValueError("verification plan does not exactly cover the candidate WorkItem")
        plan_by_id = {item.criterion_id: item for item in plan.criteria}
        for criterion_id, criterion in criterion_by_id.items():
            planned = plan_by_id[criterion_id]
            if (
                planned.statement != criterion.statement
                or set(planned.required_evidence_types) != set(criterion.required_evidence_types)
                or planned.verification != criterion.verification
            ):
                raise ValueError("verification plan criterion differs from the WorkItem")
        if receipt.producer_role_instance_id != producer_id:
            raise ValueError("verification receipt producer does not match the resolved candidate producer")
        if receipt.issued_by.role_instance_id != verification_candidate.role_instance.record_id:
            raise ValueError("verification receipt issuer is not the verifier-stage role")
        result_by_id = {item.criterion_id: item for item in receipt.criterion_results}
        resolved_runs = []
        for binding in receipt.run_bindings:
            run = cast(VerificationRun, store.resolve(binding.run))
            resolved_runs.append(run)
            if (
                run.plan != receipt.plan
                or run.candidate != receipt.candidate
                or run.change_set != receipt.change_set
                or run.workspace_digest != receipt.workspace_digest
                or store.reference(run) != binding.run
            ):
                raise ValueError("verification run does not match its receipt binding")
            for evidence_ref in run.evidence:
                evidence_manager.resolve_artifact(evidence_ref)
        if tuple(run.command for run in resolved_runs) != plan.commands:
            raise ValueError("verification runs must exactly execute the plan commands")
        if receipt.accepted and any(run.exit_code != 0 for run in resolved_runs):
            raise ValueError("an accepted verification receipt cannot contain a failed run")
        for criterion_id, result in result_by_id.items():
            if any(index >= len(resolved_runs) for index in result.command_indexes):
                raise ValueError("criterion result command mapping is outside the plan")
            expected_evidence = tuple(
                evidence
                for index in result.command_indexes
                for evidence in resolved_runs[index].evidence
            )
            verifier_command = cast(
                MachineVerificationSpec,
                criterion_by_id[criterion_id].verification,
            ).verifier_argv
            if verifier_command not in tuple(
                resolved_runs[index].command for index in result.command_indexes
            ):
                raise ValueError(
                    "criterion result does not include its declared verifier command"
                )
            expected_disposition = (
                "not_run"
                if not result.command_indexes
                else "pass"
                if all(resolved_runs[index].exit_code == 0 for index in result.command_indexes)
                and set(criterion_by_id[criterion_id].required_evidence_types) <= {EvidenceType.TEST_OUTPUT}
                else "fail"
            )
            if result.evidence != expected_evidence or result.disposition != expected_disposition:
                raise ValueError("criterion result does not match its verification run mapping")
            receipt_evidence_by_criterion[criterion_id].extend(result.evidence)
            evidence_types = {
                evidence_manager.resolve_artifact(reference).evidence_type for reference in result.evidence
            }
            if result.disposition == "pass" and not set(
                criterion_by_id[criterion_id].required_evidence_types
            ) <= evidence_types:
                raise ValueError("passing verification evidence lacks a required evidence type")
        if receipt.accepted != all(result.disposition == "pass" for result in receipt.criterion_results):
            raise ValueError("verification receipt acceptance does not match recomputed criterion results")
    verifier_dispositions = {
        item.criterion_id: item for item in verification_candidate.criterion_dispositions
    }
    for criterion_id, receipt_evidence in receipt_evidence_by_criterion.items():
        disposition = verifier_dispositions[criterion_id]
        exact_evidence = tuple(dict.fromkeys(receipt_evidence))
        if disposition.disposition != "verified" or disposition.evidence != exact_evidence:
            raise ValueError("verification candidate must use the exact accepted receipt criterion evidence")
    domains = tuple(required_assurance_domains) if required_assurance_domains is not None else tuple(
        stage.assurance_domain for stage in pipeline_revision.stages if stage.assurance_domain is not None
    )
    validate_assurance_report(assurance_report, implementation, cast(tuple[AssuranceDomain, ...], domains))
    if (
        assurance_report.producer_role_instance_id != producer_id
        or assurance_report.auditor.role_instance_id != assurance_candidate.role_instance.record_id
        or assurance_report.auditor.role_instance_id == producer_id
    ):
        raise ValueError("assurance auditor is not the independent assurance-stage role")
    for disposition in assurance_report.dispositions:
        for evidence_ref in disposition.evidence:
            evidence_manager.resolve_artifact(evidence_ref)
    validate_review_decision(
        review_decision,
        implementation,
        verification_receipts,
        assurance_report,
        cast(tuple[AssuranceDomain, ...], domains),
        current_manifest,
        cumulative_change_set,
    )
    if (
        review_decision.producer_role_instance_id != producer_id
        or review_decision.reviewer.role_instance_id != review_candidate.role_instance.record_id
        or review_decision.reviewer.role_instance_id == producer_id
    ):
        raise ValueError("reviewer is not the independent review-stage role")
    for evidence_ref in review_decision.evidence:
        if evidence_ref.kind == "evidence_artifact":
            evidence_manager.resolve_artifact(evidence_ref)
        else:
            store.resolve(evidence_ref)
    review_ref = _ref(review_decision, review_decision.review_decision_id, "review_decision")
    if (
        lead_decision.decision != "approve"
        or lead_decision.subject != review_ref
        or lead_decision.decided_by.kind != "project_lead"
    ):
        raise ValueError("sealing requires a Project Lead approval of the acceptance review")
    role_refs = tuple(sorted((_ref(item, item.role_instance_id, "role_instance") for item in role_instances), key=lambda item: item.record_id))
    context_refs = tuple(sorted((_ref(item, item.context_pack_id, "context_pack") for item in context_packs), key=lambda item: item.record_id))
    candidate_refs = tuple(
        RequiredStageCandidate(
            stage_id=stage_id,
            candidate=_ref(candidate_by_stage[stage_id], candidate_by_stage[stage_id].candidate_report_id, "candidate_report"),
        )
        for stage_id in required_ids
    )
    final_ref = store.reference(current_manifest)
    base_ref = store.reference(base_manifest)
    seal = create_candidate_seal(
        project_id=project_id,
        work_item=work_ref,
        pipeline_revision=revision_ref,
        required_stage_ids=required_ids,
        role_instances=role_refs,
        context_packs=context_refs,
        stage_candidates=candidate_refs,
        base_manifest=base_ref,
        final_manifest=final_ref,
        cumulative_change_set=change_ref,
        verification_receipts=tuple(
            sorted(
                (_ref(item, item.verification_receipt_id, "verification_receipt") for item in verification_receipts),
                key=lambda item: item.record_id,
            )
        ),
        assurance_report=_ref(assurance_report, assurance_report.assurance_report_id, "assurance_report"),
        acceptance_review=review_ref,
        lead_decision=_ref(lead_decision, lead_decision.decision_id, "lead_decision"),
        compiler_version=compiler_version,
        verification_accepted=True,
        verification_fresh=True,
        assurance_accepted=True,
        acceptance_accepted=True,
        lead_approved=True,
        sealed_by=sealed_by,
        sealed_at=manifest_time,
    )
    prior_seal: CandidateSeal | None = None
    try:
        prior_seal = cast(CandidateSeal, store.read_record("candidate_seal", seal.seal_id))
    except FileNotFoundError:
        pass
    else:
        if prior_seal.candidate_digest != seal.candidate_digest:
            raise ValueError("stored seal conflicts with the resolved candidate payload")
        seal = prior_seal
    payload = {
        "candidate_seal": _ref(seal, seal.seal_id, "candidate_seal").model_dump(mode="json"),
        "type": "candidate_sealed",
    }
    aggregate = f"closure-{project_id}"
    events = store.replay_events(aggregate)
    if events and events[-1].payload.get("type") == "project_closed":
        prior = cast(CandidateSeal, store.resolve(RecordRef.model_validate(events[0].payload["candidate_seal"])))
        if prior.candidate_digest == seal.candidate_digest:
            return prior
        raise ValueError("closed project cannot accept another candidate seal")
    store.commit_records_event(
        seal_operation,
        (
            (current_manifest, current_manifest.manifest_id),
            (seal, seal.seal_id),
        ),
        aggregate,
        payload,
        expected_version=len(events),
    )
    seal_path = store._contained("seals", f"{seal.seal_id}.json")
    content = store._read_projection("records", "candidate_seal", f"{seal.seal_id}.json")
    if store._path_exists(seal_path) and store._read_bytes(seal_path) != content:
        raise ValueError("seal projection conflicts with immutable seal")
    if not store._path_exists(seal_path):
        store._write_projection("seals", f"{seal.seal_id}.json", content, create_only=True)
    return seal


create_seal = seal_candidate


def replay_closure(store: V2ProjectStore, project_id: str) -> ClosureProjection:
    events = store.replay_events(f"closure-{project_id}")
    seal_ref = None
    closed_by = None
    status: Literal["unsealed", "sealed", "closed"] = "unsealed"
    for event in events:
        event_type = event.payload.get("type")
        if event_type == "candidate_sealed":
            if status == "closed":
                raise ValueError("candidate seal follows terminal closure")
            seal_ref = RecordRef.model_validate(event.payload["candidate_seal"])
            status = "sealed"
        elif event_type == "project_closed":
            candidate = RecordRef.model_validate(event.payload["candidate_seal"])
            if status != "sealed" or candidate != seal_ref:
                raise ValueError("closure does not reference the current candidate seal")
            closed_by = ActorRef.model_validate(event.payload["closed_by"])
            if closed_by.kind != "project_lead":
                raise ValueError("project closure requires a Project Lead")
            status = "closed"
        else:
            raise ValueError(f"unknown closure event type {event_type!r}")
    return ClosureProjection(
        project_id=project_id,
        status=status,
        revision=len(events),
        candidate_seal=seal_ref,
        closed_by=closed_by,
    )


def close_candidate(
    store: V2ProjectStore,
    seal: CandidateSeal,
    *,
    closed_by: ActorRef,
) -> ClosureProjection:
    if closed_by.kind != "project_lead":
        raise PermissionError("only a Project Lead may close a sealed candidate")
    seal_ref = _ref(seal, seal.seal_id, "candidate_seal")
    store.resolve(seal_ref)
    project_id = seal.project_id
    projection = replay_closure(store, project_id)
    if projection.status == "closed":
        if projection.candidate_seal == seal_ref and projection.closed_by == closed_by:
            return projection
        raise ValueError("project is already closed with different inputs")
    if projection.status != "sealed" or projection.candidate_seal != seal_ref:
        raise ValueError("candidate must be the project's current recorded seal")
    store.append_event(
        f"closure-{project_id}",
        {
            "candidate_seal": seal_ref.model_dump(mode="json"),
            "closed_by": closed_by.model_dump(mode="json"),
            "type": "project_closed",
        },
        expected_version=projection.revision,
    )
    return replay_closure(store, project_id)


__all__ = ["ClosureProjection", "close_candidate", "create_seal", "replay_closure", "seal_candidate"]
