tasks:
- name: project-watchdog
  interval: 10m
  prompt: |
    Check /home/alik/workspace/clawspace/projects/active/ for projects.
    For each project folder, read STATE.md if it exists.
    If phase is IN_PROGRESS and waiting_for is not 'none' and the last log entry
    is older than 15 minutes, re-send delegation to the waiting agent.
    Post one status line to #projects for each active project.
    If all projects are DONE or no active projects exist, reply HEARTBEAT_OK.
    If no STATE.md exists in a folder, skip it and reply HEARTBEAT_OK.
