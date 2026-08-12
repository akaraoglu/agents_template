from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import re
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    WithJsonSchema,
    model_validator,
)

from .canonical import (
    canonical_json,
    canonical_sha256,
    validate_project_path,
    validate_project_path_pattern as _validate_project_path_pattern,
    validate_utc_datetime,
)

SCHEMA_VERSION = "2.0"

Identifier = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$", min_length=1, max_length=200),
]
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ProjectPath = Annotated[
    str,
    AfterValidator(validate_project_path),
    WithJsonSchema(
        {
            "type": "string",
            "minLength": 1,
            "pattern": r"^(?!/)(?!.*(?:^|/)\.{1,2}(?:/|$))(?!.*//)(?!.*\\).+$",
        }
    ),
]


def validate_project_path_pattern(value: str) -> str:
    """Validate the v2 path-pattern language: safe POSIX segments with * or **."""
    _validate_project_path_pattern(value)
    if any("**" in segment and segment != "**" for segment in value.split("/")):
        raise ValueError("'**' must occupy an entire path segment")
    return value


ProjectPathPattern = Annotated[
    str,
    AfterValidator(validate_project_path_pattern),
    WithJsonSchema({"type": "string", "minLength": 1}),
]
UtcDateTime = Annotated[datetime, AfterValidator(validate_utc_datetime)]
Stage = Literal["discovery", "architecture", "ux", "implementation", "verification", "assurance", "review"]
ProjectStatus = Literal["planned", "active", "blocked", "review", "sealed", "closed", "cancelled"]
ALLOWED_PROJECT_STATUS_TRANSITIONS = frozenset(
    {
        ("planned", "active"),
        ("planned", "cancelled"),
        ("active", "blocked"),
        ("active", "review"),
        ("active", "cancelled"),
        ("blocked", "active"),
        ("blocked", "cancelled"),
        ("review", "active"),
        ("review", "sealed"),
        ("review", "cancelled"),
        ("sealed", "closed"),
    }
)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class VersionedRecord(ContractModel):
    schema_version: Literal["2.0"]


class ReusableDefinition(VersionedRecord):
    definition_version: NonEmptyStr


class AssuranceDomain(StrEnum):
    SECURITY_PRIVACY = "security_privacy"
    DATA_DATABASE = "data_database"
    ACCESSIBILITY = "accessibility"
    PERFORMANCE_RELIABILITY = "performance_reliability"


class EvidenceType(StrEnum):
    TEST_OUTPUT = "test_output"
    MANIFEST = "manifest"
    REVIEW = "review"
    ANALYSIS = "analysis"
    ARTIFACT = "artifact"


