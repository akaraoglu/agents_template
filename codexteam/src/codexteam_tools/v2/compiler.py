from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime

from .canonical import canonical_sha256
from .catalog import Catalog, ResolvedAgentSpec
from .models import (
    ActorRef,
    Assignment,
    DefinitionRef,
    PermissionOperation,
    PermissionPolicy,
    PermissionResource,
    PermissionRule,
    PipelineDefinition,
    PipelinePlan,
    PipelineRevision,
    PipelineStageSpec,
    ProjectPolicy,
    RecordRef,
    RoleInstance,
    WorkItem,
    build_role_instance_payload,
    pipeline_stage_digest,
    project_path_pattern_matches,
)


@dataclass(frozen=True)
class CompileReferences:
    pipeline: DefinitionRef
    work_item: RecordRef
    plan: RecordRef


@dataclass(frozen=True)
class CompiledPipeline:
    plan: PipelinePlan
    refs: CompileReferences
    selection_trace: tuple[str, ...]

    def __iter__(self) -> Iterator[object]:
        """Allow callers to unpack the requested PipelinePlan and references."""
        yield self.plan
        yield self.refs


def _record_ref(record_id: str, kind: str, value: object) -> RecordRef:
    return RecordRef(record_id=record_id, kind=kind, digest=canonical_sha256(value))


def compile_pipeline(
    catalog: Catalog,
    work_item: WorkItem,
    selected_optional_stages: Sequence[str],
    approved_by: ActorRef,
    approved_at: datetime,
    *,
    pipeline_id: str = "adaptive-verified-delivery",
) -> CompiledPipeline:
    selected = tuple(selected_optional_stages)
    if len(selected) != len(set(selected)) or not set(selected) <= {"architecture", "ux"}:
        raise ValueError("selected optional stages must contain each of 'architecture' and 'ux' at most once")
    pipeline = catalog.get("pipeline_definition", pipeline_id)
    if not isinstance(pipeline, PipelineDefinition):
        raise ValueError(f"definition {pipeline_id!r} is not a PipelineDefinition")
    selected_set = set(selected)
    stages: list[PipelineStageSpec] = []
    for source in pipeline.stages:
        if source.optional and source.stage not in selected_set:
            continue
        dependencies = () if not stages else (stages[-1].stage_id,)
        stages.append(source.model_copy(update={"dependencies": dependencies}))
    pipeline_ref = catalog.ref("pipeline_definition", pipeline_id)
    work_item_ref = _record_ref(work_item.work_item_id, work_item.kind, work_item)
    identity = {
        "pipeline": pipeline_ref,
        "work_item": work_item_ref,
        "stages": tuple(stages),
        "approved_by": approved_by,
    }
    plan_id = f"plan-{canonical_sha256(identity)}"
    plan = PipelinePlan.model_validate(
        {
            "schema_version": "2.0",
            "kind": "pipeline_plan",
            "plan_id": plan_id,
            "pipeline": pipeline_ref,
            "work_item": work_item_ref,
            "stages": tuple(stages),
            "approved_by": approved_by,
            "approved_at": approved_at,
        }
    )
    plan_ref = _record_ref(plan.plan_id, plan.kind, plan)
    trace = tuple(
        f"{stage}:{'selected' if stage in selected_set else 'omitted'}"
        for stage in ("architecture", "ux")
    )
    return CompiledPipeline(plan, CompileReferences(pipeline_ref, work_item_ref, plan_ref), trace)


def _scope_contains(approved: str, requested: str) -> bool:
    return project_path_pattern_matches(approved, requested, candidate_is_pattern=True)


def _rule_contains(rule_pattern: str, scope_pattern: str) -> bool:
    return project_path_pattern_matches(rule_pattern, scope_pattern, candidate_is_pattern=True)


def _policy_allows_scope(policy: PermissionPolicy | ProjectPolicy, operation: PermissionOperation, scope: str) -> bool:
    matching = tuple(
        rule
        for rule in policy.rules
        if rule.operation == operation
        and rule.resource == PermissionResource.PROJECT_PATH
        and _rule_contains(rule.resource_pattern, scope)
    )
    return any(rule.effect == "allow" for rule in matching) and not any(rule.effect == "deny" for rule in matching)


