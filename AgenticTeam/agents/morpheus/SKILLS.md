# SKILLS.md - Morpheus

- **Resolve and read canonical project state**:
  - `bash /home/alik/workspace/clawspace/bin/resolve_project.sh "<PROJECT_ID>"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "CURRENT_TASK.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/architecture/<TASK_ID>.md"`
- **Rooted helpers**:
  - `bash /home/alik/workspace/clawspace/bin/project_mkdir.sh "<PROJECT_ID>" "<relative_dir>"`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "<relative_path>" --source-file "/home/alik/workspace/clawspace/workspaces/morpheus/drafts/<PROJECT_ID>/<relative_path>" --action morpheus_project_write`
  - `bash /home/alik/workspace/clawspace/bin/project_exec.sh "<PROJECT_ID>" morpheus <command...>`
- **Verify reported build artifacts**:
  `bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" IMPLEMENT "<artifact>" --action morpheus-artifact-check`
- **Report to Niaobe**:
  use `sessions_send` with a JSON envelope keyed by `project_id` and `task_id`
