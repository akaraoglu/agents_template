from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Self, cast

from pydantic import Field, model_validator

from .canonical import canonical_sha256
from .catalog import Catalog
from .compiler import compile_pipeline
from .evidence import EvidenceManager
from .models import (
    ActorRef,
    ContractModel,
    FrozenStageDigest,
    LeadDecision,
    ParentStageDigest,
    PipelineChangeRequestBody,
    CandidateReport,
    MailboxMessage,
    PipelinePlan,
    PipelineRevision,
    RecordRef,
    RoleInstance,
    WorkItem,
    pipeline_stage_digest,
)
from .storage import RevisionConflict, V2ProjectStore


StageStatus = Literal["pending", "ready", "active", "succeeded", "blocked", "failed"]


def resolve_revision_ancestry(
    store: V2ProjectStore, current: PipelineRevision
) -> tuple[PipelineRevision, ...]:
    """Resolve and verify the current-to-root pipeline revision chain."""
    ancestry = [current]
    seen = {current.revision_id}
    while ancestry[-1].parent_revision is not None:
        child = ancestry[-1]
        parent = cast(PipelineRevision, store.resolve(cast(RecordRef, child.parent_revision)))
        if parent.revision_id in seen or parent.revision_number + 1 != child.revision_number:
            raise ValueError("pipeline revision ancestry is cyclic or nonconsecutive")
        parent_by_id = {stage.stage_id: stage for stage in parent.stages}
        pinned = {item.stage_id: item.digest for item in child.parent_stage_digests}
        for stage_id in child.frozen_stage_ids:
            stage = parent_by_id.get(stage_id)
            if stage is None or pinned.get(stage_id) != pipeline_stage_digest(stage):
                raise ValueError("pipeline parent-stage digest chain is invalid")
        ancestry.append(parent)
        seen.add(parent.revision_id)
    return tuple(ancestry)


def stage_revision_is_valid(
    store: V2ProjectStore,
    current: PipelineRevision,
    pinned: RecordRef,
    stage_id: str,
    stage_spec_digest: str,
) -> bool:
    ancestry = resolve_revision_ancestry(store, current)
    target_index = next(
        (index for index, revision in enumerate(ancestry) if store.reference(revision) == pinned),
        None,
    )
    if target_index is None:
        return False
    target_stage = next((stage for stage in ancestry[target_index].stages if stage.stage_id == stage_id), None)
    if target_stage is None or pipeline_stage_digest(target_stage) != stage_spec_digest:
        return False
    if target_index == 0:
        return True
    for child in ancestry[:target_index]:
        child_stage = next((stage for stage in child.stages if stage.stage_id == stage_id), None)
        if (
            stage_id not in child.frozen_stage_ids
            or child_stage is None
            or pipeline_stage_digest(child_stage) != stage_spec_digest
        ):
            return False
    return True


class StageProjection(ContractModel):
    stage_id: str
    status: StageStatus
    stage_spec_digest: str
    pipeline_revision: RecordRef
    active_role_instance: RecordRef | None = None
    attempt_id: str | None = None
    candidate: RecordRef | None = None
    operator_required: bool = False
    detail: str | None = None

    @model_validator(mode="after")
    def active_state_is_pinned(self) -> Self:
        if self.status == "active" and (self.active_role_instance is None or self.attempt_id is None):
            raise ValueError("active stages require a pinned role instance and attempt")
        if self.status == "succeeded" and self.candidate is None:
            raise ValueError("succeeded stages require a pinned candidate")
        return self


class PipelineRunProjection(ContractModel):
    run_id: str
    plan: RecordRef
    pipeline_revision: RecordRef
    state_revision: int = Field(ge=1)
    stages: tuple[StageProjection, ...]
    lead_outcome: Literal["approve", "reject", "return", "escalate", "cancel"] | None = None
    operator_required: bool = False

    @property
    def complete(self) -> bool:
        return all(stage.status == "succeeded" for stage in self.stages)


