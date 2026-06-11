import unittest
import json
import os
import uuid
from typing import Any, Dict, List

# --- The implementation to be tested ---

class Event:
    def __init__(self, event_id: str, event_type: str, payload: Dict[str, Any], timestamp: float):
        self.event_id = event_id
        self.event_type = event_type
        self.payload = payload
        self.timestamp = timestamp

    def to_dict(self):
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp
        }

class AgenticEventSourcing:
    def __init__(self, log_file: str):
        self.log_file = log_file
        self.events: List[Event] = []
        self._load_events()

    def _load_events(self):
        if os.path.exists(self.log_file):
            with open(self.log_file, 'r') as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    event = Event(
                        event_id=data['event_id'],
                        event_type=data['event_type'],
                        payload=data['payload'],
                        timestamp=data['timestamp']
                    )
                    self.events.append(event)

    def append_event(self, event: Event):
        self.events.append(event)
        with open(self.log_file, 'a') as f:
            f.write(json.dumps(event.to_dict()) + '\n')

# Since I need json, I'll import it inside the class or globally. 
# Let's just fix the structure.
