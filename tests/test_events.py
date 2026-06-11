import os
import pytest
import uuid
from AgenticTeam.scripts.events import append_event, read_events, clear_events
from AgenticTeam.scripts.contracts import Event

def test_event_lifecycle():
    clear_events()
    
    event = Event(
        event_id=str(uuid.uuid4()),
        event_type="test_event",
        payload={"key": "value"},
        actor="test_actor"
    )
    
    append_event(event)
    
    events = read_events()
    assert len(events) == 1
    assert events[0].event_type == "test_event"
    assert events[0].payload["key"] == "value"
    assert events[0].actor == "test_actor"

def test_empty_events():
    clear_events()
    events = read_events()
    assert len(events) == 0

def test_multiple_events():
    clear_events()
    
    event1 = Event(
        event_id=str(uuid.uuid4()),
        event_type="event1",
        payload={},
        actor="actor1"
    )
    event2 = Event(
        event_id=str(uuid.uuid4()),
        event_type="event2",
        payload={},
        actor="actor2"
    )
    
    append_event(event1)
    append_event(event2)
    
    events = read_events()
    assert len(events) == 2
    assert events[0].event_type == "event1"
    assert events[1].event_type == "event2"

def test_clear_events():
    clear_events()
    event = Event(
        event_id=str(uuid.uuid4()),
        event_type="test",
        payload={},
        actor="actor"
    )
    append_event(event)
    assert len(read_events()) == 1
    
    clear_events()
    assert len(read_events()) == 0
