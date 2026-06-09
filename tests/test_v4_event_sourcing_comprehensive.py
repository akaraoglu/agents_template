import os
import pytest
from AgenticTeam.scripts.v4_events import append_event_v4, read_events_v4, clear_events_v4
from AgenticTeam.scripts.v4_contracts import EventV4

@pytest.fixture
def clean_events():
    """Fixture to clear events before and after each test."""
    clear_events_v4()
    yield
    clear_events_v4()

def test_append_and_read_v4(clean_events):
    """Test appending and reading events."""
    event = EventV4(
        event_type="test_event",
        payload={"key": "value"},
        actor="test_actor"
    )
    append_event_v4(event)
    
    events = read_events_v4(event_type="test_event")
    assert len(events) == 1
    assert events[0].event_id == event.event_id
    assert events[0].event_type == "test_event"

def test_read_events_filtering(clean_events):
    """Test filtering events by type."""
    event1 = EventV4(event_type="type1", payload={}, actor="actor1")
    event2 = EventV4(event_type="type2", payload={}, actor="supposed_to_be_different")
    append_event_v4(event1)
    append_event_v4(event2)
    
    events_type1 = read_events_v4(event_type="type1")
    assert len(events_type1) == 1
    assert events_type1[0].event_type == "type1"
    
    events_none = read_events_v4(event_type="non_existent")
    assert len(events_none) == 0

def test_clear_events(clean_events):
    """Test clearing events."""
    event = EventV4(event_type="test", payload={}, actor="actor")
    append_event_v4(event)
    assert len(read_events_v4()) == 1
    
    clear_events_v4()
    assert len(read_events_v4()) == 0
