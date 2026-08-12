from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, Self, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from ..models import (
    AssuranceDomain,
    ContextPack,
    EvidenceType,
    PermissionOperation,
    PermissionResource,
    RoleInstance,
    RecordRef,
    SemanticFinding,
)
from ..canonical import canonical_sha256


class RuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProbeResult(RuntimeModel):
    operation: PermissionOperation
    resource: PermissionResource
    status: Literal["passed", "failed"]
    evidence_summary: str = Field(min_length=1)


class PreflightReceipt(RuntimeModel):
    role_instance_digest: str
    context_pack_digest: str
    catalog_digest: str
    workspace: str
    backend_id: str
    observed_capabilities: tuple[str, ...]
    probes: tuple[ProbeResult, ...]
    enforcement_limitations: tuple[str, ...] = ()


class RenderedContextItem(RuntimeModel):
    category: Literal["requirement", "design", "source", "evidence", "decision", "limitation"]
    summary: str = Field(min_length=1)
    locator: str | None = None
    content: str
    content_digest: str
    intended_use: str = Field(min_length=1)


class RenderedContext(RuntimeModel):
    context_pack_digest: str
    items: tuple[RenderedContextItem, ...]
    rendered_digest: str


class SemanticResponse(RuntimeModel):
    summary: str = Field(min_length=1)
    notes: tuple[str, ...] = ()


class DraftTurn(RuntimeModel):
    session_id: str = Field(min_length=1)
    response: SemanticResponse
    consumed_context_digest: str


class SemanticEvidence(RuntimeModel):
    evidence_type: EvidenceType
    content: str


class SemanticCandidate(RuntimeModel):
    stage: Literal["architecture", "ux", "implementation", "verification"]
    outcome: Literal["succeeded", "correction_needed", "blocked"]
    evidence: tuple[SemanticEvidence, ...] = ()
    findings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class SemanticDiscovery(RuntimeModel):
    stage: Literal["discovery"]
    outcome: Literal["succeeded", "correction_needed", "blocked"]
    requested_optional_stages: tuple[Literal["architecture", "ux"], ...] = ()
    rationale: str = Field(min_length=1)
    evidence: tuple[SemanticEvidence, ...] = ()
    findings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class SemanticAssuranceDisposition(RuntimeModel):
    domain: AssuranceDomain
    disposition: Literal["pass", "fail", "not_applicable"]
    findings: tuple[SemanticFinding, ...] = ()

    @model_validator(mode="after")
    def passing_disposition_has_no_blocking_findings(self) -> Self:
        if self.disposition == "pass" and any(item.unresolved_blocking for item in self.findings):
            raise ValueError("a passing assurance disposition cannot contain unresolved blocking findings")
        return self


class SemanticAssurance(RuntimeModel):
    stage: Literal["assurance"]
    outcome: Literal["succeeded", "correction_needed", "blocked"]
    dispositions: tuple[SemanticAssuranceDisposition, ...]
    evidence: tuple[SemanticEvidence, ...] = ()
    findings: tuple[SemanticFinding, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def successful_assurance_has_no_blocking_findings(self) -> Self:
        if self.outcome == "succeeded" and any(item.unresolved_blocking for item in self.findings):
            raise ValueError("successful assurance cannot contain unresolved blocking findings")
        return self


class SemanticReview(RuntimeModel):
    stage: Literal["review"]
    outcome: Literal["succeeded", "correction_needed", "blocked"]
    decision: Literal["ACCEPT", "RETURN", "BLOCK"]
    rationale: str = Field(min_length=1)
    evidence: tuple[SemanticEvidence, ...] = ()
    findings: tuple[SemanticFinding, ...] = ()
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def acceptance_has_no_blocking_findings(self) -> Self:
        if self.decision == "ACCEPT" and any(item.unresolved_blocking for item in self.findings):
            raise ValueError("ACCEPT cannot contain unresolved blocking findings")
        return self


StageSemantic = Annotated[
    SemanticDiscovery | SemanticCandidate | SemanticAssurance | SemanticReview,
    Field(discriminator="stage"),
]
STAGE_SEMANTIC_ADAPTER = TypeAdapter(StageSemantic)


class DefectPacket(RuntimeModel):
    summary: str = Field(min_length=1)
    criterion_ids: tuple[str, ...]
    evidence: tuple[str, ...] = ()


@runtime_checkable
class RuntimeAdapter(Protocol):
    def preflight(
        self, role_instance: RoleInstance, context_pack: ContextPack, workspace: Path
    ) -> PreflightReceipt: ...

    def draft(
        self, role_instance: RoleInstance, context: RenderedContext, workspace: Path
    ) -> DraftTurn: ...

    def resume(
        self,
        session_id: str,
        role_instance: RoleInstance,
        context: RenderedContext,
        workspace: Path,
        *,
        candidate_sequence: int,
    ) -> DraftTurn: ...

    def feedback(self, session_id: str, defect_packet: DefectPacket) -> SemanticResponse: ...

    def candidate(self, session_id: str, *, read_only: bool) -> StageSemantic: ...


class RuntimeErrorBase(RuntimeError):
    pass


class RuntimePreflightError(RuntimeErrorBase):
    pass


class RuntimeOutputError(RuntimeErrorBase):
    pass


class RuntimeSessionError(RuntimeErrorBase):
    pass


class RuntimeBackendError(RuntimeErrorBase):
    pass


def opencode_execution_attestation() -> RecordRef:
    """Pin the practical OpenCode boundary used by StageRunner.

    This is an execution-design attestation, not an OS sandbox claim. The model
    works only in the product directory and StageRunner audits every change.
    """
    statement = {
        "backend": "opencode",
        "boundary": "product-directory-with-post-turn-audit",
        "os_sandbox": False,
        "version": 1,
    }
    return RecordRef(
        record_id="opencode-product-audit-v1",
        kind="attestation",
        digest=canonical_sha256(statement),
    )


def validate_runtime_value(model: type[BaseModel], value: Any) -> Any:
    if isinstance(value, model):
        return value
    try:
        return model.model_validate(value, strict=True)
    except ValueError as exc:
        raise RuntimeOutputError(f"malformed runtime {model.__name__}: {exc}") from exc


def validate_stage_semantic(value: Any) -> StageSemantic:
    try:
        return STAGE_SEMANTIC_ADAPTER.validate_python(value, strict=True)
    except ValueError as exc:
        raise RuntimeOutputError(f"malformed runtime stage semantic: {exc}") from exc


__all__ = [
    "DefectPacket",
    "DraftTurn",
    "ProbeResult",
    "PreflightReceipt",
    "RenderedContext",
    "RenderedContextItem",
    "RuntimeAdapter",
    "RuntimeModel",
    "RuntimeBackendError",
    "RuntimeErrorBase",
    "RuntimeOutputError",
    "RuntimePreflightError",
    "RuntimeSessionError",
    "opencode_execution_attestation",
    "SemanticCandidate",
    "SemanticDiscovery",
    "SemanticAssurance",
    "SemanticAssuranceDisposition",
    "SemanticReview",
    "SemanticEvidence",
    "SemanticFinding",
    "SemanticResponse",
    "StageSemantic",
    "validate_stage_semantic",
]
