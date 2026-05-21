# SKILLS.md - Smith

- **Read canonical project inputs**:
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT_STATE.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "CURRENT_TASK.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/PLAN.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/BACKLOG.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/validation/<TASK_ID>_REPORT.md"`
- **Write planning artifacts**:
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/PLAN.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/PLAN.md" --action smith_plan_write`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/BACKLOG.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/BACKLOG.md" --action smith_backlog_write`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/<TASK_ID>.md" --action smith_task_write`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "CURRENT_TASK.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/CURRENT_TASK.md" --action smith_current_task_write`
- **Verify planning or validation artifacts**:
  - `bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" PLANNING "management/PLAN.md" --action smith-plan-check --contains "T001"`
  - `bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" PLANNING "CURRENT_TASK.md" --action smith-current-task-check --contains "<TASK_ID>"`
  - `bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" VERIFY "management/validation/<TASK_ID>_REPORT.md" --action smith-validation-check --contains "<TASK_ID>" --contains "PASS"`
- **Update canonical state**:
  - `bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "PLANNING" "niaobe" --actor smith --expect-owner smith --active-task "<TASK_ID>" --task-phase "TASK_HANDOFF" --task-status "READY" --note "<note>"`
  - `bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "DONE" "none" --actor smith --expect-owner niaobe --set-owner smith --current-agent none --active-task "none" --task-phase "none" --task-status "DONE" --last-completed-task "<TASK_ID>" --last-task-result "PASS" --note "<note>"`
  - `bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "BLOCKED" "none" --actor smith --expect-owner niaobe --set-owner smith --current-agent none --task-status "BLOCKED" --last-task-result "BLOCKED" --increment-blocked --blocked-reason "<exact reason>" --note "<note>"`
- **Prepare Niaobe delegation**:
  - `bash /home/alik/workspace/clawspace/bin/handoff.sh smith niaobe "<PROJECT_ID>" "Task <TASK_ID> is ready. Read CURRENT_TASK.md and management/tasks/<TASK_ID>.md, then run Design -> Implement -> Verify for that task only. Report TASK_DONE or TASK_BLOCKED to Smith." TASK_HANDOFF "<TASK_ID>"`
- **Delegate to Niaobe**:
  use `sessions_send` with sessionKey `agent:niaobe:main` and the exact
  `ENVELOPE:` value returned by `handoff.sh`
- **Sequence rule**:
  finish planning verification -> state update -> task handoff, then stop mutating
  shared state once Niaobe accepts the task
- **Report to Neo**:
  use `sessions_send` with sessionKey `agent:neo:main` and a JSON envelope keyed
  by `project_id`