class PermissionOperation(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    DELETE = "delete"
    SPAWN = "spawn"
    SEND = "send"
    APPROVE = "approve"
    SEAL = "seal"


class PermissionResource(StrEnum):
    PROJECT_PATH = "project_path"
    PROJECT_STATE = "project_state"
    MAILBOX = "mailbox"
    EVIDENCE = "evidence"
    PROCESS = "process"
    NETWORK = "network"
    GIT_REPOSITORY = "git_repository"


class LifecycleEventType(StrEnum):
    STATUS_CHANGED = "status_changed"
    ASSIGNMENT_STARTED = "assignment_started"
    ASSIGNMENT_COMPLETED = "assignment_completed"
    CANDIDATE_REPORTED = "candidate_reported"
    VERIFICATION_COMPLETED = "verification_completed"
    DECISION_RECORDED = "decision_recorded"
    CANDIDATE_SEALED = "candidate_sealed"
    PROJECT_CLOSED = "project_closed"
    CANCELLED = "cancelled"


class DefinitionRef(ContractModel):
    definition_id: Identifier
    kind: Identifier
    definition_version: NonEmptyStr
    digest: Digest


class RecordRef(ContractModel):
    record_id: Identifier
    kind: Identifier
    digest: Digest


class ActorRef(ContractModel):
    actor_id: Identifier
    kind: Literal["operator", "project_lead", "agent", "orchestrator", "launcher"]
    role_instance_id: Identifier | None = None

    @model_validator(mode="after")
    def role_instance_matches_actor_kind(self) -> Self:
        if (self.kind == "agent") != (self.role_instance_id is not None):
            raise ValueError("role_instance_id is required for agents and forbidden for non-agents")
        return self


class PermissionRule(ContractModel):
    rule_id: Identifier
    exception_class: Literal["hard", "soft"]
    effect: Literal["allow", "deny"]
    operation: PermissionOperation
    resource: PermissionResource
    resource_pattern: NonEmptyStr

    @model_validator(mode="after")
    def project_path_patterns_are_safe(self) -> Self:
        if self.resource == PermissionResource.PROJECT_PATH:
            validate_project_path_pattern(self.resource_pattern)
        return self


class PermissionPolicy(ReusableDefinition):
    kind: Literal["permission_policy"]
    policy_id: Identifier
    default_effect: Literal["deny"]
    rules: tuple[PermissionRule, ...]

    @model_validator(mode="after")
    def rule_ids_are_unique(self) -> Self:
        _require_unique((rule.rule_id for rule in self.rules), "permission rule IDs")
        return self


class ProjectPolicy(ReusableDefinition):
    kind: Literal["project_policy"]
    project_policy_id: Identifier
    default_effect: Literal["deny"]
    rules: tuple[PermissionRule, ...]

    @model_validator(mode="after")
    def rule_ids_are_unique(self) -> Self:
        _require_unique((rule.rule_id for rule in self.rules), "permission rule IDs")
        return self


PermissionLayer = PermissionPolicy | ProjectPolicy


class EffectivePermissionRequest(ContractModel):
    operation: PermissionOperation
    resource: PermissionResource
    project_path: ProjectPath | None = None
    resource_name: NonEmptyStr | None = None

    @model_validator(mode="after")
    def concrete_resource_matches_type(self) -> Self:
        if self.resource == PermissionResource.PROJECT_PATH:
            if self.project_path is None or self.resource_name is not None:
                raise ValueError("project_path is required only for project_path resources")
        elif self.resource_name is None or self.project_path is not None:
            raise ValueError("resource_name is required for non-project-path resources")
        return self


def project_path_pattern_matches(pattern: str, candidate: str, *, candidate_is_pattern: bool = False) -> bool:
    """Match a concrete path, or conservatively prove that a pattern is contained."""
    validate_project_path_pattern(pattern)
    if candidate_is_pattern:
        validate_project_path_pattern(candidate)
        if pattern == candidate:
            return True
        if "*" not in candidate:
            return project_path_pattern_matches(pattern, candidate)
        container = pattern.split("/")
        requested = candidate.split("/")
        if container[-1:] == ["**"]:
            prefix = container[:-1]
            if len(requested) < len(prefix):
                return False
            return all(_segment_pattern_contains(upper, lower) for upper, lower in zip(prefix, requested))
        if "**" in container or "**" in requested or len(container) != len(requested):
            return False
        return all(_segment_pattern_contains(upper, lower) for upper, lower in zip(container, requested))
    validate_project_path(candidate)
    pattern_parts = pattern.split("/")
    candidate_parts = candidate.split("/")

    def matches(pattern_index: int, candidate_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return candidate_index == len(candidate_parts)
        part = pattern_parts[pattern_index]
        if part == "**":
            return matches(pattern_index + 1, candidate_index) or (
                candidate_index < len(candidate_parts) and matches(pattern_index, candidate_index + 1)
            )
        if candidate_index == len(candidate_parts):
            return False
        expression = "^" + re.escape(part).replace(r"\*", "[^/]*") + "$"
        return re.fullmatch(expression, candidate_parts[candidate_index]) is not None and matches(
            pattern_index + 1, candidate_index + 1
        )

    return matches(0, 0)


def _segment_pattern_contains(container: str, candidate: str) -> bool:
    if container == candidate or container == "*":
        return True
    if "*" not in candidate:
        expression = "^" + re.escape(container).replace(r"\*", "[^/]*") + "$"
        return re.fullmatch(expression, candidate) is not None
    return False


def evaluate_effective_permission(
    policies: tuple[PermissionLayer, ...] | list[PermissionLayer],
    request: EffectivePermissionRequest,
    assignment_scope: tuple[ProjectPathPattern, ...] | list[ProjectPathPattern],
    backend_allowed_operations: tuple[PermissionOperation, ...] | list[PermissionOperation],
    backend_allowed_resources: tuple[PermissionResource, ...] | list[PermissionResource],
) -> bool:
    """Fail closed unless scope, backend, and every policy layer allow the request."""
    checked_policies = TypeAdapter(tuple[PermissionLayer, ...]).validate_python(tuple(policies), strict=True)
    checked_operations = TypeAdapter(tuple[PermissionOperation, ...]).validate_python(
        tuple(backend_allowed_operations), strict=True
    )
    checked_resources = TypeAdapter(tuple[PermissionResource, ...]).validate_python(
        tuple(backend_allowed_resources), strict=True
    )
    if not checked_policies or request.operation not in checked_operations or request.resource not in checked_resources:
        return False
    if request.resource == PermissionResource.PROJECT_PATH:
        try:
            checked_scope = TypeAdapter(tuple[ProjectPathPattern, ...]).validate_python(
                tuple(assignment_scope), strict=True
            )
        except ValueError:
            return False
        if request.project_path is None or not any(
            project_path_pattern_matches(pattern, request.project_path) for pattern in checked_scope
        ):
            return False
    for policy in checked_policies:
        matching = [
            rule
            for rule in policy.rules
            if rule.operation == request.operation
            and rule.resource == request.resource
            and (
                request.project_path is not None
                and project_path_pattern_matches(rule.resource_pattern, request.project_path)
                if request.resource == PermissionResource.PROJECT_PATH
                else rule.resource_pattern == request.resource_name
            )
        ]
        if any(rule.effect == "deny" for rule in matching) or not any(rule.effect == "allow" for rule in matching):
            return False
    return True


def intersect_permission_policies(
    policies: tuple[PermissionLayer, ...] | list[PermissionLayer],
    operation: PermissionOperation | str,
    resource: PermissionResource | str,
    resource_pattern: str,
) -> bool:
    """Compatibility helper for an exact, project-path permission request."""
    checked_operation = PermissionOperation(operation)
    checked_resource = PermissionResource(resource)
    request = EffectivePermissionRequest(
        operation=checked_operation,
        resource=checked_resource,
        **(
            {"project_path": resource_pattern}
            if checked_resource == PermissionResource.PROJECT_PATH
            else {"resource_name": resource_pattern}
        ),
    )
    return evaluate_effective_permission(
        policies,
        request,
        (resource_pattern,),
        (checked_operation,),
        (checked_resource,),
    )


class Responsibility(ReusableDefinition):
    kind: Literal["responsibility"]
    responsibility_id: Identifier
    name: NonEmptyStr
    description: NonEmptyStr
    permission_ceiling: DefinitionRef

    @model_validator(mode="after")
    def permission_ceiling_kind_is_valid(self) -> Self:
        _require_definition_kind(self.permission_ceiling, "permission_policy", "permission_ceiling")
        return self


class Capability(ReusableDefinition):
    kind: Literal["capability"]
    capability_id: Identifier
    name: NonEmptyStr
    description: NonEmptyStr
    required_operations: tuple[PermissionOperation, ...] = ()
    required_resources: tuple[PermissionResource, ...] = ()


class GuidanceModule(ReusableDefinition):
    kind: Literal["guidance_module"]
    module_id: Identifier
    path: ProjectPath
    digest: Digest


class GuidanceBundle(ReusableDefinition):
    kind: Literal["guidance_bundle"]
    bundle_id: Identifier
    modules: tuple[DefinitionRef, ...]
    digest: Digest

    @model_validator(mode="after")
    def module_kinds_are_valid(self) -> Self:
        for module in self.modules:
            _require_definition_kind(module, "guidance_module", "modules")
        return self


class BackendDefinition(ReusableDefinition):
    kind: Literal["backend_definition"]
    backend_id: Identifier
    provider: NonEmptyStr
    command: tuple[NonEmptyStr, ...]
    supported_operations: tuple[PermissionOperation, ...]
    supported_resources: tuple[PermissionResource, ...]
    limitations: tuple[Literal["no_os_sandbox", "no_mcp"], ...] = ()

    @model_validator(mode="after")
    def support_is_unique(self) -> Self:
        _require_unique(self.supported_operations, "backend supported operations")
        _require_unique(self.supported_resources, "backend supported resources")
        _require_unique(self.limitations, "backend limitations")
        return self


class ModelProfile(ReusableDefinition):
    kind: Literal["model_profile"]
    profile_id: Identifier
    model: NonEmptyStr
    backend: DefinitionRef
    reasoning_effort: Literal["low", "medium", "high"] | None = None

    @model_validator(mode="after")
    def backend_kind_is_valid(self) -> Self:
        _require_definition_kind(self.backend, "backend_definition", "backend")
        return self


class AgentSpec(ReusableDefinition):
    kind: Literal["agent_spec"]
    agent_spec_id: Identifier
    responsibility: DefinitionRef
    capabilities: tuple[DefinitionRef, ...]
    permission_policy: DefinitionRef
    guidance_bundle: DefinitionRef
    model_profile: DefinitionRef

    @model_validator(mode="after")
    def component_kinds_are_valid(self) -> Self:
        _require_definition_kind(self.responsibility, "responsibility", "responsibility")
        for capability in self.capabilities:
            _require_definition_kind(capability, "capability", "capabilities")
        _require_definition_kind(self.permission_policy, "permission_policy", "permission_policy")
        _require_definition_kind(self.guidance_bundle, "guidance_bundle", "guidance_bundle")
        _require_definition_kind(self.model_profile, "model_profile", "model_profile")
        return self


class MachineVerificationSpec(ContractModel):
    verifier_argv: tuple[NonEmptyStr, ...]
    argv: tuple[NonEmptyStr, ...]
    expected_stdout: str

    @model_validator(mode="after")
    def argv_is_nonempty(self) -> Self:
        if not self.argv or not self.verifier_argv:
            raise ValueError("machine verification argv arrays must be nonempty")
        return self


class AcceptanceCriterion(ContractModel):
    id: Identifier
    statement: NonEmptyStr
    required_evidence_types: tuple[EvidenceType, ...]
    verification: MachineVerificationSpec | None = None

    @model_validator(mode="after")
    def evidence_types_are_unique_and_nonempty(self) -> Self:
        if not self.required_evidence_types:
            raise ValueError("an acceptance criterion requires at least one evidence type")
        _require_unique(self.required_evidence_types, "required evidence types")
        return self


class WorkItem(VersionedRecord):
    kind: Literal["work_item"]
    work_item_id: Identifier
    title: NonEmptyStr
    objective: NonEmptyStr
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    approved_scope: tuple[ProjectPathPattern, ...] = ()

    @model_validator(mode="after")
    def criteria_are_stable_and_scope_is_unique(self) -> Self:
        if not self.acceptance_criteria:
            raise ValueError("a work item requires at least one acceptance criterion")
        _require_unique((criterion.id for criterion in self.acceptance_criteria), "acceptance criterion IDs")
        _require_unique(self.approved_scope, "approved scope paths")
        return self


class Assignment(VersionedRecord):
    kind: Literal["assignment"]
    assignment_id: Identifier
    work_item: RecordRef
    stage: Stage
    agent_spec: DefinitionRef
    scope: tuple[ProjectPathPattern, ...]
    assurance_domain: AssuranceDomain | None = None

    @model_validator(mode="after")
    def assignment_is_consistent(self) -> Self:
        _require_ref_kind(self.work_item, "work_item", "work_item")
        _require_definition_kind(self.agent_spec, "agent_spec", "agent_spec")
        if (self.stage == "assurance") != (self.assurance_domain is not None):
            raise ValueError("assurance_domain must be set if and only if stage is 'assurance'")
        _require_unique(self.scope, "assignment scope paths")
        return self


class RoleInstance(VersionedRecord):
    kind: Literal["role_instance"]
    role_instance_id: Identifier
    assignment: RecordRef
    pipeline_revision: RecordRef
    stage_id: Identifier
    stage_spec_digest: Digest
    attempt_id: Identifier
    agent_spec: DefinitionRef
    responsibility: DefinitionRef
    responsibility_permission_ceiling: DefinitionRef
    capabilities: tuple[DefinitionRef, ...]
    permission_policy: DefinitionRef
    project_policy: DefinitionRef
    operator_grants: tuple[DefinitionRef, ...]
    operator_grants_authorization: RecordRef | None
    assignment_scope: tuple[ProjectPathPattern, ...]
    guidance_bundle: DefinitionRef
    model_profile: DefinitionRef
    backend: DefinitionRef
    backend_supported_operations: tuple[PermissionOperation, ...]
    backend_supported_resources: tuple[PermissionResource, ...]
    backend_limitations: tuple[Literal["no_os_sandbox", "no_mcp"], ...]
    host_isolation_authorization: RecordRef | None = None
    effective_policy_digest: Digest
    resolved_digest: Digest

    @model_validator(mode="after")
    def references_have_expected_kinds(self) -> Self:
        _require_ref_kind(self.assignment, "assignment", "assignment")
        _require_ref_kind(self.pipeline_revision, "pipeline_revision", "pipeline_revision")
        _require_definition_kind(self.agent_spec, "agent_spec", "agent_spec")
        _require_definition_kind(self.responsibility, "responsibility", "responsibility")
        _require_definition_kind(
            self.responsibility_permission_ceiling, "permission_policy", "responsibility_permission_ceiling"
        )
        for capability in self.capabilities:
            _require_definition_kind(capability, "capability", "capabilities")
        _require_definition_kind(self.permission_policy, "permission_policy", "permission_policy")
        _require_definition_kind(self.project_policy, "project_policy", "project_policy")
        for grant in self.operator_grants:
            _require_definition_kind(grant, "permission_policy", "operator_grants")
        grant_keys = tuple((grant.definition_id, grant.definition_version) for grant in self.operator_grants)
        if grant_keys != tuple(sorted(set(grant_keys))):
            raise ValueError("operator_grants must be sorted and unique")
        if bool(self.operator_grants) != (self.operator_grants_authorization is not None):
            raise ValueError("operator grants require exactly one authorization reference")
        if self.operator_grants_authorization is not None and self.operator_grants_authorization.kind not in {
            "lead_decision",
            "policy_exception",
        }:
            raise ValueError("operator grants authorization must reference a lead_decision or policy_exception")
        _require_unique(self.assignment_scope, "assignment scope paths")
        _require_definition_kind(self.guidance_bundle, "guidance_bundle", "guidance_bundle")
        _require_definition_kind(self.model_profile, "model_profile", "model_profile")
        _require_definition_kind(self.backend, "backend_definition", "backend")
        _require_unique(self.backend_supported_operations, "backend supported operations")
        _require_unique(self.backend_supported_resources, "backend supported resources")
        _require_unique(self.backend_limitations, "backend limitations")
        if self.host_isolation_authorization is not None and self.host_isolation_authorization.kind not in {
            "policy_exception",
            "attestation",
        }:
            raise ValueError("host isolation authorization must reference a policy_exception or attestation")
        expected_policy_digest = canonical_sha256(
            {
                "assignment": self.assignment,
                "pipeline_revision": self.pipeline_revision,
                "stage_id": self.stage_id,
                "stage_spec_digest": self.stage_spec_digest,
                "attempt_id": self.attempt_id,
                "responsibility_permission_ceiling": self.responsibility_permission_ceiling,
                "permission_policy": self.permission_policy,
                "project_policy": self.project_policy,
                "operator_grants": self.operator_grants,
                "operator_grants_authorization": self.operator_grants_authorization,
                "assignment_scope": self.assignment_scope,
                "backend": self.backend,
                "backend_supported_operations": self.backend_supported_operations,
                "backend_supported_resources": self.backend_supported_resources,
                "backend_limitations": self.backend_limitations,
                "host_isolation_authorization": self.host_isolation_authorization,
            }
        )
        if self.effective_policy_digest != expected_policy_digest:
            raise ValueError("effective_policy_digest does not match the pinned policy references")
        values = self.model_dump(mode="python", exclude={"resolved_digest"})
        if self.resolved_digest != canonical_sha256(values):
            raise ValueError("resolved_digest does not match the role instance payload")
        return self


def _definition_ref(definition_id: str, kind: str, definition_version: str, value: ReusableDefinition) -> DefinitionRef:
    return DefinitionRef(
        definition_id=definition_id,
        kind=kind,
        definition_version=definition_version,
        digest=canonical_sha256(value),
    )


def build_role_instance_payload(
    *,
    role_instance_id: str,
    assignment: RecordRef,
    pipeline_revision: RecordRef,
    stage_id: str,
    stage_spec_digest: str,
    attempt_id: str,
    agent_spec: AgentSpec,
    responsibility: Responsibility,
    responsibility_permission_ceiling: PermissionPolicy,
    capabilities: tuple[Capability, ...],
    permission_policy: PermissionPolicy,
    project_policy: ProjectPolicy,
    operator_grants: tuple[PermissionPolicy, ...],
    operator_grants_authorization: RecordRef | None,
    assignment_scope: tuple[ProjectPathPattern, ...],
    guidance_bundle: GuidanceBundle,
    model_profile: ModelProfile,
    backend: BackendDefinition,
    host_isolation_authorization: RecordRef | None = None,
) -> RoleInstance:
    """Build a role instance after a compiler has resolved all component definitions."""
    refs = {
        "agent_spec": _definition_ref(agent_spec.agent_spec_id, agent_spec.kind, agent_spec.definition_version, agent_spec),
        "responsibility": _definition_ref(
            responsibility.responsibility_id, responsibility.kind, responsibility.definition_version, responsibility
        ),
        "responsibility_permission_ceiling": _definition_ref(
            responsibility_permission_ceiling.policy_id,
            responsibility_permission_ceiling.kind,
            responsibility_permission_ceiling.definition_version,
            responsibility_permission_ceiling,
        ),
        "capabilities": tuple(
            _definition_ref(item.capability_id, item.kind, item.definition_version, item) for item in capabilities
        ),
        "permission_policy": _definition_ref(
            permission_policy.policy_id, permission_policy.kind, permission_policy.definition_version, permission_policy
        ),
        "project_policy": _definition_ref(
            project_policy.project_policy_id, project_policy.kind, project_policy.definition_version, project_policy
        ),
        "operator_grants": tuple(
            sorted(
                (
                    _definition_ref(item.policy_id, item.kind, item.definition_version, item)
                    for item in operator_grants
                ),
                key=lambda item: (item.definition_id, item.definition_version),
            )
        ),
        "guidance_bundle": _definition_ref(
            guidance_bundle.bundle_id, guidance_bundle.kind, guidance_bundle.definition_version, guidance_bundle
        ),
        "model_profile": _definition_ref(
            model_profile.profile_id, model_profile.kind, model_profile.definition_version, model_profile
        ),
        "backend": _definition_ref(backend.backend_id, backend.kind, backend.definition_version, backend),
    }
    expected_agent_refs = {
        "responsibility": refs["responsibility"],
        "capabilities": refs["capabilities"],
        "permission_policy": refs["permission_policy"],
        "guidance_bundle": refs["guidance_bundle"],
        "model_profile": refs["model_profile"],
    }
    for name, expected in expected_agent_refs.items():
        if getattr(agent_spec, name) != expected:
            raise ValueError(f"resolved {name} does not match the agent_spec reference")
    if model_profile.backend != refs["backend"]:
        raise ValueError("resolved backend does not match the model_profile reference")
    if responsibility.permission_ceiling != refs["responsibility_permission_ceiling"]:
        raise ValueError("resolved permission ceiling does not match the responsibility reference")
    if bool(refs["operator_grants"]) != (operator_grants_authorization is not None):
        raise ValueError("operator grants require exactly one authorization reference")
    values: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": "role_instance",
        "role_instance_id": role_instance_id,
        "assignment": assignment,
        "pipeline_revision": pipeline_revision,
        "stage_id": stage_id,
        "stage_spec_digest": stage_spec_digest,
        "attempt_id": attempt_id,
        "operator_grants_authorization": operator_grants_authorization,
        "assignment_scope": tuple(sorted(assignment_scope)),
        "backend_supported_operations": backend.supported_operations,
        "backend_supported_resources": backend.supported_resources,
        "backend_limitations": backend.limitations,
        "host_isolation_authorization": host_isolation_authorization,
        **refs,
    }
    values["effective_policy_digest"] = canonical_sha256(
        {
            name: values[name]
            for name in (
                "assignment",
                "pipeline_revision",
                "stage_id",
                "stage_spec_digest",
                "attempt_id",
                "responsibility_permission_ceiling",
                "permission_policy",
                "project_policy",
                "operator_grants",
                "operator_grants_authorization",
                "assignment_scope",
                "backend",
                "backend_supported_operations",
                "backend_supported_resources",
                "backend_limitations",
                "host_isolation_authorization",
            )
        }
    )
    values["resolved_digest"] = canonical_sha256(values)
    return RoleInstance.model_validate(values)


resolve_role_instance = build_role_instance_payload


class ContextItem(VersionedRecord):
    kind: Literal["context_item"]
    context_item_id: Identifier
    category: Literal["requirement", "design", "source", "evidence", "decision", "limitation"]
    summary: NonEmptyStr
    digest: Digest
    path: ProjectPath | None = None


class ContextPack(VersionedRecord):
    kind: Literal["context_pack"]
    context_pack_id: Identifier
    assignment: RecordRef
    items: tuple[RecordRef, ...]
    digest: Digest

    @model_validator(mode="after")
    def assignment_kind_is_valid(self) -> Self:
        _require_ref_kind(self.assignment, "assignment", "assignment")
        return self


class PipelineStageSpec(ContractModel):
    stage_id: Identifier
    stage: Stage
    agent_spec: DefinitionRef
    dependencies: tuple[Identifier, ...]
    optional: bool
    assurance_domain: AssuranceDomain | None = None

    @model_validator(mode="after")
    def stage_is_consistent(self) -> Self:
        _require_definition_kind(self.agent_spec, "agent_spec", "agent_spec")
        _require_unique(self.dependencies, "stage dependencies")
        if self.stage_id in self.dependencies:
            raise ValueError("a pipeline stage cannot depend on itself")
        if (self.stage == "assurance") != (self.assurance_domain is not None):
            raise ValueError("assurance_domain must be set if and only if stage is 'assurance'")
        if self.stage in {"implementation", "verification", "assurance", "review"} and self.optional:
            raise ValueError("implementation, verification, assurance, and review stages are required")
        if self.stage == "discovery" and self.optional:
            raise ValueError("discovery is required")
        if self.stage in {"architecture", "ux"} and not self.optional:
            raise ValueError("architecture and ux stages must be optional")
        return self


class PipelineDefinition(ReusableDefinition):
    kind: Literal["pipeline_definition"]
    pipeline_id: Identifier
    name: NonEmptyStr
    stages: tuple[PipelineStageSpec, ...]

    @model_validator(mode="after")
    def pipeline_is_valid(self) -> Self:
        _validate_pipeline_stages(self.stages)
        return self


class PipelinePlan(VersionedRecord):
    kind: Literal["pipeline_plan"]
    plan_id: Identifier
    pipeline: DefinitionRef
    work_item: RecordRef
    stages: tuple[PipelineStageSpec, ...]
    approved_by: ActorRef
    approved_at: UtcDateTime

    @model_validator(mode="after")
    def plan_is_valid(self) -> Self:
        _require_definition_kind(self.pipeline, "pipeline_definition", "pipeline")
        _require_ref_kind(self.work_item, "work_item", "work_item")
        if self.approved_by.kind != "project_lead":
            raise ValueError("a pipeline plan must be approved by a project_lead")
        _validate_pipeline_stages(self.stages)
        return self


class FrozenStageDigest(ContractModel):
    stage_id: Identifier
    stage_spec_digest: Digest


class ParentStageDigest(ContractModel):
    stage_id: Identifier
    digest: Digest = Field(
        description=(
            "Digest pinned from the same stage in the resolved parent revision; the compiler MUST verify it "
            "against that external parent revision."
        )
    )


class PipelineRevision(VersionedRecord):
    kind: Literal["pipeline_revision"]
    revision_id: Identifier
    plan: RecordRef
    revision_number: Annotated[int, Field(ge=1)]
    parent_revision: RecordRef | None = None
    stages: tuple[PipelineStageSpec, ...]
    frozen_stage_ids: tuple[Identifier, ...]
    frozen_stage_digests: tuple[FrozenStageDigest, ...]
    parent_stage_digests: tuple[ParentStageDigest, ...] = Field(
        description=(
            "Parent revision stage digests supplied after resolution; the compiler MUST verify these values "
            "against the resolved parent_revision record."
        )
    )
    applies_from_stage: Identifier
    reason: NonEmptyStr
    approving_decision: RecordRef
    created_at: UtcDateTime

    @model_validator(mode="after")
    def revision_is_valid(self) -> Self:
        _require_ref_kind(self.plan, "pipeline_plan", "plan")
        _require_ref_kind(self.approving_decision, "lead_decision", "approving_decision")
        if self.revision_number == 1 and self.parent_revision is not None:
            raise ValueError("revision 1 must not have a parent revision")
        if self.revision_number == 1 and self.parent_stage_digests:
            raise ValueError("revision 1 must not have parent stage digests")
        if self.revision_number > 1:
            if self.parent_revision is None:
                raise ValueError("revisions after revision 1 require a parent revision")
            _require_ref_kind(self.parent_revision, "pipeline_revision", "parent_revision")
        _validate_pipeline_stages(self.stages)
        stage_by_id = {stage.stage_id: stage for stage in self.stages}
        if self.applies_from_stage not in stage_by_id:
            raise ValueError("applies_from_stage must identify a stage in the revision")
        applies_index = tuple(stage_by_id).index(self.applies_from_stage)
        required_frozen = set(tuple(stage_by_id)[:applies_index])
        _require_unique(self.frozen_stage_ids, "frozen stage IDs")
        unknown_frozen = set(self.frozen_stage_ids) - stage_by_id.keys()
        if unknown_frozen:
            raise ValueError("frozen_stage_ids must identify stages in the revision")
        _require_unique((item.stage_id for item in self.frozen_stage_digests), "frozen stage digest IDs")
        digest_by_id = {item.stage_id: item.stage_spec_digest for item in self.frozen_stage_digests}
        if set(digest_by_id) != set(self.frozen_stage_ids):
            raise ValueError("frozen_stage_digests must exactly map frozen_stage_ids")
        if set(self.frozen_stage_ids) != required_frozen:
            raise ValueError("all and only stages before applies_from_stage must be frozen")
        for stage_id, expected_digest in digest_by_id.items():
            if pipeline_stage_digest(stage_by_id[stage_id]) != expected_digest:
                raise ValueError(f"frozen stage {stage_id!r} differs from its pinned digest")
        _require_unique((item.stage_id for item in self.parent_stage_digests), "parent stage digest IDs")
        parent_digest_by_id = {item.stage_id: item.digest for item in self.parent_stage_digests}
        if self.revision_number > 1:
            if set(parent_digest_by_id) != set(self.frozen_stage_ids):
                raise ValueError("parent_stage_digests must exactly map frozen_stage_ids")
            for stage_id, frozen_digest in digest_by_id.items():
                if parent_digest_by_id[stage_id] != frozen_digest:
                    raise ValueError(f"frozen stage {stage_id!r} must equal its parent-stage digest")
        return self


class LeadDecision(VersionedRecord):
    kind: Literal["lead_decision"]
    decision_id: Identifier
    decision: Literal["approve", "reject", "return", "escalate", "cancel"]
    subject: RecordRef
    rationale: NonEmptyStr
    decided_by: ActorRef
    decided_at: UtcDateTime

    @model_validator(mode="after")
    def decision_is_authorized(self) -> Self:
        if self.decided_by.kind != "project_lead":
            raise ValueError("a LeadDecision must be decided by a project_lead")
        return self


class QuestionBody(ContractModel):
    kind: Literal["question"]
    question: NonEmptyStr


class ResponseBody(ContractModel):
    kind: Literal["response"]
    question: RecordRef
    response: NonEmptyStr


class ContextGapBody(ContractModel):
    kind: Literal["context_gap"]
    missing: tuple[NonEmptyStr, ...]
    impact: NonEmptyStr


class BlockerBody(ContractModel):
    kind: Literal["blocker"]
    summary: NonEmptyStr
    recovery_needed: NonEmptyStr


class ConflictBody(ContractModel):
    kind: Literal["conflict"]
    summary: NonEmptyStr
    conflicting_records: tuple[RecordRef, ...]


class PipelineChangeRequestBody(ContractModel):
    kind: Literal["pipeline_change_request"]
    requested_stages: tuple[PipelineStageSpec, ...]
    rationale: NonEmptyStr
    discovery_candidate: RecordRef

    @model_validator(mode="after")
    def candidate_kind_is_valid(self) -> Self:
        _require_ref_kind(self.discovery_candidate, "candidate_report", "discovery_candidate")
        return self


class WorkItemProposalBody(ContractModel):
    kind: Literal["work_item_proposal"]
    title: NonEmptyStr
    objective: NonEmptyStr
    acceptance_criteria: tuple[AcceptanceCriterion, ...]


class CandidateReadyBody(ContractModel):
    kind: Literal["candidate_ready"]
    candidate: RecordRef


class VerificationDefectBody(ContractModel):
    kind: Literal["verification_defect"]
    summary: NonEmptyStr
    criterion_ids: tuple[Identifier, ...]
    evidence: tuple[RecordRef, ...]


class AssuranceFindingBody(ContractModel):
    kind: Literal["assurance_finding"]
    domain: AssuranceDomain
    severity: Literal["low", "medium", "high", "critical"]
    summary: NonEmptyStr
    evidence: tuple[RecordRef, ...] = ()


class LeadDecisionBody(ContractModel):
    kind: Literal["lead_decision"]
    decision: RecordRef

    @model_validator(mode="after")
    def decision_kind_is_valid(self) -> Self:
        _require_ref_kind(self.decision, "lead_decision", "decision")
        return self


class AcknowledgementBody(ContractModel):
    kind: Literal["acknowledgement"]
    acknowledged_message: RecordRef


class CancellationBody(ContractModel):
    kind: Literal["cancellation"]
    target: RecordRef
    reason: NonEmptyStr


MessageBody = Annotated[
    QuestionBody
    | ResponseBody
    | ContextGapBody
    | BlockerBody
    | ConflictBody
    | PipelineChangeRequestBody
    | WorkItemProposalBody
    | CandidateReadyBody
    | VerificationDefectBody
    | AssuranceFindingBody
    | LeadDecisionBody
    | AcknowledgementBody
    | CancellationBody,
    Field(discriminator="kind"),
]


class MailboxMessage(VersionedRecord):
    kind: Literal["mailbox_message"]
    message_id: Identifier
    sender: ActorRef
    recipient: ActorRef
    correlation_id: Identifier
    idempotency_key: Identifier
    created_at: UtcDateTime
    body: MessageBody

    @model_validator(mode="after")
    def route_is_authorized(self) -> Self:
        agent_to_orchestrator = self.sender.kind == "agent" and self.recipient.kind == "orchestrator"
        authority_to_agent = self.sender.kind in {"orchestrator", "project_lead"} and self.recipient.kind == "agent"
        if not (agent_to_orchestrator or authority_to_agent):
            raise ValueError("mailbox routes must be agent->orchestrator or orchestrator/project_lead->agent")
        if isinstance(self.body, LeadDecisionBody) and not (
            self.sender.kind == "project_lead" and self.recipient.kind == "agent"
        ):
            raise ValueError("a LeadDecision body must be sent by a project_lead to an agent")
        if isinstance(self.body, CancellationBody) and not authority_to_agent:
            raise ValueError("a Cancellation body must be sent by an authority to an agent")
        return self


class CriterionDisposition(ContractModel):
    criterion_id: Identifier
    disposition: Literal["claimed_satisfied", "verified", "unsatisfied", "not_evaluated"]
    evidence: tuple[RecordRef, ...] = ()
    evidence_types: tuple[EvidenceType, ...] = ()
    note: NonEmptyStr | None = None

    @model_validator(mode="after")
    def satisfied_has_evidence(self) -> Self:
        if self.disposition in {"claimed_satisfied", "verified"} and (not self.evidence or not self.evidence_types):
            raise ValueError("a claimed or verified criterion requires evidence and evidence types")
        if bool(self.evidence) != bool(self.evidence_types):
            raise ValueError("criterion evidence and evidence types must be supplied together")
        return self


class CandidateReport(VersionedRecord):
    kind: Literal["candidate_report"]
    candidate_report_id: Identifier
    work_item: RecordRef
    pipeline_revision: RecordRef
    assignment: RecordRef
    role_instance: RecordRef
    stage: Stage
    stage_id: Identifier
    stage_spec_digest: Digest
    attempt_id: Identifier
    context_pack: RecordRef
    change_set: RecordRef | None = None
    outcome: Literal["succeeded", "correction_needed", "blocked"]
    criterion_ids: tuple[Identifier, ...]
    criterion_dispositions: tuple[CriterionDisposition, ...]
    findings: tuple[NonEmptyStr, ...] = ()
    limitations: tuple[NonEmptyStr, ...] = ()
    evidence: tuple[RecordRef, ...] = ()
    produced_at: UtcDateTime

    @model_validator(mode="after")
    def report_is_complete_and_pinned(self) -> Self:
        _require_ref_kind(self.work_item, "work_item", "work_item")
        _require_ref_kind(self.pipeline_revision, "pipeline_revision", "pipeline_revision")
        _require_ref_kind(self.assignment, "assignment", "assignment")
        _require_ref_kind(self.role_instance, "role_instance", "role_instance")
        _require_ref_kind(self.context_pack, "context_pack", "context_pack")
        if self.change_set is not None:
            _require_ref_kind(self.change_set, "change_set", "change_set")
        if self.stage in {"architecture", "ux", "implementation", "verification"} and self.change_set is None:
            raise ValueError("architecture, ux, implementation, and verification candidates require a change_set")
        if self.stage in {"assurance", "review"} and self.change_set is not None:
            raise ValueError("read-only assurance and review candidates forbid a change_set")
        if not self.criterion_ids:
            raise ValueError("candidate criterion_ids must be nonempty")
        _require_unique(self.criterion_ids, "candidate criterion IDs")
        disposition_ids = tuple(item.criterion_id for item in self.criterion_dispositions)
        _require_unique(disposition_ids, "candidate criterion disposition IDs")
        if set(disposition_ids) != set(self.criterion_ids):
            raise ValueError("candidate dispositions must exactly match the pinned criterion IDs")
        if self.outcome == "succeeded":
            if any(item.disposition == "unsatisfied" for item in self.criterion_dispositions):
                raise ValueError("a succeeded candidate cannot report an unsatisfied criterion")
        return self


class ChangeEntry(ContractModel):
    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"action": {"const": "create"}}, "required": ["action"]},
                    "then": {
                        "properties": {"before_digest": {"type": "null"}, "after_digest": {"type": "string"}},
                        "required": ["after_digest"],
                    },
                },
                {
                    "if": {"properties": {"action": {"const": "modify"}}, "required": ["action"]},
                    "then": {"required": ["before_digest", "after_digest"]},
                },
                {
                    "if": {"properties": {"action": {"const": "delete"}}, "required": ["action"]},
                    "then": {
                        "properties": {"after_digest": {"type": "null"}, "before_digest": {"type": "string"}},
                        "required": ["before_digest"],
                    },
                },
            ]
        }
    )

    path: ProjectPath
    action: Literal["create", "modify", "delete"]
    before_digest: Digest | None = None
    after_digest: Digest | None = None

    @model_validator(mode="after")
    def digests_match_action(self) -> Self:
        valid = {
            "create": self.before_digest is None and self.after_digest is not None,
            "modify": self.before_digest is not None and self.after_digest is not None,
            "delete": self.before_digest is not None and self.after_digest is None,
        }
        if not valid[self.action]:
            raise ValueError("before_digest and after_digest do not match the change action")
        if self.action == "modify" and self.before_digest == self.after_digest:
            raise ValueError("a modified entry must change its digest")
        return self