class PipelineRuntime:
    def __init__(self, store: V2ProjectStore, *, catalog: Catalog | None = None) -> None:
        self.store = store
        self.catalog = catalog

    @staticmethod
    def _now(value: datetime | None) -> datetime:
        return value or datetime.now(timezone.utc)

    @staticmethod
    def _ref(record: object, record_id: str, kind: str) -> RecordRef:
        return RecordRef(record_id=record_id, kind=kind, digest=canonical_sha256(record))

    def initialize_run(
        self,
        run_id: str,
        plan: PipelinePlan,
        approving_decision: LeadDecision,
        *,
        created_at: datetime | None = None,
    ) -> PipelineRunProjection:
        if approving_decision.decision != "approve":
            raise ValueError("initial pipeline revision requires an approving LeadDecision")
        plan_ref = self.store.reference(plan)
        if approving_decision.subject != plan_ref:
            raise ValueError("initial LeadDecision must approve the supplied pipeline plan")
        decision_ref = self.store.reference(approving_decision)
        operation_id = f"pipeline-initialize-{run_id}"
        revision_id = f"{run_id}-revision-1"
        journaled = self.store.journaled_record(operation_id, "pipeline_revision", revision_id)
        revision_created_at = created_at or (
            cast(PipelineRevision, journaled).created_at if journaled is not None else self._now(None)
        )
        revision = PipelineRevision(
            schema_version="2.0",
            kind="pipeline_revision",
            revision_id=revision_id,
            plan=plan_ref,
            revision_number=1,
            stages=plan.stages,
            frozen_stage_ids=(),
            frozen_stage_digests=(),
            parent_stage_digests=(),
            applies_from_stage=plan.stages[0].stage_id,
            reason="Initial pipeline revision",
            approving_decision=decision_ref,
            created_at=revision_created_at,
        )
        with self.store.run_lock(run_id):
            events = self.store.replay_events(run_id, _locked=True)
            if events:
                projected = self.replay(run_id)
                if projected.plan != plan_ref:
                    raise RevisionConflict("run already exists with a different plan")
                return projected
            revision_ref = self.store.reference(revision)
            payload = {
                "plan": plan_ref.model_dump(mode="json"),
                "pipeline_revision": revision_ref.model_dump(mode="json"),
                "stages": [
                    {"stage_id": stage.stage_id, "stage_spec_digest": pipeline_stage_digest(stage)}
                    for stage in revision.stages
                ],
                "type": "initialized",
            }
            self.store.commit_records_event(
                operation_id,
                (
                    (plan, plan.plan_id),
                    (approving_decision, approving_decision.decision_id),
                    (revision, revision.revision_id),
                ),
                run_id,
                payload,
                expected_version=0,
                _locked=True,
            )
        return self.replay(run_id)

    initialize = initialize_run

    def replay(self, run_id: str) -> PipelineRunProjection:
        events = self.store.replay_events(run_id)
        if not events or events[0].payload.get("type") != "initialized":
            raise ValueError(f"pipeline run {run_id!r} is not initialized")
        initial = events[0].payload
        plan = RecordRef.model_validate(initial["plan"])
        revision = RecordRef.model_validate(initial["pipeline_revision"])
        stage_values = cast(list[dict[str, str]], initial["stages"])
        stages = [
            StageProjection(
                stage_id=value["stage_id"],
                status="ready" if index == 0 else "pending",
                stage_spec_digest=value["stage_spec_digest"],
                pipeline_revision=revision,
            )
            for index, value in enumerate(stage_values)
        ]
        lead_outcome = None
        operator_required = False
        for event in events[1:]:
            payload = event.payload
            event_type = payload.get("type")
            if event_type == "revision_committed":
                revision = RecordRef.model_validate(payload["pipeline_revision"])
                plan = RecordRef.model_validate(payload["plan"])
                new_values = cast(list[dict[str, str]], payload["stages"])
                prior = {stage.stage_id: stage for stage in stages}
                rebuilt: list[StageProjection] = []
                for index, value in enumerate(new_values):
                    old = prior.get(value["stage_id"])
                    if old is not None and old.status not in {"pending", "ready"}:
                        rebuilt.append(old)
                    else:
                        prior_succeeded = index == 0 or rebuilt[index - 1].status == "succeeded"
                        rebuilt.append(
                            StageProjection(
                                stage_id=value["stage_id"],
                                status="ready" if prior_succeeded else "pending",
                                stage_spec_digest=value["stage_spec_digest"],
                                pipeline_revision=revision,
                            )
                        )
                stages = rebuilt
            elif event_type == "candidate_replaced":
                stage_id = cast(str, payload["stage_id"])
                index = next((index for index, item in enumerate(stages) if item.stage_id == stage_id), -1)
                if index < 0 or stages[index].status != "succeeded":
                    raise ValueError("candidate replacement requires a succeeded stage")
                stages[index] = stages[index].model_copy(
                    update={"candidate": RecordRef.model_validate(payload["candidate"]), "detail": payload.get("detail")}
                )
            elif event_type == "stage_transition":
                stage_id = cast(str, payload["stage_id"])
                index = next((index for index, item in enumerate(stages) if item.stage_id == stage_id), -1)
                if index < 0:
                    raise ValueError(f"event references unknown stage {stage_id!r}")
                current = stages[index]
                target = cast(StageStatus, payload["to_status"])
                allowed = {
                    "pending": {"ready"},
                    "ready": {"active", "blocked", "failed"},
                    "active": {"succeeded", "blocked", "failed"},
                    "blocked": {"ready", "failed"},
                    "failed": set(),
                    "succeeded": set(),
                }
                if target not in allowed[current.status]:
                    raise ValueError(f"impossible stage transition {current.status!r} -> {target!r}")
                if target in {"ready", "active"} and index and stages[index - 1].status != "succeeded":
                    raise ValueError("stage dependency is not satisfied")
                role = RecordRef.model_validate(payload["role_instance"]) if payload.get("role_instance") else None
                if target == "active" and role is None:
                    raise ValueError("active transition lacks a role instance")
                stages[index] = current.model_copy(
                    update={
                        "status": target,
                        "active_role_instance": role if target == "active" else current.active_role_instance,
                        "attempt_id": payload.get("attempt_id") or current.attempt_id,
                        "candidate": RecordRef.model_validate(payload["candidate"]) if payload.get("candidate") else current.candidate,
                        "operator_required": bool(payload.get("operator_required", False)),
                        "detail": payload.get("detail"),
                    }
                )
                if target == "succeeded" and index + 1 < len(stages) and stages[index + 1].status == "pending":
                    stages[index + 1] = stages[index + 1].model_copy(update={"status": "ready"})
                operator_required = any(item.operator_required for item in stages)
            elif event_type == "lead_decision":
                lead_outcome = cast(str, payload["outcome"])
                operator_required = operator_required or bool(payload.get("operator_required", False))
            else:
                raise ValueError(f"unknown pipeline event type {event_type!r}")
        return PipelineRunProjection(
            run_id=run_id,
            plan=plan,
            pipeline_revision=revision,
            state_revision=len(events),
            stages=tuple(stages),
            lead_outcome=lead_outcome,
            operator_required=operator_required,
        )

    def _transition(
        self,
        run_id: str,
        stage_id: str,
        target: StageStatus,
        *,
        expected_state_revision: int,
        role_instance: RoleInstance | None = None,
        candidate: RecordRef | None = None,
        detail: str | None = None,
        operator_required: bool = False,
    ) -> PipelineRunProjection:
        projection = self.replay(run_id)
        if projection.state_revision != expected_state_revision:
            raise RevisionConflict("pipeline state revision changed")
        stage = next((item for item in projection.stages if item.stage_id == stage_id), None)
        if stage is None:
            raise ValueError(f"unknown stage {stage_id!r}")
        allowed = {
            "pending": {"ready"},
            "ready": {"active", "blocked", "failed"},
            "active": {"succeeded", "blocked", "failed"},
            "blocked": {"ready", "failed"},
            "failed": set(),
            "succeeded": set(),
        }
        if target not in allowed[stage.status]:
            raise ValueError(f"impossible stage transition {stage.status!r} -> {target!r}")
        stage_index = projection.stages.index(stage)
        if target in {"ready", "active"} and stage_index and projection.stages[stage_index - 1].status != "succeeded":
            raise ValueError("stage dependency is not satisfied")
        role_ref = None
        attempt_id = None
        if target == "active":
            if role_instance is None:
                raise ValueError("starting a stage requires a RoleInstance")
            current_revision = cast(PipelineRevision, self.store.resolve(projection.pipeline_revision))
            if (
                not stage_revision_is_valid(
                    self.store,
                    current_revision,
                    role_instance.pipeline_revision,
                    stage_id,
                    role_instance.stage_spec_digest,
                )
                or role_instance.stage_id != stage_id
                or role_instance.stage_spec_digest != stage.stage_spec_digest
            ):
                raise ValueError("RoleInstance is not pinned to the current stage revision")
            role_ref = self.store.write_immutable(role_instance, role_instance.role_instance_id)
            EvidenceManager(self.store).begin_stage(stage_id, role_instance)
            attempt_id = role_instance.attempt_id
        if target == "succeeded":
            if candidate is None:
                raise ValueError("succeeding a stage requires a candidate reference")
            resolved_candidate = self.store.resolve(candidate)
            if (
                getattr(resolved_candidate, "stage_id", None) != stage_id
                or getattr(resolved_candidate, "role_instance", None) != stage.active_role_instance
                or getattr(resolved_candidate, "attempt_id", None) != stage.attempt_id
                or getattr(resolved_candidate, "pipeline_revision", None) != stage.pipeline_revision
                or getattr(resolved_candidate, "outcome", None) != "succeeded"
            ):
                raise ValueError("candidate does not match the active stage role, attempt, and revision")
        self.store.append_event(
            run_id,
            {
                "attempt_id": attempt_id,
                "candidate": candidate.model_dump(mode="json") if candidate else None,
                "detail": detail,
                "operator_required": operator_required,
                "role_instance": role_ref.model_dump(mode="json") if role_ref else None,
                "stage_id": stage_id,
                "to_status": target,
                "type": "stage_transition",
            },
            expected_version=expected_state_revision,
        )
        return self.replay(run_id)

    def ready(self, run_id: str, stage_id: str, *, expected_state_revision: int) -> PipelineRunProjection:
        return self._transition(run_id, stage_id, "ready", expected_state_revision=expected_state_revision)

    stage_ready = ready

    def start(
        self, run_id: str, stage_id: str, role_instance: RoleInstance, *, expected_state_revision: int
    ) -> PipelineRunProjection:
        return self._transition(
            run_id, stage_id, "active", expected_state_revision=expected_state_revision, role_instance=role_instance
        )

    start_stage = start

    def succeed(
        self,
        run_id: str,
        stage_id: str,
        candidate: RecordRef | None = None,
        *,
        expected_state_revision: int,
        detail: str | None = None,
    ) -> PipelineRunProjection:
        return self._transition(
            run_id,
            stage_id,
            "succeeded",
            expected_state_revision=expected_state_revision,
            candidate=candidate,
            detail=detail,
        )

    succeed_stage = succeed

    def replace_candidate(
        self,
        run_id: str,
        stage_id: str,
        candidate: RecordRef,
        *,
        expected_state_revision: int,
        detail: str | None = None,
    ) -> PipelineRunProjection:
        """Replace a successful candidate after correction by the exact same role and attempt."""
        projection = self.replay(run_id)
        if projection.state_revision != expected_state_revision:
            raise RevisionConflict("pipeline state revision changed")
        stage = next((item for item in projection.stages if item.stage_id == stage_id), None)
        if stage is None or stage.status != "succeeded":
            raise ValueError("candidate replacement requires a succeeded stage")
        resolved = self.store.resolve(candidate)
        if (
            getattr(resolved, "stage_id", None) != stage_id
            or getattr(resolved, "role_instance", None) != stage.active_role_instance
            or getattr(resolved, "attempt_id", None) != stage.attempt_id
            or getattr(resolved, "pipeline_revision", None) != stage.pipeline_revision
            or getattr(resolved, "outcome", None) != "succeeded"
        ):
            raise ValueError("replacement candidate must use the exact active role, attempt, and revision")
        self.store.append_event(
            run_id,
            {
                "candidate": candidate.model_dump(mode="json"),
                "detail": detail,
                "stage_id": stage_id,
                "type": "candidate_replaced",
            },
            expected_version=expected_state_revision,
        )
        return self.replay(run_id)

    def block(
        self,
        run_id: str,
        stage_id: str,
        *,
        expected_state_revision: int,
        detail: str,
        operator_required: bool = False,
    ) -> PipelineRunProjection:
        return self._transition(
            run_id,
            stage_id,
            "blocked",
            expected_state_revision=expected_state_revision,
            detail=detail,
            operator_required=operator_required,
        )

    block_stage = block

    def fail(self, run_id: str, stage_id: str, *, expected_state_revision: int, detail: str) -> PipelineRunProjection:
        return self._transition(run_id, stage_id, "failed", expected_state_revision=expected_state_revision, detail=detail)

    fail_stage = fail

    def record_lead_decision(
        self,
        run_id: str,
        decision: LeadDecision,
        *,
        expected_state_revision: int,
        operator_required: bool = False,
    ) -> PipelineRunProjection:
        projection = self.replay(run_id)
        if projection.state_revision != expected_state_revision:
            raise RevisionConflict("pipeline state revision changed")
        allowed_subjects = {projection.plan, projection.pipeline_revision}
        allowed_subjects.update(stage.candidate for stage in projection.stages if stage.candidate is not None)
        allowed_subjects.update(stage.active_role_instance for stage in projection.stages if stage.active_role_instance is not None)
        if decision.subject not in allowed_subjects:
            raise ValueError("LeadDecision subject is unrelated to the current plan, revision, or stage")
        decision_ref = self.store.write_immutable(decision, decision.decision_id)
        self.store.append_event(
            run_id,
            {
                "decision": decision_ref.model_dump(mode="json"),
                "operator_required": operator_required,
                "outcome": decision.decision,
                "type": "lead_decision",
            },
            expected_version=expected_state_revision,
        )
        return self.replay(run_id)

    def approve_change_request(
        self,
        run_id: str,
        request: RecordRef | MailboxMessage,
        decision: LeadDecision,
        work_item: WorkItem | None = None,
        *,
        expected_state_revision: int,
        created_at: datetime | None = None,
        catalog: Catalog | None = None,
    ) -> PipelineRunProjection:
        request_message = cast(MailboxMessage, self.store.resolve(request)) if isinstance(request, RecordRef) else request
        request_ref = self.store.reference(request_message)
        try:
            stored_request = self.store.resolve(request_ref)
        except FileNotFoundError as exc:
            raise ValueError("pipeline change request must be a stored mailbox message") from exc
        if stored_request != request_message or not isinstance(request_message.body, PipelineChangeRequestBody):
            raise ValueError("pipeline change request must be a stored typed mailbox message")
        if not any(
            event.payload.get("type") == "submitted"
            and event.payload.get("message_id") == request_message.message_id
            for event in self.store.replay_events("mailbox")
        ):
            raise ValueError("pipeline change request must have a submitted mailbox event")
        request_body = request_message.body
        if decision.decision != "approve" or decision.subject != request_ref:
            raise ValueError("pipeline change requires an approving LeadDecision")
        if any(stage.stage not in {"architecture", "ux"} for stage in request_body.requested_stages):
            raise ValueError("pipeline change requests may select only optional architecture and ux stages")
        selected = tuple(stage.stage for stage in request_body.requested_stages if stage.stage in {"architecture", "ux"})
        resolved_catalog = catalog or self.catalog
        if resolved_catalog is None:
            raise ValueError("pipeline change compilation requires a Catalog")
        projection = self.replay(run_id)
        if projection.state_revision != expected_state_revision:
            raise RevisionConflict("pipeline state revision changed")
        parent = cast(PipelineRevision, self.store.resolve(projection.pipeline_revision))
        current_plan = cast(PipelinePlan, self.store.resolve(projection.plan))
        resolved_work_item = cast(WorkItem, self.store.resolve(current_plan.work_item))
        if work_item is not None and work_item != resolved_work_item:
            raise ValueError("caller WorkItem differs from the run plan WorkItem")
        sender_role = cast(RoleInstance, self.store.read_record("role_instance", cast(str, request_message.sender.role_instance_id)))
        discovery_candidate = cast(CandidateReport, self.store.resolve(request_body.discovery_candidate))
        discovery_stage = next((item for item in projection.stages if item.stage_id == "discovery"), None)
        if (
            request_message.sender.kind != "agent"
            or discovery_stage is None
            or discovery_stage.status != "succeeded"
            or discovery_stage.active_role_instance != self.store.reference(sender_role)
            or discovery_stage.candidate != request_body.discovery_candidate
            or discovery_candidate.stage != "discovery"
            or discovery_candidate.outcome != "succeeded"
            or discovery_candidate.role_instance != self.store.reference(sender_role)
        ):
            raise ValueError("pipeline change request requires its successful Discovery candidate and sender")
        operation_id = f"pipeline-revision-{run_id}-{parent.revision_number + 1}"
        revision_id = f"{run_id}-revision-{parent.revision_number + 1}"
        journaled = self.store.journaled_record(operation_id, "pipeline_revision", revision_id)
        revision_created_at = created_at or (
            cast(PipelineRevision, journaled).created_at if journaled is not None else self._now(None)
        )
        compiled = compile_pipeline(
            resolved_catalog,
            resolved_work_item,
            selected,
            decision.decided_by,
            revision_created_at,
            pipeline_id="adaptive-verified-delivery",
        )
        new_stages = compiled.plan.stages
        old_by_id = {stage.stage_id: stage for stage in parent.stages}
        projected_by_id = {stage.stage_id: stage for stage in projection.stages}
        for stage_id, state in projected_by_id.items():
            if state.status in {"pending", "ready"}:
                continue
            replacement = next((stage for stage in new_stages if stage.stage_id == stage_id), None)
            if replacement is None or pipeline_stage_digest(replacement) != state.stage_spec_digest:
                raise ValueError("a pipeline revision cannot change active or terminal stages")
        first_unstarted = next(
            (
                index
                for index, stage in enumerate(new_stages)
                if projected_by_id.get(stage.stage_id, None) is None
                or projected_by_id[stage.stage_id].status in {"pending", "ready"}
            ),
            None,
        )
        if first_unstarted is None:
            raise ValueError("completed pipeline has no future stage to revise")
        applies = new_stages[first_unstarted]
        frozen = new_stages[:first_unstarted]
        for stage in frozen:
            parent_stage = old_by_id.get(stage.stage_id)
            if parent_stage is None or pipeline_stage_digest(parent_stage) != pipeline_stage_digest(stage):
                raise ValueError("frozen stages must exactly match the parent revision")
        plan_ref = self.store.reference(compiled.plan)
        decision_ref = self.store.reference(decision)
        revision = PipelineRevision(
            schema_version="2.0",
            kind="pipeline_revision",
            revision_id=revision_id,
            plan=plan_ref,
            revision_number=parent.revision_number + 1,
            parent_revision=projection.pipeline_revision,
            stages=new_stages,
            frozen_stage_ids=tuple(stage.stage_id for stage in frozen),
            frozen_stage_digests=tuple(
                FrozenStageDigest(stage_id=stage.stage_id, stage_spec_digest=pipeline_stage_digest(stage)) for stage in frozen
            ),
            parent_stage_digests=tuple(
                ParentStageDigest(stage_id=stage.stage_id, digest=pipeline_stage_digest(old_by_id[stage.stage_id]))
                for stage in frozen
            ),
            applies_from_stage=applies.stage_id,
            reason=request_body.rationale,
            approving_decision=decision_ref,
            created_at=revision_created_at,
        )
        with self.store.run_lock(run_id):
            if len(self.store.replay_events(run_id, _locked=True)) != expected_state_revision:
                raise RevisionConflict("pipeline state revision changed")
            revision_ref = self.store.reference(revision)
            payload = {
                "approving_decision": decision_ref.model_dump(mode="json"),
                "change_request": request_ref.model_dump(mode="json"),
                "plan": plan_ref.model_dump(mode="json"),
                "pipeline_revision": revision_ref.model_dump(mode="json"),
                "stages": [
                    {"stage_id": stage.stage_id, "stage_spec_digest": pipeline_stage_digest(stage)}
                    for stage in revision.stages
                ],
                "type": "revision_committed",
            }
            self.store.commit_records_event(
                operation_id,
                (
                    (compiled.plan, compiled.plan.plan_id),
                    (decision, decision.decision_id),
                    (revision, revision.revision_id),
                ),
                run_id,
                payload,
                expected_version=expected_state_revision,
                _locked=True,
            )
        return self.replay(run_id)

    approve_change = approve_change_request


__all__ = [
    "PipelineRunProjection",
    "PipelineRuntime",
    "StageProjection",
    "StageStatus",
    "resolve_revision_ancestry",
    "stage_revision_is_valid",
]
