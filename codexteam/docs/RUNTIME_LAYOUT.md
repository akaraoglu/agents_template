# Runtime Layout

Runtime state belongs under `/home/alik/workspace/codexspace`.

```text
/home/alik/workspace/codexspace/
  teams/<team_id>/
    team.json
    agents/
    tasks/
    runs/
    attempts/
    leader_decisions/
    worker_results/
    requested_actions/
    review_decisions/
    change_proposals/
    checkpoints/
    worker_health/
    resume_decisions/
    stale_policies/
    workspace_archives/
    messages/
      inboxes/
      events/
      dead_letters/
    plans/
    approvals/
    workspaces/
    artifacts/
    logs/
    audit/
    snapshots/
    locks/
  tmp/
```

Committed source, tests, scripts, docs, and templates stay under `codexteam/`.
