from __future__ import annotations

import json
import tomllib
from datetime import datetime, timezone
from math import inf, nan

import pytest
from pydantic import ValidationError

from codexteam_tools.v2.canonical import canonical_json, canonical_sha256, verify_digest
from codexteam_tools.v2.models import (
    SCHEMA_VERSION,
    AcceptanceCriterion,
    ActorRef,
    AgentSpec,
    Assignment,
    AssuranceDomain,
    AssuranceDisposition,
    AssuranceReport,
    BackendDefinition,
    Capability,
    CandidateReport,
    CandidateSeal,
    ChangeEntry,
    ChangeSet,
    CriterionDisposition,
    CriterionResult,
    DefinitionRef,
    EvidenceType,
    EffectivePermissionRequest,
    FrozenStageDigest,
    GuidanceBundle,
    GuidanceModule,
    LeadDecision,
    LeadDecisionBody,
    LifecycleEvent,
    LifecycleEventType,
    MailboxMessage,
    ManifestEntry,
    ModelProfile,
    PermissionPolicy,
    PermissionOperation,
    PermissionResource,
    PermissionRule,
    PipelineDefinition,
    PipelinePlan,
    PipelineRevision,
    PipelineStageSpec,
    PolicyException,
    PolicyRuleSnapshot,
    ParentStageDigest,
    ProjectPolicy,
    ProjectManifest,
    ProjectState,
    RecordRef,
    ReviewDecision,
    SemanticFinding,
    RequiredStageCandidate,
    Responsibility,
    RoleInstance,
    RunBinding,
    TOP_LEVEL_MODELS,
    VerificationCriterion,
    VerificationPlan,
    VerificationReceipt,
    VerificationRun,
    WorkItem,
    build_candidate_seal_payload,
    build_role_instance_payload,
    create_candidate_seal,
    evaluate_effective_permission,
    build_manifest_root_digest,
    intersect_permission_policies,
    pipeline_stage_digest,
    project_path_pattern_matches,
    validate_wire,
)
from codexteam_tools.v2.schema_generation import SEMANTIC_COMMENT, SCHEMA_DIRECTORY, check_schemas, schema_filename

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
NOW = datetime(2026, 8, 7, tzinfo=timezone.utc)


def definition(kind: str = "agent_spec", *, digest: str = DIGEST_A) -> DefinitionRef:
    return DefinitionRef(
        definition_id=f"ct2.{kind}",
        kind=kind,
        definition_version="1",
        digest=digest,
    )


def record(kind: str = "work_item", *, record_id: str = "record-1", digest: str = DIGEST_A) -> RecordRef:
    return RecordRef(record_id=record_id, kind=kind, digest=digest)


def lead() -> ActorRef:
    return ActorRef(actor_id="lead-1", kind="project_lead")


def launcher() -> ActorRef:
    return ActorRef(actor_id="launcher-1", kind="launcher")


def orchestrator() -> ActorRef:
    return ActorRef(actor_id="orchestrator-1", kind="orchestrator")


def agent(actor_id: str = "agent-1") -> ActorRef:
    return ActorRef(actor_id=actor_id, kind="agent", role_instance_id=f"role-{actor_id}")


def criterion(criterion_id: str = "criterion-1") -> AcceptanceCriterion:
    return AcceptanceCriterion(
        id=criterion_id,
        statement="The canary passes",
        required_evidence_types=(EvidenceType.TEST_OUTPUT,),
    )


def work_item_data() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "work_item",
        "work_item_id": "work-1",
        "title": "Canary",
        "objective": "Exercise v2",
        "acceptance_criteria": (criterion(),),
    }


def stage(stage: str, *, dependencies: tuple[str, ...] = ()) -> PipelineStageSpec:
    return PipelineStageSpec(
        stage_id=f"{stage}-stage",
        stage=stage,
        agent_spec=definition(),
        dependencies=dependencies,
        optional=stage in {"architecture", "ux"},
        assurance_domain=AssuranceDomain.SECURITY_PRIVACY if stage == "assurance" else None,
    )


def canary_stages(*, architecture: bool = False, ux: bool = False) -> tuple[PipelineStageSpec, ...]:
    discovery = stage("discovery")
    selected = [discovery]
    previous = discovery
    if architecture:
        previous = stage("architecture", dependencies=(previous.stage_id,))
        selected.append(previous)
    if ux:
        previous = stage("ux", dependencies=(previous.stage_id,))
        selected.append(previous)
    implementation = stage("implementation", dependencies=(previous.stage_id,))
    verification = stage("verification", dependencies=(implementation.stage_id,))
    assurance = stage("assurance", dependencies=(verification.stage_id,))
    review = stage("review", dependencies=(assurance.stage_id,))
    return (*selected, implementation, verification, assurance, review)


def permission_policy(
    policy_id: str,
    *rules: PermissionRule,
) -> PermissionPolicy:
    return PermissionPolicy(
        schema_version=SCHEMA_VERSION,
        kind="permission_policy",
        definition_version="1",
        policy_id=policy_id,
        default_effect="deny",
        rules=rules,
    )


def allow_write(path: str = "src/app.py", *, effect: str = "allow") -> PermissionRule:
    return PermissionRule(
        rule_id=f"{effect}-{path.replace('/', '-').replace('*', 'wildcard')}",
        exception_class="soft",
        effect=effect,
        operation=PermissionOperation.WRITE,
        resource=PermissionResource.PROJECT_PATH,
        resource_pattern=path,
    )


def receipt_data() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "verification_receipt",
        "verification_receipt_id": "receipt-1",
        "plan": record("verification_plan"),
        "candidate": record("candidate_report"),
        "change_set": record("change_set"),
        "workspace_digest": DIGEST_A,
        "run_bindings": (
            RunBinding(
                run=record("verification_run"),
                plan=record("verification_plan"),
                candidate=record("candidate_report"),
                change_set=record("change_set"),
                workspace_digest=DIGEST_A,
            ),
        ),
        "criterion_ids": ("criterion-1",),
        "criterion_results": (
            CriterionResult(
                criterion_id="criterion-1",
                command_indexes=(0,),
                disposition="pass",
                evidence=(record("evidence_artifact"),),
            ),
        ),
        "accepted": True,
        "producer_role_instance_id": "role-producer",
        "issued_by": agent("verifier"),
        "issued_at": NOW,
    }


def candidate_data() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "candidate_report",
        "candidate_report_id": "candidate-1",
        "work_item": record("work_item"),
        "pipeline_revision": record("pipeline_revision"),
        "assignment": record("assignment"),
        "role_instance": record("role_instance"),
        "stage": "implementation",
        "stage_id": "implementation-stage",
        "stage_spec_digest": DIGEST_A,
        "attempt_id": "attempt-1",
        "context_pack": record("context_pack"),
        "change_set": record("change_set"),
        "outcome": "succeeded",
        "criterion_ids": ("criterion-1",),
        "criterion_dispositions": (
            CriterionDisposition(
                criterion_id="criterion-1",
                disposition="claimed_satisfied",
                evidence=(record("evidence_artifact"),),
                evidence_types=(EvidenceType.TEST_OUTPUT,),
            ),
        ),
        "evidence": (record("evidence_artifact"),),
        "produced_at": NOW,
    }


