from AgenticTeam.scripts.agents.base_agent import BaseAgentV4
from AgenticTeam.scripts.core.event_bus import EventBusV4
from AgenticTeam.scripts.core.state_manager import StateManagerV4
from AgenticTeam.scripts.v4_contracts import EventV4
from AgenticTeam.scripts.v4_interfaces import V4AgentContext

class SmithV4Agent(BaseAgentV4):
    """
    The Smith agent that manages the project and dispatches tasks.
    """
    def __init__(self, agent_id: str, event_bus: EventBusV4, state_manager: StateManagerV4):
        super().__init__(agent_id, event_bus, state_manager)

    def _setup_listeners(self) -> None:
        self.event_bus.subscribe("PROJECT_CREATED_V4", self.handle_event)

    async def handle_event(self, event: EventV4) -> None:
        if event.event_type == "PROJECT_CREATED_V4":
            # When Neo creates a project, Smith starts planning
            self.emit_event("SMITH_PLANNING_STARTED_V4", {
                "project_id": event.payload.get("project_id"),
                "workspace_root": event.payload.get("workspace_root")
            })
        elif event.event_type == "TASK_ASSIGNED":
            # Handle task assignment
            pass
        elif event.event_type == "WORK_RESULT_SUBMITTED":
            # Handle work result submission
            pass
