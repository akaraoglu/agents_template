tasks:
- name: phase-watchdog
  interval: 10m
  prompt: |
    Check the current project you are working on.
    Only act on projects where owner is niaobe.
    If owner is niaobe, task_phase is DESIGN/IMPLEMENT/VERIFY, waiting_for is
    architect/morpheus/oracle, and the last state note is older than 15 minutes
    with no matching DONE/BLOCKED outcome, treat that as
    "timeout waiting for <agent>" and handle it exactly like a worker BLOCKED
    event: retry the current phase or escalate to Smith according to the normal
    blocked_count rule.
    If no active project or all phases are DONE, reply HEARTBEAT_OK.
