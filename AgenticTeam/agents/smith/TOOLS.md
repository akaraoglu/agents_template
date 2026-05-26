# Tools - Smith

## Initial planning runtime

```text
exec: bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh autoplan "<ENVELOPE_JSON>"
exec: bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh prepare "<ENVELOPE_JSON>"
read: <HANDOFF_FILE>
read: <CONTEXT_FILE>
exec: bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh read "<RUN_DIR>" "<RELATIVE_PATH>"
write: <DRAFT_WRITE_ROOT>/<project_relative_planning_path>
write: <MANIFEST_WRITE_FILE>
exec: bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh complete "<RUN_DIR>"
exec: bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh block "<RUN_DIR>" --code "<CODE>" --reason "<EXACT_REASON>"
```

For the initial Neo -> Smith planning handoff, use only the printed `RUN_DIR`,
`DRAFT_WRITE_ROOT`, and `MANIFEST_WRITE_FILE`. Do not reconstruct them from the project id.
If the project includes an explicit `## Required Plan`, prefer `autoplan`; it owns
the deterministic plan artifacts and Niaobe handoff.
Use exact planning draft paths such as:

- `<DRAFT_WRITE_ROOT>/management/PLAN.md`
- `<DRAFT_WRITE_ROOT>/management/BACKLOG.md`
- `<DRAFT_WRITE_ROOT>/management/tasks/T001.md`
- `<DRAFT_WRITE_ROOT>/CURRENT_TASK.md`

Use the printed `DRAFT_WRITE_ROOT` verbatim and only append the allowed suffixes. Do
not invent alternate draft roots, altered timestamps, stray spaces, wildcard
characters, or direct project writes during initial planning.

## Later rooted reads and state updates

```text
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT_STATE.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "CURRENT_TASK.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/PLAN.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/BACKLOG.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/validation/<TASK_ID>_REPORT.md"
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/PLAN.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/PLAN.md" --action smith_plan_write
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/BACKLOG.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/BACKLOG.md" --action smith_backlog_write
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/<TASK_ID>.md" --action smith_task_write
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "CURRENT_TASK.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/CURRENT_TASK.md" --action smith_current_task_write
exec: bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" PLANNING "management/PLAN.md" --action smith-plan-check --contains "T001"
exec: bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" VERIFY "management/validation/<TASK_ID>_REPORT.md" --action smith-validation-check --contains "<TASK_ID>" --contains "PASS"
exec: bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "PLANNING" "niaobe" --actor smith --expect-owner smith --active-task "<TASK_ID>" --task-phase "TASK_HANDOFF" --task-status "READY" --note "<note>"
exec: bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "DONE" "none" --actor smith --expect-owner niaobe --set-owner smith --current-agent none --active-task "none" --task-phase "none" --task-status "DONE" --last-completed-task "<TASK_ID>" --last-task-result "PASS" --note "<note>"
exec: bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "BLOCKED" "none" --actor smith --expect-owner niaobe --set-owner smith --current-agent none --task-status "BLOCKED" --last-task-result "BLOCKED" --increment-blocked --blocked-reason "<exact reason>" --note "<note>"
```

## Notification and delegation

```text
exec: bash /home/alik/workspace/clawspace/bin/handoff.sh smith niaobe "<PROJECT_ID>" "Task <TASK_ID> is ready. Read CURRENT_TASK.md and management/tasks/<TASK_ID>.md, then run Design -> Implement -> Verify for that task only. Report TASK_DONE or TASK_BLOCKED to Smith." TASK_HANDOFF "<TASK_ID>"
```

## sessions_send to Niaobe

Use the exact `ENVELOPE:` value returned by `handoff.sh`.

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "<ENVELOPE from handoff.sh>"
}
```

## sessions_send to Neo

```json
{
  "sessionKey": "agent:neo:main",
  "message": "{\"project_id\":\"<PROJECT_ID>\",\"from\":\"smith\",\"to\":\"neo\",\"phase\":\"DONE|BLOCKED\",\"instructions\":\"<exact outcome>\"}"
}
```

After Niaobe accepts the current task handoff, Smith must not call `write_state.sh`
again for that project until Niaobe returns `TASK_DONE` or `TASK_BLOCKED`.