def seal_payload_data() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "project_id": "project-1",
        "work_item": record("work_item"),
        "pipeline_revision": record("pipeline_revision"),
        "role_instances": (record("role_instance"),),
        "context_packs": (record("context_pack"),),
        "required_stage_ids": ("implementation-stage",),
        "stage_candidates": (
            RequiredStageCandidate(stage_id="implementation-stage", candidate=record("candidate_report")),
        ),
        "base_manifest": record("project_manifest", record_id="base-manifest"),
        "final_manifest": record("project_manifest", record_id="final-manifest", digest=DIGEST_B),
        "cumulative_change_set": record("change_set"),
        "verification_receipts": (record("verification_receipt"),),
        "assurance_report": record("assurance_report"),
        "acceptance_review": record("review_decision"),
        "lead_decision": record("lead_decision"),
        "compiler_version": "codexteam-v2-compiler/1",
        "verification_accepted": True,
        "verification_fresh": True,
        "assurance_accepted": True,
        "acceptance_accepted": True,
        "lead_approved": True,
    }


def test_schema_version_and_kind_are_required_on_ingress() -> None:
    for missing in ("schema_version", "kind"):
        data = work_item_data()
        data.pop(missing)
        with pytest.raises(ValidationError, match=missing):
            WorkItem.model_validate(data)


def test_reusable_definitions_and_refs_pin_definition_version() -> None:
    with pytest.raises(ValidationError, match="definition_version"):
        DefinitionRef(definition_id="ct2.agent", kind="agent_spec", digest=DIGEST_A)
    with pytest.raises(ValidationError, match="definition_version"):
        PermissionPolicy(
            schema_version=SCHEMA_VERSION,
            kind="permission_policy",
            policy_id="policy-1",
            default_effect="deny",
            rules=(),
        )


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        WorkItem(**work_item_data(), unknown=True)


def test_validate_wire_accepts_json_and_toml_containers_without_scalar_coercion() -> None:
    json_data = json.loads(
        '{"schema_version":"2.0","kind":"work_item","work_item_id":"work-1","title":"Canary",'
        '"objective":"Exercise v2","acceptance_criteria":[{"id":"criterion-1","statement":"Pass",'
        '"required_evidence_types":["test_output"]}]}'
    )
    assert isinstance(validate_wire(WorkItem, json_data), WorkItem)
    toml_data = tomllib.loads(
        'schema_version = "2.0"\nkind = "work_item"\nwork_item_id = "work-1"\ntitle = "Canary"\n'
        'objective = "Exercise v2"\n[[acceptance_criteria]]\nid = "criterion-1"\nstatement = "Pass"\n'
        'required_evidence_types = ["test_output"]\n'
    )
    assert isinstance(validate_wire(WorkItem, toml_data), WorkItem)
    json_data["title"] = 1
    with pytest.raises(ValidationError, match="string"):
        validate_wire(WorkItem, json_data)


def test_canonical_digest_is_stable_and_mapping_order_independent() -> None:
    left = {"b": [2, 1], "a": {"y": True, "x": None}}
    right = {"a": {"x": None, "y": True}, "b": [2, 1]}
    assert canonical_json(left) == canonical_json(right)
    assert canonical_sha256(left) == canonical_sha256(right)
    assert verify_digest(right, canonical_sha256(left))
    assert not verify_digest(right, DIGEST_A)


def test_canonical_mapping_keys_cannot_collide_through_coercion() -> None:
    with pytest.raises(TypeError, match="string keys"):
        canonical_json({1: "integer", "1": "string"})


def test_model_digest_hashes_the_validated_model_dump() -> None:
    item = WorkItem(**work_item_data())
    assert canonical_sha256(item) == canonical_sha256(item.model_dump(mode="python", by_alias=True))


@pytest.mark.parametrize("value", (nan, inf, -inf))
def test_nonfinite_floats_are_rejected_globally(value: float) -> None:
    with pytest.raises(ValidationError, match="finite number"):
        VerificationRun(
            schema_version=SCHEMA_VERSION,
            kind="verification_run",
            verification_run_id="run-1",
            plan=record("verification_plan"),
            candidate=record("candidate_report"),
            change_set=record("change_set"),
            workspace_digest=DIGEST_A,
            command=("pytest",),
            exit_code=0,
            duration_seconds=value,
            evidence=(record("evidence_artifact"),),
            started_at=NOW,
            finished_at=NOW,
        )


@pytest.mark.parametrize("path", ("/etc/passwd", ".", "..", "src/../secret", "src\\file.py", "bad\x00name"))
def test_project_paths_reject_unsafe_values(path: str) -> None:
    data = work_item_data()
    data["approved_scope"] = (path,)
    with pytest.raises(ValidationError):
        WorkItem(**data)


def test_work_item_criteria_require_stable_unique_ids_and_evidence_types() -> None:
    data = work_item_data()
    data["acceptance_criteria"] = (criterion(), criterion())
    with pytest.raises(ValidationError, match="criterion IDs must be unique"):
        WorkItem(**data)
    with pytest.raises(ValidationError, match="at least one evidence type"):
        AcceptanceCriterion(id="criterion-1", statement="Pass", required_evidence_types=())


def test_assignment_domain_is_present_if_and_only_if_stage_is_assurance() -> None:
    common = {
        "schema_version": SCHEMA_VERSION,
        "kind": "assignment",
        "assignment_id": "assignment-1",
        "work_item": record(),
        "agent_spec": definition(),
        "scope": ("src",),
    }
    Assignment(**common, stage="assurance", assurance_domain=AssuranceDomain.SECURITY_PRIVACY)
    with pytest.raises(ValidationError, match="if and only if"):
        Assignment(**common, stage="assurance")
    with pytest.raises(ValidationError, match="if and only if"):
        Assignment(**common, stage="implementation", assurance_domain=AssuranceDomain.ACCESSIBILITY)


def test_pipeline_requires_nonempty_unique_dag_with_first_canary_stages() -> None:
    common = {
        "schema_version": SCHEMA_VERSION,
        "kind": "pipeline_definition",
        "definition_version": "1",
        "pipeline_id": "pipeline-1",
        "name": "Canary",
    }
    PipelineDefinition(**common, stages=canary_stages())
    with pytest.raises(ValidationError, match="nonempty"):
        PipelineDefinition(**common, stages=())
    duplicate = canary_stages() + (stage("implementation"),)
    with pytest.raises(ValidationError, match="stage IDs must be unique"):
        PipelineDefinition(**common, stages=duplicate)
    discovery, implementation, verification, assurance, review = canary_stages()
    parallel = (discovery, implementation.model_copy(update={"dependencies": ()}), verification, assurance, review)
    with pytest.raises(ValidationError, match="serial chain"):
        PipelineDefinition(**common, stages=parallel)
    missing = (discovery, implementation, assurance.model_copy(update={"dependencies": (implementation.stage_id,)}), review)
    with pytest.raises(ValidationError, match="exactly one verification"):
        PipelineDefinition(**common, stages=missing)