class ChangeSet(VersionedRecord):
    kind: Literal["change_set"]
    change_set_id: Identifier
    base_manifest_digest: Digest
    final_manifest_digest: Digest
    entries: tuple[ChangeEntry, ...]
    created_at: UtcDateTime

    @model_validator(mode="after")
    def paths_are_unique_and_sorted(self) -> Self:
        _require_sorted_unique_paths((entry.path for entry in self.entries), "change set")
        return self


class EvidenceArtifact(VersionedRecord):
    kind: Literal["evidence_artifact"]
    evidence_id: Identifier
    evidence_type: EvidenceType
    path: ProjectPath
    digest: Digest
    size_bytes: Annotated[int, Field(ge=0)]
    producer: ActorRef
    created_at: UtcDateTime


class VerificationCriterion(ContractModel):
    criterion_id: Identifier
    statement: NonEmptyStr
    required_evidence_types: tuple[EvidenceType, ...]
    verification: MachineVerificationSpec | None = None


class VerificationPlan(VersionedRecord):
    kind: Literal["verification_plan"]
    verification_plan_id: Identifier
    work_item: RecordRef
    criteria: tuple[VerificationCriterion, ...]
    commands: tuple[tuple[NonEmptyStr, ...], ...]
    created_at: UtcDateTime

    @model_validator(mode="after")
    def criterion_ids_are_stable(self) -> Self:
        _require_ref_kind(self.work_item, "work_item", "work_item")
        if not self.criteria:
            raise ValueError("a verification plan requires criteria")
        _require_unique((criterion.criterion_id for criterion in self.criteria), "verification criterion IDs")
        expected_commands = tuple(
            criterion.verification.verifier_argv
            for criterion in self.criteria
            if criterion.verification is not None
        )
        if (
            len(expected_commands) != len(self.criteria)
            or len(set(expected_commands)) != len(expected_commands)
            or any(self.commands.count(command) != 1 for command in expected_commands)
        ):
            raise ValueError(
                "verification plan must contain one unique verifier_argv for every criterion"
            )
        return self


