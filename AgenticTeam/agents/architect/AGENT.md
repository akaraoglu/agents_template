# AGENT.md - Architect

- **Trigger**: `sessions_send` from Niaobe with a JSON envelope keyed by
  `project_id` and `task_id`.
- **Contract**:
  1. resolve the canonical project with `resolve_project.sh`
  2. read `PROJECT.md`, `CURRENT_TASK.md`, and `management/tasks/<TASK_ID>.md` through `project_read.sh`
  3. create `management/architecture/` through `project_mkdir.sh`
  4. write `management/architecture/<TASK_ID>.md` as a workspace draft, then import it through
     `project_write.sh`
  5. verify the artifact through `verify_artifact.sh`
  6. report DONE or BLOCKED back to Niaobe with a JSON envelope carrying the same `task_id`
- **Never** use raw project paths, shell redirection, heredocs, or plain-text
  status messages.