def test_pipeline_rejects_unknown_dependency_and_requires_lead_approval() -> None:
    stages = list(canary_stages())
    stages[0] = stages[0].model_copy(update={"dependencies": ("missing-stage",)})
    with pytest.raises(ValidationError, match="unknown dependencies"):
        PipelineDefinition(
            schema_version=SCHEMA_VERSION,
            kind="pipeline_definition",
            definition_version="1",
            pipeline_id="pipeline-1",
            name="Canary",
            stages=tuple(stages),
        )
    with pytest.raises(ValidationError, match="project_lead"):
        PipelinePlan(
            schema_version=SCHEMA_VERSION,
            kind="pipeline_plan",
            plan_id="plan-1",
            pipeline=definition("pipeline_definition"),
            work_item=record("work_item"),
            stages=canary_stages(),
            approved_by=ActorRef(actor_id="operator-1", kind="operator"),
            approved_at=NOW,
        )


@pytest.mark.parametrize(("architecture", "ux"), ((False, False), (True, False), (False, True), (True, True)))
def test_first_canary_accepts_all_optional_stage_variants(architecture: bool, ux: bool) -> None:
    PipelineDefinition(
        schema_version=SCHEMA_VERSION,
        kind="pipeline_definition",
        definition_version="1",
        pipeline_id="pipeline-1",
        name="Canary",
        stages=canary_stages(architecture=architecture, ux=ux),
    )


def test_first_canary_rejects_missing_discovery_and_architecture_after_ux() -> None:
    common = {
        "schema_version": SCHEMA_VERSION,
        "kind": "pipeline_definition",
        "definition_version": "1",
        "pipeline_id": "pipeline-1",
        "name": "Canary",
    }
    with pytest.raises(ValidationError, match="discovery"):
        missing_discovery = canary_stages()[1:]
        PipelineDefinition(
            **common,
            stages=(missing_discovery[0].model_copy(update={"dependencies": ()}), *missing_discovery[1:]),
        )
    stages = canary_stages(architecture=True, ux=True)
    reordered = (stages[0], stages[2], stages[1], *stages[3:])
    with pytest.raises(ValidationError, match="exact serial stage order"):
        PipelineDefinition(**common, stages=reordered)


def test_pipeline_revision_pins_frozen_specs_and_applies_from_stage() -> None:
    stages = canary_stages()
    frozen = stages[:3]
    common = {
        "schema_version": SCHEMA_VERSION,
        "kind": "pipeline_revision",
        "revision_id": "revision-1",
        "plan": record("pipeline_plan"),
        "revision_number": 1,
        "stages": stages,
        "frozen_stage_ids": tuple(item.stage_id for item in frozen),
        "frozen_stage_digests": tuple(
            FrozenStageDigest(stage_id=item.stage_id, stage_spec_digest=pipeline_stage_digest(item))
            for item in frozen
        ),
        "parent_stage_digests": (),
        "applies_from_stage": "assurance-stage",
        "reason": "Pin initial canary",
        "approving_decision": record("lead_decision"),
        "created_at": NOW,
    }
    PipelineRevision(**common)
    with pytest.raises(ValidationError, match="applies_from_stage"):
        PipelineRevision(**{**common, "applies_from_stage": "missing"})
    changed_digest = (
        common["frozen_stage_digests"][0],
        FrozenStageDigest(stage_id="implementation-stage", stage_spec_digest=DIGEST_B),
        *common["frozen_stage_digests"][2:],
    )
    with pytest.raises(ValidationError, match="differs from its pinned digest"):
        PipelineRevision(**{**common, "frozen_stage_digests": changed_digest})
    with pytest.raises(ValidationError, match="parent revision"):
        PipelineRevision(**{**common, "revision_number": 2, "revision_id": "revision-2"})


def test_pipeline_revision_frozen_stage_must_equal_parent_digest() -> None:
    stages = canary_stages()
    frozen = stages[:2]
    frozen_digests = tuple(
        FrozenStageDigest(stage_id=item.stage_id, stage_spec_digest=pipeline_stage_digest(item)) for item in frozen
    )
    common = {
        "schema_version": SCHEMA_VERSION,
        "kind": "pipeline_revision",
        "revision_id": "revision-2",
        "plan": record("pipeline_plan"),
        "revision_number": 2,
        "parent_revision": record("pipeline_revision"),
        "stages": stages,
        "frozen_stage_ids": tuple(item.stage_id for item in frozen),
        "frozen_stage_digests": frozen_digests,
        "parent_stage_digests": tuple(
            ParentStageDigest(stage_id=item.stage_id, digest=pipeline_stage_digest(item)) for item in frozen
        ),
        "applies_from_stage": "verification-stage",
        "reason": "Revise verification onward",
        "approving_decision": record("lead_decision"),
        "created_at": NOW,
    }
    PipelineRevision(**common)
    changed = frozen[1].model_copy(update={"agent_spec": definition(digest=DIGEST_B)})
    changed_stages = (frozen[0], changed, *stages[2:])
    changed_frozen = (
        frozen_digests[0],
        FrozenStageDigest(stage_id=changed.stage_id, stage_spec_digest=pipeline_stage_digest(changed)),
    )
    with pytest.raises(ValidationError, match="parent-stage digest"):
        PipelineRevision(**{**common, "stages": changed_stages, "frozen_stage_digests": changed_frozen})


def test_actor_role_instance_identity_is_conditional() -> None:
    agent()
    lead()
    with pytest.raises(ValidationError, match="required for agents"):
        ActorRef(actor_id="agent-1", kind="agent")
    with pytest.raises(ValidationError, match="forbidden for non-agents"):
        ActorRef(actor_id="lead-1", kind="project_lead", role_instance_id="role-1")


