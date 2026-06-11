# SKILLS.md - Neo

- **Start a V4 project**:
  1. Write Master's full project goal to `/home/alik/workspace/clawspace/workspaces/neo/v4_PROJECT.md`.
  2. Run:
     `bash /home/alik/workspace/clawspace/bin/run_v4_team.sh --background --project-root /home/alik/workspace/clawspace/projects/active --project-id "<project_slug>" --title "<project_title>" --project-file /home/alik/workspace/clawspace/workspaces/neo/v4_PROJECT.md`
  3. Report the printed `V4_TEAM_STARTED`, `PROJECT_ID`, `EXPECTED_PROJECT_PATH`, `V4_TEAM_PID`, and `V4_TEAM_LOG` values.
  4. For the official V4 Fibonacci E2E fixture only, append `--fixture fibonacci_tree_visualizer` to the command. Do not use that fixture flag for ordinary user projects.
  5. Do not keep your own turn open waiting for Smith, Morpheus, or Oracle; the background V4 runtime owns the rest of the project loop.

- **Diagnose a V4 project**:
  read the project's `.openclaw/state.json`, `.openclaw/events.jsonl`, `PROJECT_STATE.md`, `CURRENT_TASK.md`, and `management/PLAN.md`, then explain the current owner, phase, active task, and blocker if any.

- **Project slug rule**:
  use a short lowercase hyphenated slug based on the title plus a timestamp when needed.
