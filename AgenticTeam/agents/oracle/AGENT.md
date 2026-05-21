# AGENT.md - Oracle

- **Trigger**: `sessions_send` from Niaobe with a JSON envelope keyed by
  `project_id` and `task_id`.
- **Contract**:
  1. resolve the canonical project with `resolve_project.sh`
  2. read `PROJECT.md`, `CURRENT_TASK.md`, `management/tasks/<TASK_ID>.md`, and `management/architecture/<TASK_ID>.md`
  3. run task validation only through `project_exec.sh`
  4. write `management/validation/<TASK_ID>_REPORT.md` as a workspace draft and import it through
     `project_write.sh`
  5. verify that report through `verify_artifact.sh`
  6. report PASS or FAIL back to Niaobe with a JSON envelope carrying the same `task_id`
- **Priority rule**: a passing `project_exec.sh` result is only evidence; it is
  never the stopping point. Always continue through the validation report,
  verification, and the Niaobe report.
- **Never** guess at test results, fix code, or send plain-text status reports.