class StageSession(VersionedRecord):
    kind: Literal["stage_session"]
    stage_session_id: Identifier
    role_instance: RecordRef
    stage_id: Identifier
    attempt_id: Identifier
    backend_session_id: NonEmptyStr
    context_digest: Digest
    workspace: NonEmptyStr
    created_at: UtcDateTime

    @model_validator(mode="after")
    def role_kind_is_valid(self) -> Self:
        _require_ref_kind(self.role_instance, "role_instance", "role_instance")
        return self


class VerificationRun(VersionedRecord):
    kind: Literal["verification_run"]
    verification_run_id: Identifier
    plan: RecordRef
    candidate: RecordRef
    change_set: RecordRef
    workspace_digest: Digest
    command: tuple[NonEmptyStr, ...]
    exit_code: int
    duration_seconds: Annotated[float, Field(ge=0)]
    evidence: tuple[RecordRef, ...]
    started_at: UtcDateTime
    finished_at: UtcDateTime

    @model_validator(mode="after")
    def run_is_bound(self) -> Self:
        _require_ref_kind(self.plan, "verification_plan", "plan")
        _require_ref_kind(self.candidate, "candidate_report", "candidate")
        _require_ref_kind(self.change_set, "change_set", "change_set")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        return self


class CriterionResult(ContractModel):
    criterion_id: Identifier
    command_indexes: tuple[Annotated[int, Field(ge=0)], ...]
    disposition: Literal["pass", "fail", "not_run"]
    evidence: tuple[RecordRef, ...] = ()

    @model_validator(mode="after")
    def passing_results_have_evidence(self) -> Self:
        _require_unique(self.command_indexes, "criterion command indexes")
        if self.disposition == "pass" and not self.evidence:
            raise ValueError("a passing criterion result requires evidence")
        if self.disposition == "not_run" and self.command_indexes:
            raise ValueError("a not_run criterion result cannot bind commands")
        if self.disposition != "not_run" and not self.command_indexes:
            raise ValueError("a run criterion result requires command indexes")
        return self


