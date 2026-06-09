import os
import pytest
import uuid
from AgenticTeam.scripts.v4_events import append_event_v4, read_events_v4, clear_events_v4
from AgenticTeam.scripts.v4_contracts import EventV4

def test_event_lifecycle():
    clear_events_v4()
    
    event = EventV4(
        event_id=str(uuid.uuid4()),
        event_type="test_event",
        payload={"key": "value"},
        actor="test_actor"
    )
    
    append_event_v4(event)
    
    events = read_events_v4()
    assert len(events) == 1
    assert events[0].event_type == "test_event"
    assert events[0].payload["key"] == "value"
    assert events[0].actor == "test_actor"

def test_empty_events():
    clear_events_v4()
    events = read_events_v4()
    assert len(events) == 0

def test_multiple_events():
    clear_events_v4()
    
    event1 = EventV4(
        event_id=str(uuid.uuid4()),
        event_type="event1",
        payload={},
        actor="actor1"
    )
    event2 = EventV4(
        event_id=str(uuid.uuid4()),
        event_type="event2",
        payload={},
        actor="actor2"
    )
    
    append_event_v4(event1)
    append_event_v4(event2)
    
    events = read_events_v4()
    assert len(events) == 2
    assert events[0].event_type == "event1"
    assert events[1].event_type == "event2"

def test_clear_events():
    clear_events_v4()
    event = EventV4(
        event_id=str(uuid.uuid4()),
        event_type="test",
        payload={},
        actor="actor"
    )
    append_event_v4(event)
    assert len(read_events_v4()) == 1
    
    clear_events_v4()
    assert len(read_events_v4()) == 0
