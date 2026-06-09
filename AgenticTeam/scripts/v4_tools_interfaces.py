import abc
from typing import Any, Protocol, runtime_checkable
from AgenticTeam.scripts.v4_contracts import TaskPackV4, WorkResultV4, OracleResultV4

@runtime_checkable
class V4Tool(Protocol):
    """
    Protocol for a V4 tool. 
    A tool is a capability that can be invoked by an agent.
    """
    async def execute(self, task_pack: TaskPackV4, **kwargs: Any) -> Any:
        """
        Execute the tool's logic.
        
        :param task_pack: The context and constraints for the task execution.
        :param kwargs: The arguments for the tool execution.
        :return: The result of the tool execution (could be WorkResultV4, OracleResultV4, or other).
        """
        ...

class V4FileSystemTool(Protocol):
    """
    Protocol for V4 filesystem tools (e.g., write, patch, read).
    """
    async def read(self, path: str) -> str:
        """Read the contents of a file."""
        ...

    async def write(self, path: str, content: str) -> None:
        """Write content to a file."""
        ...

    async def patch(self, path: str, patch_content: str) -> None:
        """Apply a patch to a file."""
        ...

class V4TestingTool(Protocol):
    """
    Protocol for V4 testing tools.
    """
    async def run_test(self, test_command: str) -> Any:
        """Run a test command and return the results/evidence."""
        ...

class V4WorkSubmissionTool(Protocol):
    """
    Protocol for V4 work submission tools.
    """
    async def submit_work(self, task_id: str, result: WorkResultV4) -> None:
        """Submit the results of a completed task."""
        ...

class V4VerificationTool(Protocol):
    """
    Protocol for V4 verification tools (e.g., Oracle verification).
    """
    async def verify_project(self, project_id: str) -> OracleResultV4:
        """Verify the state of a project."""
        ...
