from . import models as _models
from .catalog import Catalog, CatalogFile, ResolvedAgentSpec, catalog_lock, load_catalog, resolve_agent_spec
from .canonical import canonical_json, canonical_json_bytes, canonical_sha256, sha256_digest, verify_digest
from .compiler import CompileReferences, CompiledPipeline, build_role_instance as _build_role_instance, compile_pipeline
from .evidence import (
    EvidenceManager,
    StageCandidate,
    compose_change_sets,
    derive_change_set,
    evidence_is_fresh,
    validate_change_attribution,
    workspace_manifest,
)
from .mailbox import Mailbox, MailboxEnvelope, MailboxProcessingState, MailboxReceipt
from .models import *
from .pipeline_runtime import (
    PipelineRunProjection,
    PipelineRuntime,
    StageProjection,
    resolve_revision_ancestry,
    stage_revision_is_valid,
)
from .sealing import ClosureProjection, close_candidate, create_seal, replay_closure, seal_candidate
from .storage import CorruptStore, RevisionConflict, StorageConflict, StoredEvent, V2ProjectStore
from .verification import VerificationExecutor, receipt_is_fresh, validate_assurance_report, validate_review_decision
from .views import render_assurance, render_candidate, render_pipeline, render_status, write_view
from .canary import CanaryResult, run_fake_canary, run_live_opencode_canary
from .qualification import MuseQualificationResult, QualificationCheck, run_muse_qualification
from .runtime import (
    DefectPacket,
    CodexRuntimeAdapter,
    CodexSessionInfo,
    OpenCodeRuntimeAdapter,
    OpenCodeSessionInfo,
    DraftTurn,
    ProbeResult,
    FakeRuntimeAdapter,
    PreflightReceipt,
    RenderedContext,
    RenderedContextItem,
    PreparedStage,
    RuntimeAdapter,
    RuntimeBackendError,
    RuntimeErrorBase,
    RuntimeOutputError,
    RuntimePreflightError,
    RuntimeSessionError,
    SemanticCandidate,
    SemanticAssurance,
    SemanticAssuranceDisposition,
    SemanticDiscovery,
    SemanticEvidence,
    SemanticFinding,
    SemanticReview,
    SemanticResponse,
    StageSemantic,
    StageExecution,
    StageRunner,
    opencode_execution_attestation,
)


def build_role_instance(*args, **kwargs):
    """Build a public v2 role with the pinned practical OpenCode boundary."""
    if kwargs.get("host_isolation_authorization") is None:
        catalog = args[0] if args else kwargs.get("catalog")
        assignment = kwargs.get("assignment")
        if catalog is not None and assignment is not None:
            resolved = catalog.resolve_agent_spec(
                assignment.agent_spec.definition_id,
                assignment.agent_spec.definition_version,
            )
            if resolved.backend.provider == "opencode":
                kwargs["host_isolation_authorization"] = opencode_execution_attestation()
    return _build_role_instance(*args, **kwargs)

__all__ = [
    "canonical_json",
    "canonical_json_bytes",
    "canonical_sha256",
    "sha256_digest",
    "verify_digest",
    "Catalog",
    "CatalogFile",
    "ResolvedAgentSpec",
    "catalog_lock",
    "load_catalog",
    "resolve_agent_spec",
    "CompileReferences",
    "CompiledPipeline",
    "build_role_instance",
    "compile_pipeline",
    "V2ProjectStore",
    "StoredEvent",
    "StorageConflict",
    "RevisionConflict",
    "CorruptStore",
    "Mailbox",
    "MailboxEnvelope",
    "MailboxReceipt",
    "MailboxProcessingState",
    "PipelineRuntime",
    "PipelineRunProjection",
    "StageProjection",
    "resolve_revision_ancestry",
    "stage_revision_is_valid",
    "EvidenceManager",
    "StageCandidate",
    "workspace_manifest",
    "derive_change_set",
    "compose_change_sets",
    "validate_change_attribution",
    "evidence_is_fresh",
    "VerificationExecutor",
    "receipt_is_fresh",
    "validate_assurance_report",
    "validate_review_decision",
    "seal_candidate",
    "create_seal",
    "ClosureProjection",
    "close_candidate",
    "replay_closure",
    "render_pipeline",
    "render_status",
    "render_assurance",
    "render_candidate",
    "write_view",
    "CanaryResult",
    "run_fake_canary",
    "run_live_opencode_canary",
    "MuseQualificationResult",
    "QualificationCheck",
    "run_muse_qualification",
    "DefectPacket",
    "CodexRuntimeAdapter",
    "CodexSessionInfo",
    "OpenCodeRuntimeAdapter",
    "OpenCodeSessionInfo",
    "DraftTurn",
    "ProbeResult",
    "FakeRuntimeAdapter",
    "PreflightReceipt",
    "RenderedContext",
    "RenderedContextItem",
    "PreparedStage",
    "RuntimeAdapter",
    "RuntimeBackendError",
    "RuntimeErrorBase",
    "RuntimeOutputError",
    "RuntimePreflightError",
    "RuntimeSessionError",
    "SemanticCandidate",
    "SemanticAssurance",
    "SemanticAssuranceDisposition",
    "SemanticDiscovery",
    "SemanticEvidence",
    "SemanticFinding",
    "SemanticReview",
    "SemanticResponse",
    "StageSemantic",
    "StageExecution",
    "StageRunner",
    "opencode_execution_attestation",
] + _models.__all__
