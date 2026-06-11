import uuid
import datetime
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

TASK_ID_RE = re.compile(r"T\d{3}")

DEFAULT_WRITABLE_PATHS = [
    "src/**",
    "tests/**",
    "README.md",
    "docs/**",
]

DEFAULT_PROTECTED_PATHS = [
    ".openclaw/**",
    "PROJECT.md",
    "PROJECT_STATE.md",
    "CURRENT_TASK.md",
    "BRIEF.md",
    "RESULT.md",
    "DONE_REPORT.md",
    "BLOCKED_REPORT.md",
    "management/PLAN.md",
    "management/BACKLOG.md",
    "management/tasks/**",
]

class Event(BaseModel):
    """Represents an immutable event in the system state."""
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    payload: Dict[str, Any]
    actor: str

class Lease(BaseModel):
    """Represents a resource lease for concurrency control."""
    lease_id: str
    resource_id: str
    owner: str
    expires_at: datetime.datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)

class TaskPack(BaseModel):
    """Represents the context and constraints for a single task execution."""
    project_id: str
    task_id: str
    workspace_root: str
    expected_artifacts: List[str] = Field(default_factory=list)
    writable_paths: List[str] = Field(default_factory=lambda: list(DEFAULT_WRITABLE_PATHS))
    protected_paths: List[str] = Field(default_factory=lambda: list(DEFAULT_PROTECTED_PATHS))
    # Compatibility alias for older callers. Do not use this as the write gate.
    allowed_artifacts: List[str] = Field(default_factory=list)
    deadline: Optional[datetime.datetime] = None
    constraints: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, v: str) -> str:
        if not TASK_ID_RE.match(v):
            raise ValueError("task_id must match T###")
        return v

    def effective_expected_artifacts(self) -> List[str]:
        return self.expected_artifacts or self.allowed_artifacts


class ArtifactPolicy(BaseModel):
    """Separates task deliverables from the project-safe write boundary."""
    expected_artifacts: List[str] = Field(default_factory=list)
    writable_paths: List[str] = Field(default_factory=lambda: list(DEFAULT_WRITABLE_PATHS))
    protected_paths: List[str] = Field(default_factory=lambda: list(DEFAULT_PROTECTED_PATHS))

class WorkResult(BaseModel):
    """Represents the result of a completed task."""
    task_id: str
    attempt_id: str
    status: str  # e.g., STARTED, IN_PROGRESS, DONE, FAILED, BLOCKED
    summary: str = ""
    output: Dict[str, Any] = Field(default_factory=dict)
    evidence: Dict[str, Any] = Field(default_factory=dict)
    repair_reason: Optional[str] = None

class OracleResult(BaseModel):
    """Represents the result of an Oracle verification."""
    project_id: str
    task_id: str
    status: str
    evidence_paths: List[str]
    summary: str
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now)

def validate_work_result(wr: WorkResult) -> bool:
    """Validates that a WorkResult is complete and contains required evidence/output."""
    if wr.status.upper() != "DONE":
        return True
    if not wr.output and not wr.evidence:
        return False
    if not wr.task_id or not wr.attempt_id:
        return False
    return True

def validate_oracle_result(or_res: OracleResult) -> bool:
    """Validates that an OracleResult has the required evidence paths."""
    return len(or_res.evidence_paths) > 0
