import json
import os
import datetime
from pathlib import Path
from typing import List, Optional
from AgenticTeam.scripts.contracts import Event

DEFAULT_EVENT_FILE = ".openclaw/events.jsonl"

def get_event_file_path() -> Path:
    return Path(os.environ.get("TEAM_EVENT_FILE", DEFAULT_EVENT_FILE))

def clear_events():
    """Clear all events in the event file (truncates the file or deletes it)."""
    path = get_event_file_path()
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

def append_event(event: Event) -> bool:
    """Appends an event to the jsonl file. Returns False if duplicate detected."""
    path = get_event_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Check for duplicate event_id
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if data.get("event_id") == event.event_id:
                        return False
                except json.JSONDecodeError:
                    continue

    with open(path, "a", encoding="utf-8") as f:
        f.write(event.model_dump_json() + "\n")
    return True

def read_events(event_type: Optional[str] = None) -> List[Event]:
    """Reads all events from the event file, optionally filtered by event_type."""
    path = get_event_file_path()
    if not path.exists():
        return []

    events = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                ev = Event.model_validate(data)
                if event_type is None or ev.event_type == event_type:
                    events.append(ev)
            except Exception:
                continue
    return events

class EventStore:
    def __init__(self, event_file: str):
        self.event_file = Path(event_file)
        self.event_file.parent.mkdir(parents=True, exist_ok=True)

    def append_event(self, event: Event) -> bool:
        """Appends an event to the jsonl file. Returns False if duplicate detected."""
        event_data = event.model_dump_json()
        
        # Check for duplicate event_id
        if self.event_exists(event.event_id):
            return False

        with open(self.event_file, "a", encoding="utf-8") as f:
            f.write(event_data + "\n")
        return True

    def event_exists(self, event_id: str) -> bool:
        """Checks if an event with the given ID already exists."""
        if not self.event_file.exists():
            return False
        
        with open(self.event_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if data.get("event_id") == event_id:
                        return True
                except json.JSONDecodeError:
                    continue
        return False

    def get_all_events(self) -> List[Event]:
        events = []
        if not self.event_file.exists():
            return events
        with open(self.event_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    events.append(Event.model_validate(json.loads(line)))
                except Exception:
                    continue
        return events