def test_role_instance_pins_pipeline_stage_attempt_and_effective_policy() -> None:
    data = {
        "schema_version": SCHEMA_VERSION,
        "kind": "role_instance",
        "role_instance_id": "role-1",
        "assignment": record("assignment"),
        "pipeline_revision": record("pipeline_revision"),
        "stage_id": "implementation-stage",
        "stage_spec_digest": DIGEST_A,
        "attempt_id": "attempt-1",
        "agent_spec": definition("agent_spec"),
        "responsibility": definition("responsibility"),
        "responsibility_permission_ceiling": definition("permission_policy", digest=DIGEST_C),
        "capabilities": (definition("capability"),),
        "permission_policy": definition("permission_policy"),
        "project_policy": definition("project_policy"),
        "operator_grants": (definition("permission_policy", digest=DIGEST_B),),
        "operator_grants_authorization": record("lead_decision"),
        "assignment_scope": ("src/**",),
        "guidance_bundle": definition("guidance_bundle"),
        "model_profile": definition("model_profile"),
        "backend": definition("backend_definition"),
        "backend_supported_operations": (PermissionOperation.READ, PermissionOperation.WRITE),
        "backend_supported_resources": (PermissionResource.PROJECT_PATH,),
        "backend_limitations": (),
        "host_isolation_authorization": None,
    }
    data["effective_policy_digest"] = canonical_sha256(
        {
            name: data[name]
            for name in (
                "assignment", "pipeline_revision", "stage_id", "stage_spec_digest", "attempt_id",
                "responsibility_permission_ceiling", "permission_policy", "project_policy", "operator_grants",
                "operator_grants_authorization", "assignment_scope", "backend", "backend_supported_operations",
                "backend_supported_resources", "backend_limitations", "host_isolation_authorization",
            )
        }
    )
    data["resolved_digest"] = canonical_sha256(data)
    RoleInstance(**data)
    for field in ("pipeline_revision", "stage_id", "stage_spec_digest", "attempt_id", "effective_policy_digest"):
        incomplete = dict(data)
        incomplete.pop(field)
        with pytest.raises(ValidationError, match=field):
            RoleInstance(**incomplete)


def test_role_instance_rejects_swapped_kinds_and_changed_component_digest() -> None:
    data = {
        "schema_version": SCHEMA_VERSION,
        "kind": "role_instance",
        "role_instance_id": "role-1",
        "assignment": record("assignment"),
        "pipeline_revision": record("pipeline_revision"),
        "stage_id": "implementation-stage",
        "stage_spec_digest": DIGEST_A,
        "attempt_id": "attempt-1",
        "agent_spec": definition("agent_spec"),
        "responsibility": definition("responsibility"),
        "responsibility_permission_ceiling": definition("permission_policy", digest=DIGEST_C),
        "capabilities": (definition("capability"),),
        "permission_policy": definition("permission_policy"),
        "project_policy": definition("project_policy"),
        "operator_grants": (),
        "operator_grants_authorization": None,
        "assignment_scope": ("src/**",),
        "guidance_bundle": definition("guidance_bundle"),
        "model_profile": definition("model_profile"),
        "backend": definition("backend_definition"),
        "backend_supported_operations": (PermissionOperation.READ,),
        "backend_supported_resources": (PermissionResource.PROJECT_PATH,),
        "backend_limitations": (),
        "host_isolation_authorization": None,
    }
    data["effective_policy_digest"] = canonical_sha256(
        {
            name: data[name]
            for name in (
                "assignment", "pipeline_revision", "stage_id", "stage_spec_digest", "attempt_id",
                "responsibility_permission_ceiling", "permission_policy", "project_policy", "operator_grants",
                "operator_grants_authorization", "assignment_scope", "backend", "backend_supported_operations",
                "backend_supported_resources", "backend_limitations", "host_isolation_authorization",
            )
        }
    )
    data["resolved_digest"] = canonical_sha256(data)
    with pytest.raises(ValidationError, match="capabilities"):
        RoleInstance(**{**data, "capabilities": (definition("guidance_bundle"),)})
    changed = {**data, "backend": definition("backend_definition", digest=DIGEST_B)}
    with pytest.raises(ValidationError, match="effective_policy_digest"):
        RoleInstance(**changed)


def test_role_instance_factory_resolves_component_digests_and_rejects_changed_component() -> None:
    backend = BackendDefinition(
        schema_version=SCHEMA_VERSION,
        kind="backend_definition",
        definition_version="1",
        backend_id="backend-1",
        provider="local",
        command=("agent",),
        supported_operations=(PermissionOperation.WRITE,),
        supported_resources=(PermissionResource.PROJECT_PATH,),
    )
    backend_ref = DefinitionRef(
        definition_id=backend.backend_id,
        kind=backend.kind,
        definition_version=backend.definition_version,
        digest=canonical_sha256(backend),
    )
    model_profile = ModelProfile(
        schema_version=SCHEMA_VERSION,
        kind="model_profile",
        definition_version="1",
        profile_id="model-1",
        model="test-model",
        backend=backend_ref,
    )
    capability = Capability(
        schema_version=SCHEMA_VERSION,
        kind="capability",
        definition_version="1",
        capability_id="capability-1",
        name="Coding",
        description="Edit code",
    )
    permission = permission_policy("permission-1", allow_write())
    permission_ref = DefinitionRef(
        definition_id=permission.policy_id,
        kind=permission.kind,
        definition_version=permission.definition_version,
        digest=canonical_sha256(permission),
    )
    responsibility = Responsibility(
        schema_version=SCHEMA_VERSION,
        kind="responsibility",
        definition_version="1",
        responsibility_id="responsibility-1",
        name="Developer",
        description="Implement",
        permission_ceiling=permission_ref,
    )
    project = ProjectPolicy(
        schema_version=SCHEMA_VERSION,
        kind="project_policy",
        definition_version="1",
        project_policy_id="project-policy-1",
        default_effect="deny",
        rules=(allow_write(),),
    )
    guidance = GuidanceBundle(
        schema_version=SCHEMA_VERSION,
        kind="guidance_bundle",
        definition_version="1",
        bundle_id="guidance-1",
        modules=(),
        digest=DIGEST_A,
    )
    refs = {
        "responsibility": DefinitionRef(definition_id=responsibility.responsibility_id, kind=responsibility.kind, definition_version="1", digest=canonical_sha256(responsibility)),
        "capability": DefinitionRef(definition_id=capability.capability_id, kind=capability.kind, definition_version="1", digest=canonical_sha256(capability)),
        "permission": permission_ref,
        "guidance": DefinitionRef(definition_id=guidance.bundle_id, kind=guidance.kind, definition_version="1", digest=canonical_sha256(guidance)),
        "model": DefinitionRef(definition_id=model_profile.profile_id, kind=model_profile.kind, definition_version="1", digest=canonical_sha256(model_profile)),
    }
    spec = AgentSpec(
        schema_version=SCHEMA_VERSION,
        kind="agent_spec",
        definition_version="1",
        agent_spec_id="agent-spec-1",
        responsibility=refs["responsibility"],
        capabilities=(refs["capability"],),
        permission_policy=refs["permission"],
        guidance_bundle=refs["guidance"],
        model_profile=refs["model"],
    )
    common = {
        "role_instance_id": "role-1",
        "assignment": record("assignment"),
        "pipeline_revision": record("pipeline_revision"),
        "stage_id": "implementation-stage",
        "stage_spec_digest": DIGEST_A,
        "attempt_id": "attempt-1",
        "agent_spec": spec,
        "responsibility": responsibility,
        "responsibility_permission_ceiling": permission,
        "capabilities": (capability,),
        "permission_policy": permission,
        "project_policy": project,
        "operator_grants": (),
        "operator_grants_authorization": None,
        "assignment_scope": ("src/**",),
        "guidance_bundle": guidance,
        "model_profile": model_profile,
        "backend": backend,
    }
    role = build_role_instance_payload(**common)
    assert role.resolved_digest == canonical_sha256(role.model_dump(mode="python", exclude={"resolved_digest"}))
    changed_scope = build_role_instance_payload(**{**common, "assignment_scope": ("tests/**",)})
    assert changed_scope.effective_policy_digest != role.effective_policy_digest
    changed_ceiling = permission.model_copy(update={"policy_id": "permission-ceiling-2"})
    changed_ceiling_ref = DefinitionRef(
        definition_id=changed_ceiling.policy_id,
        kind=changed_ceiling.kind,
        definition_version=changed_ceiling.definition_version,
        digest=canonical_sha256(changed_ceiling),
    )
    changed_responsibility = responsibility.model_copy(update={"permission_ceiling": changed_ceiling_ref})
    changed_responsibility_ref = DefinitionRef(
        definition_id=changed_responsibility.responsibility_id,
        kind=changed_responsibility.kind,
        definition_version=changed_responsibility.definition_version,
        digest=canonical_sha256(changed_responsibility),
    )
    changed_responsibility_spec = spec.model_copy(update={"responsibility": changed_responsibility_ref})
    changed_ceiling_role = build_role_instance_payload(
        **{
            **common,
            "agent_spec": changed_responsibility_spec,
            "responsibility": changed_responsibility,
            "responsibility_permission_ceiling": changed_ceiling,
        }
    )
    assert changed_ceiling_role.effective_policy_digest != role.effective_policy_digest
    changed_backend = backend.model_copy(
        update={"supported_operations": (PermissionOperation.READ, PermissionOperation.WRITE)}
    )
    changed_backend_ref = DefinitionRef(
        definition_id=changed_backend.backend_id,
        kind=changed_backend.kind,
        definition_version=changed_backend.definition_version,
        digest=canonical_sha256(changed_backend),
    )
    changed_profile = model_profile.model_copy(update={"backend": changed_backend_ref})
    changed_profile_ref = DefinitionRef(
        definition_id=changed_profile.profile_id,
        kind=changed_profile.kind,
        definition_version=changed_profile.definition_version,
        digest=canonical_sha256(changed_profile),
    )
    changed_spec = spec.model_copy(update={"model_profile": changed_profile_ref})
    changed_backend_role = build_role_instance_payload(
        **{
            **common,
            "agent_spec": changed_spec,
            "model_profile": changed_profile,
            "backend": changed_backend,
        }
    )
    assert changed_backend_role.effective_policy_digest != role.effective_policy_digest
    changed_capability = capability.model_copy(update={"description": "Changed"})
    with pytest.raises(ValueError, match="does not match the agent_spec"):
        build_role_instance_payload(**{**common, "capabilities": (changed_capability,)})


