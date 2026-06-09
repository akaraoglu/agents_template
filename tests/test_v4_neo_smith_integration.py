import asyncio
import pytest
from AgenticTeam.scripts.core.event_bus import EventBusV4
from AgenticTeam.scripts.core.state_manager import StateManagerV4
from AgenticTeam.agents.v4.neo.agent import NeoV4Agent
from AgenticTeam.agents.v4.smith.agent import SmithV4Agent
from AgenticTeam.scripts.v4_contracts import EventV4

@pytest.mark.asyncio
async def test_neo_to_smith_v4_flow():
    event_bus = EventBusV4()
    state_manager = StateManagerV4(event_bus)
    
    neo_agent = NeoV4Agent("neo-v4", event_bus, state_manager)
    smith_agent = SmithV4Agent("smith-v4", event_bus, state_manager)
    
    emitted_events = []
    done_event = asyncio.Event()
    
    def capture_callback(event: EventV4):
        emitted_events.append(event)
        done_event.set()
    
    event_bus.subscribe("SMITH_PLANNING_STARTED_V4", capture_callback)
    
    # Trigger Neo's action
    init_event = EventV4(
        event_type="PROJECT_INITI_V4",
        payload={"project_id": "test_project_integration", "workspace_root": "/tmp/test_project_integration"},
        actor="master"
    )
    
    await neo_agent.handle_event(init_event)
    
    # Wait for the event to be captured or timeout
    try:
        await asyncio.wait_for(done_event.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pytest.fail("Timed out waiting for SMITH_PLANNING_STARTED_V4 event")
    
    # Verify Smith received the event and started planning
    assert len(emitted_events) == 1
    assert emitted_events[0].event_type == "SMITH_PLANNING_STARTED_V4"
    assert emitted_events[0].payload["project_id"] == "test_project_integration"
    assert emitted_events[0].actor == "smith-v4"
