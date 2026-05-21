# SKILLS.md - Oracle

- **Resolve and read canonical validation inputs**:
  - `bash /home/alik/workspace/clawspace/bin/resolve_project.sh "<PROJECT_ID>"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "CURRENT_TASK.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/architecture/<TASK_ID>.md"`
- **Run tests through the rooted exec helper**:
  `bash /home/alik/workspace/clawspace/bin/project_exec.sh "<PROJECT_ID>" oracle <project-native verification command>`
- **Import the validation artifact**:
  - `write /home/alik/workspace/clawspace/workspaces/oracle/drafts/<PROJECT_ID>/<TASK_ID>_REPORT.md`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/validation/<TASK_ID>_REPORT.md" --source-file "/home/alik/workspace/clawspace/workspaces/oracle/drafts/<PROJECT_ID>/<TASK_ID>_REPORT.md" --action oracle_project_write`
- **Verify the imported validation artifact**:
  `bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" VERIFY "management/validation/<TASK_ID>_REPORT.md" --action oracle-write --contains "<TASK_ID>"`
- **Sequence rule**:
  do not stop after `project_exec.sh`; always finish the write -> verify ->
  report sequence
- **Report to Niaobe**:
  use `sessions_send` with a JSON envelope keyed by `project_id` and `task_id`