def test_lead_and_reviewer_actions_enforce_actor_authority() -> None:
    with pytest.raises(ValidationError, match="project_lead"):
        LeadDecision(
            schema_version=SCHEMA_VERSION,
            kind="lead_decision",
            decision_id="decision-1",
            decision="approve",
            subject=record("candidate_report"),
            rationale="Approve",
            decided_by=agent(),
            decided_at=NOW,
        )
    with pytest.raises(ValidationError, match="reviewer must be an agent"):
        ReviewDecision(
            schema_version=SCHEMA_VERSION,
            kind="review_decision",
                review_decision_id="review-1",
                candidate=record("candidate_report"),
                producer_role_instance_id="role-producer",
            decision="RETURN",
            rationale="Needs work",
            reviewer=lead(),
            decided_at=NOW,
        )


def test_mailbox_routes_are_bipartite_and_typed_authority_is_enforced() -> None:
    common = {
        "schema_version": SCHEMA_VERSION,
        "kind": "mailbox_message",
        "message_id": "message-1",
        "correlation_id": "correlation-1",
        "idempotency_key": "idempotency-1",
        "created_at": NOW,
        "body": {"kind": "question", "question": "Proceed?"},
    }
    MailboxMessage(**common, sender=agent(), recipient=orchestrator())
    MailboxMessage(**common, sender=orchestrator(), recipient=agent())
    with pytest.raises(ValidationError, match="mailbox routes"):
        MailboxMessage(**common, sender=agent("one"), recipient=agent("two"))
    body = LeadDecisionBody(kind="lead_decision", decision=record("lead_decision"))
    MailboxMessage(**{**common, "body": body}, sender=lead(), recipient=agent())
    with pytest.raises(ValidationError, match="project_lead"):
        MailboxMessage(**{**common, "body": body}, sender=orchestrator(), recipient=agent())


def test_policy_exception_only_accepts_soft_policy_rules_with_evidence() -> None:
    common = {
        "schema_version": SCHEMA_VERSION,
        "kind": "policy_exception",
        "policy_exception_id": "exception-1",
        "scope": ("src",),
        "reason": "Temporary soft-rule waiver",
        "evidence": (record("evidence_artifact"),),
        "compensating_verification": "Run focused checks",
        "expires_at": NOW,
        "approving_lead_decision": record("lead_decision"),
    }
    permission_rule = allow_write()
    soft_rule = PolicyRuleSnapshot(
        policy=definition("project_policy"),
        rule=permission_rule,
        rule_digest=canonical_sha256(permission_rule),
    )
    PolicyException(**common, rule=soft_rule)
    hard_permission_rule = permission_rule.model_copy(update={"exception_class": "hard"})
    hard_rule = PolicyRuleSnapshot(
        policy=soft_rule.policy,
        rule=hard_permission_rule,
        rule_digest=canonical_sha256(hard_permission_rule),
    )
    with pytest.raises(ValidationError, match="hard policy rules cannot be excepted"):
        PolicyException(**common, rule=hard_rule)
    with pytest.raises(ValidationError, match="requires evidence"):
        PolicyException(**{**common, "evidence": ()}, rule=soft_rule)
    with pytest.raises(ValidationError, match="Extra inputs"):
        PolicyException(**common, rule=soft_rule, category="caller-controlled")


def test_policy_rule_snapshot_rejects_relabeling_without_digest_update() -> None:
    soft = allow_write()
    with pytest.raises(ValidationError, match="rule_digest"):
        PolicyRuleSnapshot(
            policy=definition("permission_policy"),
            rule=soft.model_copy(update={"exception_class": "hard"}),
            rule_digest=canonical_sha256(soft),
        )


def test_permission_intersection_is_exact_and_fail_closed() -> None:
    responsibility = permission_policy("responsibility", allow_write())
    project = permission_policy("project", allow_write())
    agent_policy = permission_policy("agent", allow_write())
    assert intersect_permission_policies(
        [responsibility, project, agent_policy], "write", "project_path", "src/app.py"
    )
    assert not intersect_permission_policies(
        [responsibility, project, permission_policy("missing")],
        "write",
        "project_path",
        "src/app.py",
    )
    assert not intersect_permission_policies(
        [responsibility, project, permission_policy("deny", allow_write(effect="deny"))],
        "write",
        "project_path",
        "src/app.py",
    )
    assert not intersect_permission_policies(
        [responsibility, project, agent_policy], "write", "project_path", "src/other.py"
    )