class RunBinding(ContractModel):
    run: RecordRef
    plan: RecordRef
    candidate: RecordRef
    change_set: RecordRef
    workspace_digest: Digest

    @model_validator(mode="after")
    def reference_kinds_are_valid(self) -> Self:
        _require_ref_kind(self.run, "verification_run", "run")
        _require_ref_kind(self.plan, "verification_plan", "plan")
        _require_ref_kind(self.candidate, "candidate_report", "candidate")
        _require_ref_kind(self.change_set, "change_set", "change_set")
        return self


class VerificationReceipt(VersionedRecord):
    kind: Literal["verification_receipt"]
    verification_receipt_id: Identifier
    plan: RecordRef
    candidate: RecordRef
    change_set: RecordRef
    workspace_digest: Digest
    run_bindings: tuple[RunBinding, ...]
    criterion_ids: tuple[Identifier, ...]
    criterion_results: tuple[CriterionResult, ...]
    accepted: bool
    producer_role_instance_id: Identifier
    issued_by: ActorRef
    issued_at: UtcDateTime

    @model_validator(mode="after")
    def receipt_is_complete_and_bound(self) -> Self:
        _require_ref_kind(self.plan, "verification_plan", "plan")
        _require_ref_kind(self.candidate, "candidate_report", "candidate")
        _require_ref_kind(self.change_set, "change_set", "change_set")
        if not self.run_bindings:
            raise ValueError("a verification receipt requires at least one run")
        _require_unique((binding.run.record_id for binding in self.run_bindings), "verification run IDs")
        for binding in self.run_bindings:
            if (
                binding.plan != self.plan
                or binding.candidate != self.candidate
                or binding.change_set != self.change_set
                or binding.workspace_digest != self.workspace_digest
            ):
                raise ValueError("every run binding must match the receipt plan, candidate, change set, and workspace")
        if not self.criterion_ids:
            raise ValueError("receipt criterion_ids must be nonempty")
        _require_unique(self.criterion_ids, "receipt criterion IDs")
        result_ids = tuple(result.criterion_id for result in self.criterion_results)
        _require_unique(result_ids, "criterion result IDs")
        if set(result_ids) != set(self.criterion_ids):
            raise ValueError("criterion results must exactly match the pinned plan criterion IDs")
        if self.accepted and any(result.disposition != "pass" for result in self.criterion_results):
            raise ValueError("an accepted receipt requires every criterion to pass")
        if self.issued_by.kind != "agent":
            raise ValueError("a verification receipt issuer must be an agent")
        if self.producer_role_instance_id == self.issued_by.role_instance_id:
            raise ValueError("a verification receipt issuer must be independent from its producer")
        return self


