import asyncio
import pytest
from AgenticTeam.scripts.core.event_bus import EventBusV4
from AgenticTeam.scripts.core.state_manager import StateManagerV4
from AgenticTeam.agents.v4.neo.agent import NeoV4Agent
from AgenticTeam.scripts.v4_contracts import EventV4

@pytest.mark.asyncio
async def test_neo_v4_agent_handles_initiation():
    event_bus = EventBusV4()
    state_manager = StateManagerV4(event_bus)
    agent = NeoV4Agent("neo-v4", event_bus, state_manager)
    
    # We want to capture the emitted event
    emitted_events = []
    def capture_callback(event: EventV4):
        emitted_events.append(event)
    
    event_bus.subscribe("PROJECT_CREATED_V4", capture_callback)
    
    # Trigger the event
    init_event = EventV4(
        event_type="PROJECT_INITI_V4",
        payload={"project_id": "test_project", "workspace_root": "/tmp/test_project"},
        actor="master"
    )
    
    await agent.handle_event(init_event)
    
    # Verify
    assert len(emitted_events) == 1
    assert emitted_events[0].event_type == "PROJECT_CREATED_V4"
    assert emitted_events[0].payload["project_id"] == "test_project"
    assert emitted_events[0].actor == "neo-v4"