def _policy_allows_rule(policy: PermissionPolicy | ProjectPolicy, source_rule: PermissionRule) -> bool:
    operation = source_rule.operation
    resource = source_rule.resource
    pattern = source_rule.resource_pattern
    matching = tuple(
        rule
        for rule in policy.rules
        if rule.operation == operation
        and rule.resource == resource
        and (
            _rule_contains(rule.resource_pattern, pattern)
            if resource == PermissionResource.PROJECT_PATH
            else rule.resource_pattern == pattern
        )
    )
    return any(rule.effect == "allow" for rule in matching) and not any(rule.effect == "deny" for rule in matching)


def _backend_limits(resolved: ResolvedAgentSpec) -> tuple[tuple[PermissionOperation, ...], tuple[PermissionResource, ...]]:
    return resolved.backend.supported_operations, resolved.backend.supported_resources


def _policy_supports_requirements(
    policy: PermissionPolicy | ProjectPolicy,
    operations: set[PermissionOperation],
    resources: set[PermissionResource],
) -> bool:
    allows = tuple(rule for rule in policy.rules if rule.effect == "allow")
    return all(any(rule.operation == operation for rule in allows) for operation in operations) and all(
        any(rule.resource == resource for rule in allows) for resource in resources
    )


def build_role_instance(
    catalog: Catalog,
    *,
    assignment: Assignment,
    work_item: WorkItem,
    pipeline_revision: PipelineRevision,
    stage_spec: PipelineStageSpec,
    attempt_id: str,
    project_policy_id: str = "canary-project",
    operator_grant_ids: Sequence[str] = (),
    operator_grants_authorization: RecordRef | None = None,
    host_isolation_authorization: RecordRef | None = None,
    role_instance_id: str | None = None,
) -> RoleInstance:
    if not isinstance(pipeline_revision, PipelineRevision):
        raise ValueError("pipeline_revision must be a resolved PipelineRevision")
    work_item_ref = _record_ref(work_item.work_item_id, work_item.kind, work_item)
    if assignment.work_item != work_item_ref:
        raise ValueError("assignment work_item does not match the supplied work item")
    revision_stage = next((item for item in pipeline_revision.stages if item.stage_id == stage_spec.stage_id), None)
    if revision_stage is None or revision_stage != stage_spec or pipeline_stage_digest(revision_stage) != pipeline_stage_digest(stage_spec):
        raise ValueError("supplied pipeline stage is not byte-identical to a stage in the pipeline revision")
    if assignment.stage != stage_spec.stage or assignment.agent_spec != stage_spec.agent_spec:
        raise ValueError("assignment does not match the supplied pipeline stage")
    if assignment.assurance_domain != stage_spec.assurance_domain:
        raise ValueError("assignment assurance_domain does not match the supplied pipeline stage")
    if any(not any(_scope_contains(approved, scope) for approved in work_item.approved_scope) for scope in assignment.scope):
        raise ValueError("assignment scope broadens the work item approved scope")
    resolved = catalog.resolve_agent_spec(
        assignment.agent_spec.definition_id, assignment.agent_spec.definition_version
    )
    if assignment.agent_spec != catalog.ref(
        "agent_spec", resolved.agent_spec.agent_spec_id, resolved.agent_spec.definition_version
    ):
        raise ValueError("assignment agent_spec digest/reference mismatch")
    project_policy = catalog.get("project_policy", project_policy_id)
    if not isinstance(project_policy, ProjectPolicy):
        raise ValueError(f"definition {project_policy_id!r} is not a ProjectPolicy")
    grant_ids = tuple(sorted(set(operator_grant_ids)))
    if bool(grant_ids) != (operator_grants_authorization is not None):
        raise ValueError("operator grants require exactly one authorization reference")
    if operator_grants_authorization is not None and operator_grants_authorization.kind not in {
        "lead_decision",
        "policy_exception",
    }:
        raise ValueError("operator grants authorization must reference a lead_decision or policy_exception")
    grants: list[PermissionPolicy] = []
    for grant_id in grant_ids:
        grant = catalog.get("permission_policy", grant_id)
        if not isinstance(grant, PermissionPolicy):
            raise ValueError(f"operator grant {grant_id!r} is not a PermissionPolicy")
        grants.append(grant)
    backend_operations, backend_resources = _backend_limits(resolved)
    required_operations = {
        operation for capability in resolved.capabilities for operation in capability.required_operations
    }
    required_resources = {
        resource for capability in resolved.capabilities for resource in capability.required_resources
    }
    if not required_operations <= set(backend_operations) or not required_resources <= set(backend_resources):
        raise ValueError("backend support cannot satisfy the resolved capability requirements")
    for policy in (resolved.responsibility_permission_ceiling, project_policy, resolved.permission_policy, *grants):
        if not _policy_supports_requirements(policy, required_operations, required_resources):
            raise ValueError("effective policy layers cannot satisfy the resolved capability requirements")
    required_agent_rules = tuple(
        rule
        for rule in resolved.permission_policy.rules
        if rule.effect == "allow"
        and rule.operation in required_operations
        and rule.resource in required_resources
    )
    for rule in required_agent_rules:
        for policy in (resolved.responsibility_permission_ceiling, project_policy, *grants):
            if not _policy_allows_rule(policy, rule):
                raise ValueError("effective policy layers cannot satisfy an AgentSpec permission requirement")
    agent_path_operations = {
        rule.operation
        for rule in resolved.permission_policy.rules
        if rule.effect == "allow"
        and rule.resource == PermissionResource.PROJECT_PATH
        and rule.operation in required_operations
    }
    if PermissionOperation.READ in agent_path_operations:
        for scope in assignment.scope:
            for policy in (resolved.responsibility_permission_ceiling, project_policy, resolved.permission_policy, *grants):
                if not _policy_allows_scope(policy, PermissionOperation.READ, scope):
                    raise ValueError("assignment read scope broadens effective permissions")
    writable = PermissionOperation.WRITE in agent_path_operations
    if resolved.backend.provider == "opencode" and writable and host_isolation_authorization is None:
        raise ValueError("writable OpenCode role instances require explicit host isolation authorization")
    stage_digest = pipeline_stage_digest(stage_spec)
    pipeline_revision_ref = _record_ref(
        pipeline_revision.revision_id, pipeline_revision.kind, pipeline_revision
    )
    identity = {
        "assignment": assignment,
        "pipeline_revision": pipeline_revision_ref,
        "stage_id": stage_spec.stage_id,
        "stage_spec_digest": stage_digest,
        "attempt_id": attempt_id,
        "project_policy": catalog.ref("project_policy", project_policy_id),
        "operator_grants": tuple(
            catalog.ref("permission_policy", item.policy_id, item.definition_version) for item in grants
        ),
        "operator_grants_authorization": operator_grants_authorization,
        "assignment_scope": tuple(sorted(assignment.scope)),
        "backend": catalog.ref(
            "backend_definition", resolved.backend.backend_id, resolved.backend.definition_version
        ),
        "backend_supported_operations": resolved.backend.supported_operations,
        "backend_supported_resources": resolved.backend.supported_resources,
        "backend_limitations": resolved.backend.limitations,
        "host_isolation_authorization": host_isolation_authorization,
    }
    resolved_role_id = role_instance_id or f"role-{canonical_sha256(identity)}"
    return build_role_instance_payload(
        role_instance_id=resolved_role_id,
        assignment=_record_ref(assignment.assignment_id, assignment.kind, assignment),
        pipeline_revision=pipeline_revision_ref,
        stage_id=stage_spec.stage_id,
        stage_spec_digest=stage_digest,
        attempt_id=attempt_id,
        agent_spec=resolved.agent_spec,
        responsibility=resolved.responsibility,
        responsibility_permission_ceiling=resolved.responsibility_permission_ceiling,
        capabilities=resolved.capabilities,
        permission_policy=resolved.permission_policy,
        project_policy=project_policy,
        operator_grants=tuple(grants),
        operator_grants_authorization=operator_grants_authorization,
        assignment_scope=assignment.scope,
        guidance_bundle=resolved.guidance_bundle,
        model_profile=resolved.model_profile,
        backend=resolved.backend,
        host_isolation_authorization=host_isolation_authorization,
    )


__all__ = [
    "CompileReferences",
    "CompiledPipeline",
    "build_role_instance",
    "compile_pipeline",
]
