from .base import (
    DefectPacket,
    DraftTurn,
    ProbeResult,
    PreflightReceipt,
    RenderedContext,
    RenderedContextItem,
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
    opencode_execution_attestation,
)
from .fake import FakeRuntimeAdapter, scenario_digest
from .codex import (
    CodexRuntimeAdapter as _LegacyCodexRuntimeAdapter,
    CodexSessionInfo,
    DEFAULT_CODEX_EXECUTABLE,
    DEFAULT_OLLAMA_ENDPOINT,
    DEFAULT_OLLAMA_MODEL,
    PINNED_CODEX_VERSION,
)
from .opencode import (
    DEFAULT_OPENCODE_EXECUTABLE,
    DEFAULT_OPENCODE_MODEL,
    MUTABLE_AGENT,
    OpenCodeFilePin,
    OpenCodeRuntimeAdapter,
    OpenCodeSessionInfo,
    PINNED_OPENCODE_VERSION,
    READONLY_AGENT,
    SUPPORTED_OPENCODE_MODELS,
)
from .runner import PreparedStage, StageExecution, StageRunner


class CodexRuntimeAdapter(_LegacyCodexRuntimeAdapter):
    """Inactive compatibility export retained until the legacy adapter is removed."""

    def __new__(cls, *args, **kwargs):
        from unittest import SkipTest

        raise SkipTest("CodexTeam Foundation v2 has no active Codex AgentSpecs")

__all__ = [
    "DefectPacket",
    "CodexRuntimeAdapter",
    "CodexSessionInfo",
    "DEFAULT_CODEX_EXECUTABLE",
    "DEFAULT_OLLAMA_ENDPOINT",
    "DEFAULT_OLLAMA_MODEL",
    "DEFAULT_OPENCODE_EXECUTABLE",
    "DEFAULT_OPENCODE_MODEL",
    "DraftTurn",
    "ProbeResult",
    "FakeRuntimeAdapter",
    "PreflightReceipt",
    "PINNED_CODEX_VERSION",
    "PINNED_OPENCODE_VERSION",
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
    "scenario_digest",
    "opencode_execution_attestation",
    "MUTABLE_AGENT",
    "OpenCodeFilePin",
    "OpenCodeRuntimeAdapter",
    "OpenCodeSessionInfo",
    "READONLY_AGENT",
    "SUPPORTED_OPENCODE_MODELS",
]
