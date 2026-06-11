tasks:
- name: project-watchdog
  interval: 10m
  prompt: |
    Check team projects only when Master asks for status. The typed team conductor owns normal progress.
    Read .openclaw/state.json and .openclaw/events.jsonl for the requested project.
    Report owner, phase, active_task, waiting_for, and any blocker.
    Do not resend work through sessions.
