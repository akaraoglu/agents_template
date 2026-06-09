import asyncio
from AgenticTeam.scripts.v4_contracts import EventV4
from AgenticTeam.scripts.core.event_bus import EventBusV4
from AgenticTeam.scripts.core.state_manager import StateManagerV4
from AgenticTeam.scripts.agents.base_agent import BaseAgentV4

class NeoV4Agent(BaseAgentV4):
    """V4 version of Neo agent."""
    
    def _setup_listeners(self) -> None:
        self.event_bus.subscribe("PROJECT_INITI_V4", self.handle_event)

    async def handle_event(self, event: EventV4) -> None:
        if event.event_type == "PROJECT_INITI_V4":
            print(f"[{self.agent_id}] Received project initiation request: {event.payload.get('project_id')}")
            
            # Simulate some work
            await asyncio.sleep(0.1)
            
            # Emit project created event
            self.emit_event("PROJECT_CREATED_V4", {
                "project_id": event.payload.get("project_id"),
                "workspace_root": event.payload.get("workspace_root")
            })
            print(f"[{self.agent_id}] Project created and handed off to Smith.")

async def run_neo_v4(event_bus: EventBusV4, state_manager: StateManagerV4):
    agent = NeoV4Agent("neo-v4", event_bus, state_manager)
    # Keep the agent running
    while True:
        await asyncio.sleep(1)

if __name__ == "__callee__":
    # This is just a placeholder for standalone testing if needed
    pass
