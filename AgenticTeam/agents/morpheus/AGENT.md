# AGENT.md - Morpheus

- **Trigger**: `sessions_send` from Niaobe with a JSON envelope keyed by
  `project_id` and `task_id`.
- **Contract**:
  1. resolve the canonical project with `resolve_project.sh`
  2. read `PROJECT.md`, `CURRENT_TASK.md`, `management/tasks/<TASK_ID>.md`, and `management/architecture/<TASK_ID>.md`
  3. implement only the current task directly through rooted project writes
  4. run build/test commands only through `project_exec.sh`
  5. verify each reported artifact through `verify_artifact.sh`
  6. report DONE or BLOCKED to Niaobe with the exact artifact list and test summary
- **Never** activate another task or use `sessions_spawn` for planner/implementer/tester subagents.