def test_effective_permissions_support_safe_globs_scope_and_backend_intersection() -> None:
    request = EffectivePermissionRequest(
        operation=PermissionOperation.WRITE,
        resource=PermissionResource.PROJECT_PATH,
        project_path="src/pkg/app.py",
    )
    policies = [permission_policy(name, allow_write("src/**/*.py")) for name in ("responsibility", "project", "agent")]
    assert evaluate_effective_permission(policies, request, ("src/**",), (PermissionOperation.WRITE,), (PermissionResource.PROJECT_PATH,))
    assert not evaluate_effective_permission(policies, request, ("tests/**",), (PermissionOperation.WRITE,), (PermissionResource.PROJECT_PATH,))
    assert not evaluate_effective_permission(policies, request, ("src/**",), (PermissionOperation.READ,), (PermissionResource.PROJECT_PATH,))
    assert not evaluate_effective_permission(policies[:-1], request, ("src/**",), (), (PermissionResource.PROJECT_PATH,))
    denied = permission_policy("deny", allow_write("src/**", effect="deny"), allow_write("src/**/*.py"))
    assert not evaluate_effective_permission([*policies[:-1], denied], request, ("src/**",), (PermissionOperation.WRITE,), (PermissionResource.PROJECT_PATH,))


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    (
        ("src", "src", True),
        ("src", "src/app.py", False),
        ("src/**", "src", True),
        ("src/**", "src/app.py", True),
        ("src/**", "src/pkg/app.py", True),
        ("src/*", "src/app.py", True),
        ("src/*", "src/pkg/app.py", False),
        ("src/*.py", "src/app.py", True),
        ("src/*.py", "src/pkg/app.py", False),
    ),
)
def test_project_path_pattern_semantics(pattern: str, path: str, matches: bool) -> None:
    assert project_path_pattern_matches(pattern, path) is matches


def test_non_path_effective_permissions_ignore_assignment_scope() -> None:
    rule = PermissionRule(
        rule_id="send-mailbox",
        exception_class="hard",
        effect="allow",
        operation=PermissionOperation.SEND,
        resource=PermissionResource.MAILBOX,
        resource_pattern="mailbox",
    )
    policies = [permission_policy(name, rule) for name in ("responsibility", "project", "agent")]
    request = EffectivePermissionRequest(
        operation=PermissionOperation.SEND,
        resource=PermissionResource.MAILBOX,
        resource_name="mailbox",
    )
    assert evaluate_effective_permission(
        policies,
        request,
        (),
        (PermissionOperation.SEND,),
        (PermissionResource.MAILBOX,),
    )
    assert not evaluate_effective_permission(policies[:-1], request, (), (), (PermissionResource.MAILBOX,))


@pytest.mark.parametrize("pattern", ("../src/**", "/src/**", "src/[ab].py", "src/?.py", "src/***.py", "src/**.py"))
def test_permission_patterns_reject_unsafe_globs(pattern: str) -> None:
    with pytest.raises(ValidationError):
        allow_write(pattern)


def test_concrete_permission_request_rejects_globs() -> None:
    with pytest.raises(ValidationError):
        EffectivePermissionRequest(operation="write", resource="project_path", project_path="src/**")


def test_permission_typos_and_non_deny_defaults_are_rejected() -> None:
    with pytest.raises(ValidationError):
        PermissionRule(
            rule_id="typo",
            exception_class="hard",
            effect="allow",
            operation="wirte",
            resource="project_path",
            resource_pattern="src/app.py",
        )
    with pytest.raises(ValueError):
        intersect_permission_policies([permission_policy("one")], "wirte", "project_path", "src/app.py")
    with pytest.raises(ValidationError):
        PermissionPolicy(
            schema_version=SCHEMA_VERSION,
            kind="permission_policy",
            definition_version="1",
            policy_id="unsafe",
            default_effect="allow",
            rules=(),
        )


def test_candidate_success_requires_exact_criterion_map_and_stage_appropriate_dispositions() -> None:
    CandidateReport(**candidate_data())
    data = candidate_data()
    data["criterion_ids"] = ("criterion-1", "criterion-2")
    with pytest.raises(ValidationError, match="exactly match"):
        CandidateReport(**data)
    data = candidate_data()
    data["criterion_dispositions"] = (
        CriterionDisposition(criterion_id="criterion-1", disposition="unsatisfied"),
    )
    with pytest.raises(ValidationError, match="unsatisfied"):
        CandidateReport(**data)
    data = candidate_data()
    data["criterion_dispositions"] = (
        CriterionDisposition(criterion_id="criterion-1", disposition="not_evaluated"),
    )
    data["evidence"] = ()
    assert CandidateReport(**data).criterion_dispositions[0].disposition == "not_evaluated"
    with pytest.raises(ValidationError, match="requires evidence"):
        CriterionDisposition(criterion_id="criterion-1", disposition="claimed_satisfied")


def test_candidate_pins_session_context_and_role_appropriate_change_set() -> None:
    data = candidate_data()
    data.pop("attempt_id")
    with pytest.raises(ValidationError, match="attempt_id"):
        CandidateReport(**data)
    data = candidate_data()
    data["change_set"] = None
    with pytest.raises(ValidationError, match="implementation.*require"):
        CandidateReport(**data)
    data = candidate_data()
    data.update(stage="review", stage_id="review-stage")
    with pytest.raises(ValidationError, match="forbid a change_set"):
        CandidateReport(**data)


def test_verification_plan_criteria_have_unique_stable_ids() -> None:
    item = VerificationCriterion(
        criterion_id="criterion-1",
        statement="The canary passes",
        required_evidence_types=(EvidenceType.TEST_OUTPUT,),
    )
    with pytest.raises(ValidationError, match="criterion IDs must be unique"):
        VerificationPlan(
            schema_version=SCHEMA_VERSION,
            kind="verification_plan",
            verification_plan_id="plan-1",
            work_item=record("work_item"),
            criteria=(item, item),
            commands=(("pytest",),),
            created_at=NOW,
        )


def test_verification_receipt_is_bound_complete_and_evidenced() -> None:
    VerificationReceipt(**receipt_data())
    data = receipt_data()
    data["run_bindings"] = ()
    with pytest.raises(ValidationError, match="at least one run"):
        VerificationReceipt(**data)
    data = receipt_data()
    data["criterion_ids"] = ("criterion-1", "criterion-2")
    with pytest.raises(ValidationError, match="exactly match"):
        VerificationReceipt(**data)
    with pytest.raises(ValidationError, match="requires evidence"):
        CriterionResult(criterion_id="criterion-1", command_indexes=(0,), disposition="pass")
    data = receipt_data()
    data["criterion_results"] = (
        CriterionResult(criterion_id="criterion-1", command_indexes=(0,), disposition="fail"),
    )
    with pytest.raises(ValidationError, match="every criterion"):
        VerificationReceipt(**data)


