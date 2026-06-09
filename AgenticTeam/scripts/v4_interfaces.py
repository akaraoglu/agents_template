import abc
from typing import Any, Protocol, runtime_checkable
from AgenticTeam.scripts.v4_contracts import EventV4

@runtime_checkable
class V4AgentContext(Protocol):
    """
    Protocol for the context provided to agents to allow them 
    to interact with the environment (e.g., emitting events).
    """
    async def emit(self, event: EventV4) -> None:
        """Emit a new event to the system."""
        ...

    async def get_state(self, key: str) -> Any:
        """Retrieve a piece of global state."""
        ...

    async def set_state(self, key: str, value: Any) -> None:
        """Update a piece of global state."""
        ...

class V4Agent(abc.ABC):
    """
    Abstract base class for all V4 agents (Neo, Smith, etc.).
    Every V4 agent must be able to handle incoming events and 
    emit outgoing events through a provided context.
    """

    @abc.abstractmethod
    async def handle_event(self, event: EventV4, context: V4AgentContext) -> None:
        """
        Process an incoming event.
        
        :param event: The incoming event to be processed.
        :param context: The agent context for interacting with the system.
        """
        pass

    @abc.abstractmethod
    def get_agent_name(self) -> str:
        """
        Return the name of the agent.
        """
        pass
