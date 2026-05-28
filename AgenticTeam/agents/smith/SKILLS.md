# SKILLS.md - Smith

- **Initial planning runtime**:
  - `bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh autoplan "<ENVELOPE_JSON>"`
  - if `autoplan` prints `RESULT_FILE=...`, stop; the runtime already planned and handed off T001
  - if `autoplan` reports no deterministic `## Required Plan`, continue from its printed `RUN_DIR`, `DRAFT_WRITE_ROOT`, and `MANIFEST_WRITE_FILE`
  - `bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh read "<RUN_DIR>" "<RELATIVE_PATH>"`
  - write full planning drafts under `<DRAFT_WRITE_ROOT>/<project_relative_path>` using tool args `path` and `content`
  - write the planning manifest to `<MANIFEST_WRITE_FILE>` using tool args `path` and `content`
  - `bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh complete "<RUN_DIR>"`
  - `bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh block "<RUN_DIR>" --code "<CODE>" --reason "<EXACT_REASON>"`
- **Initial planning rule**:
  for the first Neo -> Smith planning handoff, do not call `project_write.sh`,
  `write_state.sh`, `handoff.sh`, or `sessions_send` directly; the runtime owns
  those completion steps
  and `CURRENT_TASK.md` must be written to the exact path
  `<DRAFT_WRITE_ROOT>/CURRENT_TASK.md`
- **Later canonical reads**:
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT_STATE.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "CURRENT_TASK.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/PLAN.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/BACKLOG.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/validation/<TASK_ID>_REPORT.md"`
- **Later task activation / completion**:
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/PLAN.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/PLAN.md" --action smith_plan_write`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/BACKLOG.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/BACKLOG.md" --action smith_backlog_write`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/<TASK_ID>.md" --action smith_task_write`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "CURRENT_TASK.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/CURRENT_TASK.md" --action smith_current_task_write`
  - `bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" VERIFY "management/validation/<TASK_ID>_REPORT.md" --action smith-validation-check --contains "<TASK_ID>" --contains "PASS"`
  - `bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "DONE" "none" --actor smith --expect-owner niaobe --set-owner smith --current-agent none --active-task "none" --task-phase "none" --task-status "DONE" --last-completed-task "<TASK_ID>" --last-task-result "PASS" --note "<note>"`
  - `bash /home/alik/workspace/clawspace/bin/write_state.sh "<PROJECT_ID>" "BLOCKED" "none" --actor smith --expect-owner niaobe --set-owner smith --current-agent none --task-status "BLOCKED" --last-task-result "BLOCKED" --increment-blocked --blocked-reason "<exact reason>" --note "<note>"`
  - `bash /home/alik/workspace/clawspace/bin/handoff.sh smith niaobe "<PROJECT_ID>" "Task <TASK_ID> is ready. Read CURRENT_TASK.md and management/tasks/<TASK_ID>.md, then run Design -> Implement -> Verify for that task only. Report TASK_DONE or TASK_BLOCKED to Smith." TASK_HANDOFF "<TASK_ID>"`
- **Report to Neo**:
  use `sessions_send` with sessionKey `agent:neo:main` and a JSON envelope keyed
  by `project_id`
