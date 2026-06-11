import os
import pytest
from AgenticTeam.scripts.events import append_event, read_events, clear_events
from AgenticTeam.scripts.contracts import Event

@pytest.fixture
def clean_events():
    """Fixture to clear events before and after each test."""
    clear_events()
    yield
    clear_events()

def test_append_and_read_events(clean_events):
    """Test appending and reading events."""
    event = Event(
        event_type="test_event",
        payload={"key": "value"},
        actor="test_actor"
    )
    append_event(event)
    
    events = read_events(event_type="test_event")
    assert len(events) == 1
    assert events[0].event_id == event.event_id
    assert events[0].event_type == "test_event"

def test_read_events_filtering(clean_events):
    """Test filtering events by type."""
    event1 = Event(event_type="type1", payload={}, actor="actor1")
    event2 = Event(event_type="type2", payload={}, actor="supposed_to_be_different")
    append_event(event1)
    append_event(event2)
    
    events_type1 = read_events(event_type="type1")
    assert len(events_type1) == 1
    assert events_type1[0].event_type == "type1"
    
    events_none = read_events(event_type="non_existent")
    assert len(events_none) == 0

def test_clear_events(clean_events):
    """Test clearing events."""
    event = Event(event_type="test", payload={}, actor="actor")
    append_event(event)
    assert len(read_events()) == 1
    
    clear_events()
    assert len(read_events()) == 0
