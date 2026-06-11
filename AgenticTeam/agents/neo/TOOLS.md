# Tools - Neo

## Start Project

```text
write: path=/home/alik/workspace/clawspace/workspaces/neo/team_PROJECT.md content=<full Master project goal>
exec: bash /home/alik/workspace/clawspace/bin/run_team.sh --background --project-root /home/alik/workspace/clawspace/projects/active --project-id "<project_slug>" --title "<project_title>" --project-file /home/alik/workspace/clawspace/workspaces/neo/team_PROJECT.md
```

Use this for all new project starts.
Do not wait inside your own turn for the whole project to finish; the background team runtime owns Smith, Morpheus, Oracle, and finalization.

For the official Fibonacci E2E fixture only, append:

```text
--fixture fibonacci_tree_visualizer
```

Do not append fixture selectors for normal Master project requests.

## Diagnose Project

```text
read: /home/alik/workspace/clawspace/projects/active/PROJECT_ID/.openclaw/state.json
read: /home/alik/workspace/clawspace/projects/active/PROJECT_ID/.openclaw/events.jsonl
read: /home/alik/workspace/clawspace/projects/active/PROJECT_ID/PROJECT_STATE.md
read: /home/alik/workspace/clawspace/projects/active/PROJECT_ID/CURRENT_TASK.md
read: /home/alik/workspace/clawspace/projects/active/PROJECT_ID/management/PLAN.md
```
