"""Runtime helpers for artifact movement and sandbox integration."""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "ArtifactParser",
    "ArtifactSerializer",
    "BuiltinRoleExecutor",
    "DispatchReceipt",
    "ExecutionContextBuilder",
    "OpenClawWorkspaceExecutor",
    "OllamaPromptRunner",
    "PromptSubprocessExecutor",
    "ProjectStateLayout",
    "ResponseRecord",
    "RuntimeDispatcher",
    "RuntimeWorker",
    "WorkerExecutionResult",
    "WorkerSpec",
    "WorkerSupervisor",
    "artifact_bucket_for_type",
]

_EXPORTS = {
    "ArtifactParser": ("openclaw_agents.runtime.artifact_parsers", "ArtifactParser"),
    "ArtifactSerializer": ("openclaw_agents.runtime.artifact_serializers", "ArtifactSerializer"),
    "artifact_bucket_for_type": ("openclaw_agents.runtime.artifact_serializers", "artifact_bucket_for_type"),
    "DispatchReceipt": ("openclaw_agents.runtime.dispatcher", "DispatchReceipt"),
    "ResponseRecord": ("openclaw_agents.runtime.dispatcher", "ResponseRecord"),
    "RuntimeDispatcher": ("openclaw_agents.runtime.dispatcher", "RuntimeDispatcher"),
    "ExecutionContextBuilder": ("openclaw_agents.runtime.external_executor", "ExecutionContextBuilder"),
    "PromptSubprocessExecutor": ("openclaw_agents.runtime.external_executor", "PromptSubprocessExecutor"),
    "ProjectStateLayout": ("openclaw_agents.runtime.project_state", "ProjectStateLayout"),
    "OpenClawWorkspaceExecutor": ("openclaw_agents.runtime.openclaw_workspace_executor", "OpenClawWorkspaceExecutor"),
    "OllamaPromptRunner": ("openclaw_agents.runtime.ollama_prompt_runner", "OllamaPromptRunner"),
    "BuiltinRoleExecutor": ("openclaw_agents.runtime.role_executor", "BuiltinRoleExecutor"),
    "RuntimeWorker": ("openclaw_agents.runtime.worker_runner", "RuntimeWorker"),
    "WorkerExecutionResult": ("openclaw_agents.runtime.worker_runner", "WorkerExecutionResult"),
    "WorkerSpec": ("openclaw_agents.runtime.worker_supervisor", "WorkerSpec"),
    "WorkerSupervisor": ("openclaw_agents.runtime.worker_supervisor", "WorkerSupervisor"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
