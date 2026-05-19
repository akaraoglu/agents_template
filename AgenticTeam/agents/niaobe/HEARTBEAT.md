tasks:
- name: phase-watchdog
  interval: 10m
  prompt: |
    Check the current project you are working on (look for STATE.md with phase
    IN_PROGRESS or a specific phase like DESIGN/BUILD/VERIFY and waiting_for not 'none').
    If a phase has been waiting for more than 15 minutes without a response, re-send
    the delegation to the relevant agent (architect/morpheus/oracle).
    If no active project or all phases are DONE, reply HEARTBEAT_OK.