class SemanticFinding(ContractModel):
    summary: NonEmptyStr
    severity: Literal["low", "medium", "high", "critical"]
    blocking: bool
    resolved: bool = False

    @property
    def unresolved_blocking(self) -> bool:
        return not self.resolved and (self.blocking or self.severity in {"high", "critical"})


class AssuranceDisposition(ContractModel):
    domain: AssuranceDomain
    disposition: Literal["pass", "fail", "not_applicable"]
    findings: tuple[SemanticFinding, ...] = ()
    evidence: tuple[RecordRef, ...] = ()

    @model_validator(mode="after")
    def passing_disposition_has_no_blocking_findings(self) -> Self:
        if self.disposition == "pass" and any(item.unresolved_blocking for item in self.findings):
            raise ValueError("a passing assurance disposition cannot contain unresolved blocking findings")
        return self


class AssuranceReport(VersionedRecord):
    kind: Literal["assurance_report"]
    assurance_report_id: Identifier
    candidate: RecordRef
    producer_role_instance_id: Identifier
    dispositions: tuple[AssuranceDisposition, ...]
    auditor: ActorRef
    produced_at: UtcDateTime

    @model_validator(mode="after")
    def report_is_independent_and_unique(self) -> Self:
        _require_ref_kind(self.candidate, "candidate_report", "candidate")
        if self.auditor.kind != "agent":
            raise ValueError("an assurance report auditor must be an agent")
        if not self.dispositions:
            raise ValueError("an assurance report requires dispositions")
        _require_unique((item.domain for item in self.dispositions), "assurance report domains")
        if self.producer_role_instance_id == self.auditor.role_instance_id:
            raise ValueError("an assurance report auditor must be independent from its producer")
        return self


class ReviewDecision(VersionedRecord):
    kind: Literal["review_decision"]
    review_decision_id: Identifier
    candidate: RecordRef
    producer_role_instance_id: Identifier
    decision: Literal["ACCEPT", "RETURN", "BLOCK"]
    rationale: NonEmptyStr
    findings: tuple[SemanticFinding, ...] = ()
    evidence: tuple[RecordRef, ...] = ()
    verification_receipts: tuple[RecordRef, ...] = ()
    reviewer: ActorRef
    decided_at: UtcDateTime

    @model_validator(mode="after")
    def decision_is_authorized_and_supported(self) -> Self:
        _require_ref_kind(self.candidate, "candidate_report", "candidate")
        if self.reviewer.kind != "agent":
            raise ValueError("a ReviewDecision reviewer must be an agent")
        if self.producer_role_instance_id == self.reviewer.role_instance_id:
            raise ValueError("a ReviewDecision reviewer must be independent from its producer")
        for receipt in self.verification_receipts:
            _require_ref_kind(receipt, "verification_receipt", "verification_receipts")
        if self.decision == "ACCEPT" and (not self.evidence or not self.verification_receipts):
            raise ValueError("ACCEPT requires evidence and verification receipt references")
        if self.decision == "ACCEPT" and any(item.unresolved_blocking for item in self.findings):
            raise ValueError("ACCEPT cannot contain unresolved blocking findings")
        return self


