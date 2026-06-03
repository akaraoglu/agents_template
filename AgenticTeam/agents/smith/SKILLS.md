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
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "BRIEF.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/PLAN.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/BACKLOG.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/validation/<TASK_ID>_REPORT.md"`
- **Self-heal helper**:
  - `bash /home/alik/workspace/clawspace/bin/smith_task_progress.sh sync "<PROJECT_ID>"`
- **Task progression helper**:
  - `bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" VERIFY "management/validation/<TASK_ID>_REPORT.md" --action smith-validation-check --contains "<TASK_ID>" --contains "PASS"`
  - `bash /home/alik/workspace/clawspace/bin/smith_task_progress.sh complete "<PROJECT_ID>" "<TASK_ID>"`
  - `bash /home/alik/workspace/clawspace/bin/smith_task_progress.sh blocked "<PROJECT_ID>" "<TASK_ID>" --reason "<exact reason>"`
- **Manual re-scope fallback**:
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/PLAN.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/PLAN.md" --action smith_plan_write`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/BACKLOG.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/BACKLOG.md" --action smith_backlog_write`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/<TASK_ID>.md" --action smith_task_write`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "CURRENT_TASK.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/CURRENT_TASK.md" --action smith_current_task_write`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "BRIEF.md" --source-file "/home/alik/workspace/clawspace/workspaces/smith/drafts/<PROJECT_ID>/BRIEF.md" --action smith_brief_write`
- **Report to Neo**:
  use `sessions_send` with sessionKey `agent:neo:main` and a JSON envelope keyed
  by `project_id`
- **Run local Python diagnosis when needed**:
  `bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<runtime-or-workspace-directory>" --module unittest -- tests/test_main.py`
  uses `/home/alik/workspace/clawspace/venv-claw` without shell activation; it
  is not final project evidence.
