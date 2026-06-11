tasks:
- name: v4-project-watchdog
  interval: 10m
  prompt: |
    Check V4 projects only when Master asks for status. The typed V4 conductor owns normal progress.
    Read .openclaw/state.json and .openclaw/events.jsonl for the requested project.
    Report owner, phase, active_task, waiting_for, and any blocker.
    Do not resend work through sessions.
