tasks:
- name: project-watchdog
  interval: 10m
  prompt: |
    Check /home/alik/workspace/clawspace/projects/active/ for projects.
    For each project folder, read PROJECT_STATE.md if it exists, otherwise STATE.md.
    Only act on projects where owner is smith.
    If owner is smith, waiting_for is niaobe, active_task is not none, task_phase
    is TASK_HANDOFF, and the last state note is older than 15 minutes, re-send the
    Smith -> Niaobe task handoff once using the same task_id.
    If owner is niaobe, do not resend anything — Niaobe owns recovery after ack.
    Post one status line to #projects for each active project.
    If all projects are DONE or no active projects exist, reply HEARTBEAT_OK.
    If no project state file exists in a folder, skip it and reply HEARTBEAT_OK.