def test_independent_receipts_reports_and_reviews_reject_producer_identity() -> None:
    data = receipt_data()
    data["producer_role_instance_id"] = data["issued_by"].role_instance_id
    with pytest.raises(ValidationError, match="independent"):
        VerificationReceipt(**data)
    disposition = AssuranceDisposition(domain=AssuranceDomain.SECURITY_PRIVACY, disposition="pass")
    with pytest.raises(ValidationError, match="requires dispositions"):
        AssuranceReport(
            schema_version=SCHEMA_VERSION,
            kind="assurance_report",
            assurance_report_id="assurance-1",
            candidate=record("candidate_report"),
            producer_role_instance_id="role-producer",
            dispositions=(),
            auditor=agent("auditor"),
            produced_at=NOW,
        )
    with pytest.raises(ValidationError, match="domains must be unique"):
        AssuranceReport(
            schema_version=SCHEMA_VERSION,
            kind="assurance_report",
            assurance_report_id="assurance-1",
            candidate=record("candidate_report"),
            producer_role_instance_id="role-producer",
            dispositions=(disposition, disposition),
            auditor=agent("auditor"),
            produced_at=NOW,
        )
    with pytest.raises(ValidationError, match="independent"):
        ReviewDecision(
            schema_version=SCHEMA_VERSION,
            kind="review_decision",
            review_decision_id="review-1",
            candidate=record("candidate_report"),
            producer_role_instance_id="role-reviewer",
            decision="RETURN",
            rationale="Return",
            reviewer=agent("reviewer"),
            decided_at=NOW,
        )


def test_verification_receipt_run_bindings_must_match_receipt_pins() -> None:
    data = receipt_data()
    binding = data["run_bindings"][0]
    data["run_bindings"] = (binding.model_copy(update={"workspace_digest": DIGEST_B}),)
    with pytest.raises(ValidationError, match="run binding must match"):
        VerificationReceipt(**data)


def test_verification_run_requires_candidate_change_set_and_workspace_bindings() -> None:
    data = {
        "schema_version": SCHEMA_VERSION,
        "kind": "verification_run",
        "verification_run_id": "run-1",
        "plan": record("verification_plan"),
        "candidate": record("candidate_report"),
        "change_set": record("change_set"),
        "workspace_digest": DIGEST_A,
        "command": ("pytest",),
        "exit_code": 0,
        "duration_seconds": 1.0,
        "evidence": (record("evidence_artifact"),),
        "started_at": NOW,
        "finished_at": NOW,
    }
    VerificationRun(**data)
    for field in ("candidate", "change_set", "workspace_digest"):
        incomplete = dict(data)
        incomplete.pop(field)
        with pytest.raises(ValidationError, match=field):
            VerificationRun(**incomplete)


def test_accept_review_decision_requires_evidence_and_receipts() -> None:
    with pytest.raises(ValidationError, match="requires evidence"):
        ReviewDecision(
            schema_version=SCHEMA_VERSION,
            kind="review_decision",
            review_decision_id="review-1",
            candidate=record("candidate_report"),
            producer_role_instance_id="role-producer",
            decision="ACCEPT",
            rationale="Criteria are met",
            reviewer=agent("reviewer"),
            decided_at=NOW,
        )


def test_structured_blocking_findings_contradict_pass_and_accept() -> None:
    finding = SemanticFinding(summary="Unresolved risk", severity="high", blocking=False)
    with pytest.raises(ValidationError, match="passing assurance"):
        AssuranceDisposition(
            domain=AssuranceDomain.SECURITY_PRIVACY,
            disposition="pass",
            findings=(finding,),
        )
    with pytest.raises(ValidationError, match="ACCEPT cannot"):
        ReviewDecision(
            schema_version=SCHEMA_VERSION,
            kind="review_decision",
            review_decision_id="review-blocking",
            candidate=record("candidate_report"),
            producer_role_instance_id="role-producer",
            decision="ACCEPT",
            rationale="Accept",
            findings=(finding,),
            evidence=(record("assurance_report"),),
            verification_receipts=(record("verification_receipt"),),
            reviewer=agent("reviewer"),
            decided_at=NOW,
        )


@pytest.mark.parametrize(
    ("action", "before", "after"),
    (("create", None, DIGEST_A), ("modify", DIGEST_A, DIGEST_B), ("delete", DIGEST_A, None)),
)
def test_change_entry_accepts_action_appropriate_digests(action: str, before: str | None, after: str | None) -> None:
    ChangeEntry(path="src/app.py", action=action, before_digest=before, after_digest=after)


@pytest.mark.parametrize(
    ("action", "before", "after"),
    (("create", DIGEST_A, DIGEST_B), ("modify", None, DIGEST_B), ("modify", DIGEST_A, DIGEST_A), ("delete", DIGEST_A, DIGEST_B)),
)
def test_change_entry_rejects_action_inappropriate_digests(action: str, before: str | None, after: str | None) -> None:
    with pytest.raises(ValidationError):
        ChangeEntry(path="src/app.py", action=action, before_digest=before, after_digest=after)


def test_change_set_paths_are_unique_and_sorted() -> None:
    one = ChangeEntry(path="src/a.py", action="create", after_digest=DIGEST_A)
    two = ChangeEntry(path="src/b.py", action="create", after_digest=DIGEST_B)
    common = {
        "schema_version": SCHEMA_VERSION,
        "kind": "change_set",
        "change_set_id": "change-1",
        "base_manifest_digest": DIGEST_A,
        "final_manifest_digest": DIGEST_B,
        "created_at": NOW,
    }
    ChangeSet(**common, entries=(one, two))
    with pytest.raises(ValidationError, match="sorted"):
        ChangeSet(**common, entries=(two, one))
    with pytest.raises(ValidationError, match="unique"):
        ChangeSet(**common, entries=(one, one))


def test_manifest_root_is_computed_from_validated_sorted_entries() -> None:
    entries = (
        ManifestEntry(path="src/a.py", digest=DIGEST_A, size_bytes=1),
        ManifestEntry(path="src/b.py", digest=DIGEST_B, size_bytes=2),
    )
    root = build_manifest_root_digest(entries)
    ProjectManifest(
        schema_version=SCHEMA_VERSION,
        kind="project_manifest",
        manifest_id="manifest-1",
        entries=entries,
        root_digest=root,
        created_at=NOW,
    )
    with pytest.raises(ValidationError, match="root_digest"):
        ProjectManifest(
            schema_version=SCHEMA_VERSION,
            kind="project_manifest",
            manifest_id="manifest-1",
            entries=entries,
            root_digest=DIGEST_A,
            created_at=NOW,
        )
    with pytest.raises(ValidationError, match="unique"):
        build_manifest_root_digest((entries[0], entries[0]))


