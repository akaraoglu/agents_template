# Tools - Smith

## Initial planning runtime

```text
exec: bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh autoplan "<ENVELOPE_JSON>"
exec: bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh read "<RUN_DIR>" "<RELATIVE_PATH>"
write: path=<DRAFT_WRITE_ROOT>/<project_relative_planning_path> content=<planning markdown>
write: path=<MANIFEST_WRITE_FILE> content=<manifest json>
exec: bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh complete "<RUN_DIR>"
exec: bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh block "<RUN_DIR>" --code "<CODE>" --reason "<EXACT_REASON>"
```

For the initial Neo -> Smith planning handoff, call `autoplan` first. If it
prints `RESULT_FILE=...`, stop; it already owns the deterministic plan artifacts
and Niaobe handoff. If it reports no deterministic `## Required Plan`, continue
from its printed `RUN_DIR`, `DRAFT_WRITE_ROOT`, and `MANIFEST_WRITE_FILE`. Do
not run `prepare` again and do not reconstruct paths from the project id.
Use exact planning draft paths such as:

- `<DRAFT_WRITE_ROOT>/management/PLAN.md`
- `<DRAFT_WRITE_ROOT>/management/BACKLOG.md`
- `<DRAFT_WRITE_ROOT>/management/tasks/T001.md`
- `<DRAFT_WRITE_ROOT>/CURRENT_TASK.md`
- `<DRAFT_WRITE_ROOT>/BRIEF.md`

Use the printed `DRAFT_WRITE_ROOT` verbatim and only append the allowed suffixes.
Do not invent alternate draft roots, altered timestamps, stray spaces, wildcard
characters, or direct project writes during initial planning.

## Later rooted reads and state updates

```text
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT_STATE.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "CURRENT_TASK.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "BRIEF.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/PLAN.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/BACKLOG.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/validation/<TASK_ID>_REPORT.md"
exec: bash /home/alik/workspace/clawspace/bin/smith_task_progress.sh sync "<PROJECT_ID>"
exec: bash /home/alik/workspace/clawspace/bin/smith_task_progress.sh complete "<PROJECT_ID>" "<TASK_ID>"
exec: bash /home/alik/workspace/clawspace/bin/smith_task_progress.sh blocked "<PROJECT_ID>" "<TASK_ID>" --reason "<exact reason>"
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/PLAN.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/PLAN.md" --action smith_plan_write
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/BACKLOG.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/BACKLOG.md" --action smith_backlog_write
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/<TASK_ID>.md" --action smith_task_write
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "CURRENT_TASK.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/CURRENT_TASK.md" --action smith_current_task_write
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "BRIEF.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/BRIEF.md" --action smith_brief_write
exec: bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" PLANNING "management/PLAN.md" --action smith-plan-check --contains "T001"
exec: bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" VERIFY "management/validation/<TASK_ID>_REPORT.md" --action smith-validation-check --contains "<TASK_ID>" --contains "PASS"
```

## Notification and delegation

```text
exec: bash /home/alik/workspace/clawspace/bin/smith_task_progress.sh complete "<PROJECT_ID>" "<TASK_ID>"
exec: bash /home/alik/workspace/clawspace/bin/smith_task_progress.sh blocked "<PROJECT_ID>" "<TASK_ID>" --reason "<exact reason>"
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

## Python diagnostics

```text
exec: bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<runtime-or-workspace-directory>" --module unittest -- tests/test_main.py
exec: bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<runtime-or-workspace-directory>" --syntax-check "src/main.py"
```

`python_claw.sh` uses `/home/alik/workspace/clawspace/venv-claw` without shell
activation. Use it only for local Python diagnosis; Smith's planning/task
helpers remain the authority for state movement and final evidence.