class LifecycleEvent(VersionedRecord):
    kind: Literal["lifecycle_event"]
    event_id: Identifier
    aggregate_version: Annotated[int, Field(ge=1)]
    previous_event_digest: Digest | None = None
    event_type: LifecycleEventType
    from_status: ProjectStatus
    to_status: ProjectStatus
    actor: ActorRef
    subject: RecordRef
    summary: NonEmptyStr
    occurred_at: UtcDateTime

    @model_validator(mode="after")
    def event_chain_is_valid(self) -> Self:
        if self.aggregate_version == 1 and self.previous_event_digest is not None:
            raise ValueError("aggregate version 1 must not have a previous event digest")
        if self.aggregate_version > 1 and self.previous_event_digest is None:
            raise ValueError("later aggregate versions require a previous event digest")
        if (self.from_status, self.to_status) not in ALLOWED_PROJECT_STATUS_TRANSITIONS:
            raise ValueError("lifecycle status transition is not allowed")
        if self.event_type in {LifecycleEventType.STATUS_CHANGED, LifecycleEventType.PROJECT_CLOSED}:
            _require_ref_kind(self.subject, "project_state", "subject")
        if self.event_type == LifecycleEventType.PROJECT_CLOSED and (self.from_status, self.to_status) != (
            "sealed",
            "closed",
        ):
            raise ValueError("PROJECT_CLOSED only permits sealed to closed")
        return self


class ManifestEntry(ContractModel):
    path: ProjectPath
    digest: Digest
    size_bytes: Annotated[int, Field(ge=0)]


class ManifestDigestPayload(ContractModel):
    entries: tuple[ManifestEntry, ...]

    @model_validator(mode="after")
    def entries_are_unique_and_sorted(self) -> Self:
        _require_sorted_unique_paths((entry.path for entry in self.entries), "manifest")
        return self


def build_manifest_root_digest(entries: tuple[ManifestEntry, ...] | list[ManifestEntry]) -> str:
    payload = ManifestDigestPayload(entries=TypeAdapter(tuple[ManifestEntry, ...]).validate_python(entries))
    return canonical_sha256(payload)


class ProjectManifest(VersionedRecord):
    kind: Literal["project_manifest"]
    manifest_id: Identifier
    entries: tuple[ManifestEntry, ...]
    root_digest: Digest
    created_at: UtcDateTime

    @model_validator(mode="after")
    def root_digest_matches_entries(self) -> Self:
        expected = build_manifest_root_digest(self.entries)
        if self.root_digest != expected:
            raise ValueError("root_digest does not match the validated manifest entries")
        return self


class ProjectState(VersionedRecord):
    kind: Literal["project_state"]
    project_id: Identifier
    status: ProjectStatus
    pipeline_revision: RecordRef | None = None
    active_assignments: tuple[RecordRef, ...] = ()
    candidate_seal: RecordRef | None = None
    last_event_sequence: Annotated[int, Field(ge=0)] = 0
    updated_at: UtcDateTime

    @model_validator(mode="after")
    def state_is_consistent(self) -> Self:
        if self.pipeline_revision is not None:
            _require_ref_kind(self.pipeline_revision, "pipeline_revision", "pipeline_revision")
        for assignment in self.active_assignments:
            _require_ref_kind(assignment, "assignment", "active_assignments")
        _require_unique((assignment.record_id for assignment in self.active_assignments), "active assignment IDs")
        if self.status in {"sealed", "closed"} and self.candidate_seal is None:
            raise ValueError("sealed and closed project states require a candidate_seal")
        if self.status in {"sealed", "closed"} and self.active_assignments:
            raise ValueError("sealed and closed project states forbid active assignments")
        if self.candidate_seal is not None:
            _require_ref_kind(self.candidate_seal, "candidate_seal", "candidate_seal")
        return self


class RequiredStageCandidate(ContractModel):
    stage_id: Identifier
    candidate: RecordRef

    @model_validator(mode="after")
    def candidate_kind_is_valid(self) -> Self:
        _require_ref_kind(self.candidate, "candidate_report", "candidate")
        return self


class CandidateSealPayload(ContractModel):
    schema_version: Literal["2.0"]
    project_id: Identifier
    work_item: RecordRef
    pipeline_revision: RecordRef
    required_stage_ids: tuple[Identifier, ...]
    role_instances: tuple[RecordRef, ...]
    context_packs: tuple[RecordRef, ...]
    stage_candidates: tuple[RequiredStageCandidate, ...]
    base_manifest: RecordRef
    final_manifest: RecordRef
    cumulative_change_set: RecordRef
    verification_receipts: tuple[RecordRef, ...]
    assurance_report: RecordRef
    acceptance_review: RecordRef
    lead_decision: RecordRef
    compiler_version: NonEmptyStr
    verification_accepted: Literal[True]
    verification_fresh: Literal[True]
    assurance_accepted: Literal[True]
    acceptance_accepted: Literal[True]
    lead_approved: Literal[True]

    @model_validator(mode="after")
    def payload_references_are_complete(self) -> Self:
        _require_ref_kind(self.work_item, "work_item", "work_item")
        _require_ref_kind(self.pipeline_revision, "pipeline_revision", "pipeline_revision")
        _require_nonempty_refs(self.role_instances, "role_instances", "role_instance")
        _require_nonempty_refs(self.context_packs, "context_packs", "context_pack")
        if not self.required_stage_ids:
            raise ValueError("required_stage_ids must be nonempty")
        _require_unique(self.required_stage_ids, "required stage IDs")
        if tuple(sorted(self.required_stage_ids)) != self.required_stage_ids:
            raise ValueError("required_stage_ids must be sorted")
        stage_ids = tuple(item.stage_id for item in self.stage_candidates)
        if tuple(sorted(stage_ids)) != stage_ids:
            raise ValueError("stage_candidates must be sorted by stage_id")
        _require_unique(stage_ids, "stage candidate IDs")
        _require_unique((item.candidate.record_id for item in self.stage_candidates), "stage candidate references")
        if stage_ids != self.required_stage_ids:
            raise ValueError("stage_candidates must exactly cover required_stage_ids")
        _require_ref_kind(self.base_manifest, "project_manifest", "base_manifest")
        _require_ref_kind(self.final_manifest, "project_manifest", "final_manifest")
        _require_ref_kind(self.cumulative_change_set, "change_set", "cumulative_change_set")
        _require_nonempty_refs(self.verification_receipts, "verification_receipts", "verification_receipt")
        _require_ref_kind(self.assurance_report, "assurance_report", "assurance_report")
        _require_ref_kind(self.acceptance_review, "review_decision", "acceptance_review")
        _require_ref_kind(self.lead_decision, "lead_decision", "lead_decision")
        return self


_CANDIDATE_PAYLOAD_FIELDS = tuple(CandidateSealPayload.model_fields)


def build_candidate_seal_payload(**values: Any) -> CandidateSealPayload:
    """Validate and return exactly the non-self-referential candidate inputs."""
    return CandidateSealPayload.model_validate(values)


class CandidateSeal(VersionedRecord):
    kind: Literal["candidate_seal"]
    seal_id: Identifier
    candidate_digest: Digest
    project_id: Identifier
    work_item: RecordRef
    pipeline_revision: RecordRef
    required_stage_ids: tuple[Identifier, ...]
    role_instances: tuple[RecordRef, ...]
    context_packs: tuple[RecordRef, ...]
    stage_candidates: tuple[RequiredStageCandidate, ...]
    base_manifest: RecordRef
    final_manifest: RecordRef
    cumulative_change_set: RecordRef
    verification_receipts: tuple[RecordRef, ...]
    assurance_report: RecordRef
    acceptance_review: RecordRef
    lead_decision: RecordRef
    compiler_version: NonEmptyStr
    verification_accepted: Literal[True]
    verification_fresh: Literal[True]
    assurance_accepted: Literal[True]
    acceptance_accepted: Literal[True]
    lead_approved: Literal[True]
    sealed_by: ActorRef
    sealed_at: UtcDateTime

    @model_validator(mode="after")
    def seal_is_authorized_and_matches_payload(self) -> Self:
        payload = build_candidate_seal_payload(**{name: getattr(self, name) for name in _CANDIDATE_PAYLOAD_FIELDS})
        if self.candidate_digest != canonical_sha256(payload):
            raise ValueError("candidate_digest does not match the validated candidate seal payload")
        if self.seal_id != f"seal-{self.candidate_digest}":
            raise ValueError("seal_id must deterministically equal 'seal-' plus candidate_digest")
        if self.sealed_by.kind not in {"project_lead", "launcher"}:
            raise ValueError("a candidate seal must be sealed by a project_lead or authorized launcher")
        return self


