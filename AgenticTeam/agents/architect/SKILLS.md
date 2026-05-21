# SKILLS.md - Architect

- **Resolve the canonical project**:
  `bash /home/alik/workspace/clawspace/bin/resolve_project.sh "<PROJECT_ID>"`
- **Read canonical inputs**:
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "CURRENT_TASK.md"`
  - `bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md"`
- **Prepare and import the design artifact**:
  - `bash /home/alik/workspace/clawspace/bin/project_mkdir.sh "<PROJECT_ID>" "management/architecture"`
  - `write /home/alik/workspace/clawspace/workspaces/architect/drafts/<PROJECT_ID>/<TASK_ID>.md`
  - `bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/architecture/<TASK_ID>.md" --source-file "/home/alik/workspace/clawspace/workspaces/architect/drafts/<PROJECT_ID>/<TASK_ID>.md" --action architect_project_write`
- **Verify the imported design**:
  `bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" DESIGN "management/architecture/<TASK_ID>.md" --action architect-write --contains "<TASK_ID>"`
- **Report to Niaobe**:
  use `sessions_send` with a JSON envelope keyed by `project_id` and `task_id`