def test_project_state_seal_and_assignment_invariants() -> None:
    common = {
        "schema_version": SCHEMA_VERSION,
        "kind": "project_state",
        "project_id": "project-1",
        "updated_at": NOW,
    }
    with pytest.raises(ValidationError, match="require a candidate_seal"):
        ProjectState(**common, status="sealed")
    with pytest.raises(ValidationError, match="require a candidate_seal"):
        ProjectState(**common, status="closed")
    assignment = record("assignment")
    with pytest.raises(ValidationError, match="active assignment IDs must be unique"):
        ProjectState(**common, status="active", active_assignments=(assignment, assignment))
    with pytest.raises(ValidationError, match="forbid active assignments"):
        ProjectState(
            **common,
            status="sealed",
            candidate_seal=record("candidate_seal"),
            active_assignments=(assignment,),
        )


def test_lifecycle_events_are_typed_status_transitions_in_a_digest_chain() -> None:
    common = {
        "schema_version": SCHEMA_VERSION,
        "kind": "lifecycle_event",
        "event_id": "event-2",
        "aggregate_version": 2,
        "previous_event_digest": DIGEST_A,
        "event_type": LifecycleEventType.STATUS_CHANGED,
        "from_status": "planned",
        "to_status": "active",
        "actor": lead(),
        "subject": record("project_state"),
        "summary": "Begin work",
        "occurred_at": NOW,
    }
    LifecycleEvent(**common)
    with pytest.raises(ValidationError):
        LifecycleEvent(**{**common, "event_type": "typo"})
    with pytest.raises(ValidationError, match="previous event digest"):
        LifecycleEvent(**{**common, "previous_event_digest": None})
    with pytest.raises(ValidationError, match="not allowed"):
        LifecycleEvent(**{**common, "to_status": "planned"})
    with pytest.raises(ValidationError, match="project_state"):
        LifecycleEvent(**{**common, "subject": record("work_item")})
    with pytest.raises(ValidationError, match="PROJECT_CLOSED"):
        LifecycleEvent(**{**common, "event_type": LifecycleEventType.PROJECT_CLOSED})


def test_candidate_seal_digest_covers_every_material_payload_input() -> None:
    values = seal_payload_data()
    payload = build_candidate_seal_payload(**values)
    digest = canonical_sha256(payload)
    seal = CandidateSeal(
        kind="candidate_seal",
        seal_id=f"seal-{digest}",
        candidate_digest=digest,
        **values,
        sealed_by=launcher(),
        sealed_at=NOW,
    )
    assert seal.candidate_digest == digest

    for field in (
        "project_id",
        "work_item",
        "pipeline_revision",
        "role_instances",
        "context_packs",
        "stage_candidates",
        "base_manifest",
        "final_manifest",
        "cumulative_change_set",
        "verification_receipts",
        "assurance_report",
        "acceptance_review",
        "lead_decision",
    ):
        changed = dict(values)
        current = changed[field]
        if field == "project_id":
            changed[field] = "project-2"
        elif isinstance(current, tuple):
            item = current[0]
            if isinstance(item, RequiredStageCandidate):
                changed[field] = (item.model_copy(update={"candidate": item.candidate.model_copy(update={"digest": DIGEST_C})}),)
            else:
                changed[field] = (item.model_copy(update={"digest": DIGEST_C}),)
        else:
            changed[field] = current.model_copy(update={"digest": DIGEST_C})
        assert canonical_sha256(build_candidate_seal_payload(**changed)) != digest
    changed = {**values, "compiler_version": "codexteam-v2-compiler/2"}
    assert canonical_sha256(build_candidate_seal_payload(**changed)) != digest


def test_candidate_seal_rejects_tampering_empty_inputs_and_arbitrary_refs() -> None:
    values = seal_payload_data()
    digest = canonical_sha256(build_candidate_seal_payload(**values))
    common = {
        "schema_version": SCHEMA_VERSION,
        "kind": "candidate_seal",
        "seal_id": f"seal-{digest}",
        "candidate_digest": digest,
        **values,
        "sealed_by": lead(),
        "sealed_at": NOW,
    }
    with pytest.raises(ValidationError, match="candidate_digest"):
        CandidateSeal(**{**common, "compiler_version": "tampered"})
    with pytest.raises(ValidationError, match="role_instances must be nonempty"):
        CandidateSeal(**{**common, "role_instances": ()})
    with pytest.raises(ValidationError, match="review_decision"):
        CandidateSeal(**{**common, "acceptance_review": record("arbitrary")})
    with pytest.raises(ValidationError):
        CandidateSeal(**{**common, "verification_fresh": False})
    with pytest.raises(ValidationError, match="project_lead or authorized launcher"):
        CandidateSeal(**{**common, "sealed_by": agent()})


def test_candidate_seal_factory_enforces_coverage_identity_and_input_immutability() -> None:
    values = seal_payload_data()
    original = dict(values)
    seal = create_candidate_seal(**values, sealed_by=lead(), sealed_at=NOW)
    assert seal.seal_id == f"seal-{seal.candidate_digest}"
    assert values == original
    with pytest.raises(ValidationError, match="seal_id"):
        CandidateSeal(**{**seal.model_dump(mode="python"), "seal_id": "seal-alternate"})
    with pytest.raises(ValidationError, match="exactly cover"):
        build_candidate_seal_payload(**{**values, "required_stage_ids": ("implementation-stage", "review-stage")})
    duplicate = values["stage_candidates"][0]
    with pytest.raises(ValidationError, match="stage candidate"):
        build_candidate_seal_payload(**{**values, "stage_candidates": (duplicate, duplicate)})
    with pytest.raises(ValidationError):
        create_candidate_seal(**{**values, "verification_accepted": False}, sealed_by=lead(), sealed_at=NOW)


def test_timestamps_must_be_utc_aware() -> None:
    data = receipt_data()
    data["issued_at"] = datetime(2026, 8, 7)
    with pytest.raises(ValidationError, match="UTC-aware"):
        VerificationReceipt(**data)


def test_generated_schemas_require_discriminators_and_mark_semantic_validation() -> None:
    for model in TOP_LEVEL_MODELS:
        schema = json.loads((SCHEMA_DIRECTORY / schema_filename(model)).read_text(encoding="utf-8"))
        assert {"schema_version", "kind"} <= set(schema["required"])
        assert schema["$comment"] == SEMANTIC_COMMENT
        assert schema["x-codexteam-semantic-model"] == model.__name__
        assert schema["x-codexteam-semantic-module"] == "codexteam_tools.v2.models"
        assert schema["x-codexteam-contract-version"] == SCHEMA_VERSION
    change_schema = json.loads((SCHEMA_DIRECTORY / "change-set.json").read_text(encoding="utf-8"))
    assert "allOf" in change_schema["$defs"]["ChangeEntry"]
    assert "pattern" in change_schema["$defs"]["ChangeEntry"]["properties"]["path"]


def test_generated_schemas_are_fresh() -> None:
    assert check_schemas() == []