def create_candidate_seal(*, sealed_by: ActorRef, sealed_at: UtcDateTime, **values: Any) -> CandidateSeal:
    """Create a deterministic seal from resolved references and observed eligibility inputs."""
    payload_values = dict(values)
    payload_values.setdefault("schema_version", SCHEMA_VERSION)
    payload = build_candidate_seal_payload(**payload_values)
    digest = canonical_sha256(payload)
    return CandidateSeal(
        kind="candidate_seal",
        seal_id=f"seal-{digest}",
        candidate_digest=digest,
        **payload.model_dump(mode="python"),
        sealed_by=sealed_by,
        sealed_at=sealed_at,
    )


class PolicyRuleSnapshot(ContractModel):
    policy: DefinitionRef
    rule: PermissionRule
    rule_digest: Digest

    @model_validator(mode="after")
    def snapshot_is_content_addressed(self) -> Self:
        if self.policy.kind not in {"permission_policy", "project_policy"}:
            raise ValueError("a policy rule must reference a permission_policy or project_policy")
        if self.rule_digest != canonical_sha256(self.rule):
            raise ValueError("rule_digest does not match the canonical permission rule")
        return self


class PolicyException(VersionedRecord):
    kind: Literal["policy_exception"]
    policy_exception_id: Identifier
    rule: PolicyRuleSnapshot
    scope: tuple[ProjectPathPattern, ...]
    reason: NonEmptyStr
    evidence: tuple[RecordRef, ...]
    compensating_verification: NonEmptyStr
    expires_at: UtcDateTime
    approving_lead_decision: RecordRef

    @model_validator(mode="after")
    def exception_is_soft_and_supported(self) -> Self:
        if self.rule.rule.exception_class != "soft":
            raise ValueError("hard policy rules cannot be excepted")
        if not self.evidence:
            raise ValueError("a policy exception requires evidence")
        _require_ref_kind(self.approving_lead_decision, "lead_decision", "approving_lead_decision")
        return self


def pipeline_stage_digest(stage: PipelineStageSpec) -> str:
    return canonical_sha256(stage)


def _validate_pipeline_stages(stages: tuple[PipelineStageSpec, ...]) -> None:
    if not stages:
        raise ValueError("a pipeline requires nonempty stages")
    stage_ids = tuple(stage.stage_id for stage in stages)
    _require_unique(stage_ids, "pipeline stage IDs")
    stage_id_set = set(stage_ids)
    for stage in stages:
        unknown = set(stage.dependencies) - stage_id_set
        if unknown:
            raise ValueError(f"stage {stage.stage_id!r} has unknown dependencies")
    for required_stage in ("discovery", "implementation", "verification", "assurance", "review"):
        if sum(stage.stage == required_stage for stage in stages) != 1:
            raise ValueError(f"a first-canary pipeline requires exactly one {required_stage} stage")
    for optional_stage in ("architecture", "ux"):
        if sum(stage.stage == optional_stage for stage in stages) > 1:
            raise ValueError(f"a first-canary pipeline permits at most one {optional_stage} stage")
    selected = ["discovery"]
    if any(stage.stage == "architecture" for stage in stages):
        selected.append("architecture")
    if any(stage.stage == "ux" for stage in stages):
        selected.append("ux")
    selected.extend(("implementation", "verification", "assurance", "review"))
    actual = [stage.stage for stage in stages]
    if actual != selected:
        raise ValueError("first-canary stages must be in exact serial stage order")
    for index, item in enumerate(stages):
        expected = () if index == 0 else (stages[index - 1].stage_id,)
        if item.dependencies != expected:
            raise ValueError("first-canary stages must form a serial chain with no extra dependencies")


def validate_wire(model_type: type[ContractModel], data: Any) -> ContractModel:
    """Validate catalog wire data, allowing only ordinary container conversion."""
    # JSON-mode validation converts arrays/objects while strict contract fields still reject scalar coercion.
    return model_type.model_validate_json(canonical_json(data), strict=True)


def _require_unique(values: Any, label: str) -> None:
    materialized = tuple(values)
    if len(materialized) != len(set(materialized)):
        raise ValueError(f"{label} must be unique")


def _require_sorted_unique_paths(values: Any, label: str) -> None:
    paths = tuple(values)
    if tuple(sorted(paths)) != paths:
        raise ValueError(f"{label} paths must be sorted")
    _require_unique(paths, f"{label} paths")


def _require_ref_kind(reference: RecordRef, expected: str, field_name: str) -> None:
    if reference.kind != expected:
        raise ValueError(f"{field_name} must reference kind {expected!r}")


def _require_definition_kind(reference: DefinitionRef, expected: str, field_name: str) -> None:
    if reference.kind != expected:
        raise ValueError(f"{field_name} must reference definition kind {expected!r}")


def _require_nonempty_refs(references: tuple[RecordRef, ...], field_name: str, expected_kind: str) -> None:
    if not references:
        raise ValueError(f"{field_name} must be nonempty")
    for reference in references:
        _require_ref_kind(reference, expected_kind, field_name)
    _require_unique((reference.record_id for reference in references), f"{field_name} references")


TOP_LEVEL_MODELS: tuple[type[VersionedRecord], ...] = (
    Responsibility,
    Capability,
    PermissionPolicy,
    ProjectPolicy,
    GuidanceModule,
    GuidanceBundle,
    BackendDefinition,
    ModelProfile,
    AgentSpec,
    WorkItem,
    Assignment,
    RoleInstance,
    ContextItem,
    ContextPack,
    PipelineDefinition,
    PipelinePlan,
    PipelineRevision,
    LeadDecision,
    MailboxMessage,
    CandidateReport,
    ChangeSet,
    EvidenceArtifact,
    VerificationPlan,
    StageSession,
    VerificationRun,
    VerificationReceipt,
    AssuranceReport,
    ReviewDecision,
    LifecycleEvent,
    ProjectManifest,
    ProjectState,
    CandidateSeal,
    PolicyException,
)

__all__ = [
    "SCHEMA_VERSION",
    "AssuranceDomain",
    "EvidenceType",
    "PermissionOperation",
    "PermissionResource",
    "LifecycleEventType",
    "DefinitionRef",
    "RecordRef",
    "ActorRef",
    "PermissionRule",
    "PermissionPolicy",
    "ProjectPolicy",
    "EffectivePermissionRequest",
    "project_path_pattern_matches",
    "evaluate_effective_permission",
    "intersect_permission_policies",
    "Responsibility",
    "Capability",
    "GuidanceModule",
    "GuidanceBundle",
    "BackendDefinition",
    "ModelProfile",
    "AgentSpec",
    "AcceptanceCriterion",
    "MachineVerificationSpec",
    "WorkItem",
    "Assignment",
    "RoleInstance",
    "build_role_instance_payload",
    "resolve_role_instance",
    "ContextItem",
    "ContextPack",
    "PipelineStageSpec",
    "PipelineDefinition",
    "PipelinePlan",
    "FrozenStageDigest",
    "ParentStageDigest",
    "PipelineRevision",
    "LeadDecision",
    "QuestionBody",
    "ResponseBody",
    "ContextGapBody",
    "BlockerBody",
    "ConflictBody",
    "PipelineChangeRequestBody",
    "WorkItemProposalBody",
    "CandidateReadyBody",
    "VerificationDefectBody",
    "AssuranceFindingBody",
    "LeadDecisionBody",
    "AcknowledgementBody",
    "CancellationBody",
    "MailboxMessage",
    "CriterionDisposition",
    "CandidateReport",
    "ChangeEntry",
    "ChangeSet",
    "EvidenceArtifact",
    "VerificationCriterion",
    "VerificationPlan",
    "StageSession",
    "VerificationRun",
    "CriterionResult",
    "RunBinding",
    "VerificationReceipt",
    "SemanticFinding",
    "AssuranceDisposition",
    "AssuranceReport",
    "ReviewDecision",
    "LifecycleEvent",
    "ManifestEntry",
    "build_manifest_root_digest",
    "ProjectManifest",
    "ProjectState",
    "CandidateSealPayload",
    "RequiredStageCandidate",
    "build_candidate_seal_payload",
    "CandidateSeal",
    "create_candidate_seal",
    "PolicyRuleSnapshot",
    "PolicyException",
    "pipeline_stage_digest",
    "validate_wire",
    "TOP_LEVEL_MODELS",
]
