# SKILLS.md - Morpheus

- **Prepare a task runtime**:
  `bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh prepare '<JSON envelope>'`
- **Use the generated handoff**:
  use the printed `WORK_ORDER_BEGIN` / `WORK_ORDER_END`, `RUN_DIR`, `RUNTIME_DIR`, `DRAFT_WRITE_ROOT`, and `MANIFEST_WRITE_FILE`.
  Copy printed paths exactly; do not reconstruct them from the project id.
  `MANIFEST_WRITE_FILE` is inside `DRAFT_WRITE_ROOT`.
  If `REQUIRED_OUTPUTS=` is printed, every listed path must be present in the drafts and manifest.
- **Create implementation drafts**:
  write every artifact under `DRAFT_WRITE_ROOT` using the same project-relative path that should be imported.
- **Write the runtime manifest**:
  `MANIFEST_WRITE_FILE` must be JSON with `artifacts` and `test_command`.
- **Complete the task**:
  `bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh complete "<RUN_DIR>"`
- **Repair when requested**:
  if complete prints `WORKER_RUNTIME_REPAIR_REQUIRED[...]`, update the existing drafts or manifest and rerun the printed `NEXT_REQUIRED`.
  If `NEXT_REQUIRED` is a `repair` command, run it first, edit only printed
  `ALLOWED_REPAIR_PATHS`, then run the final printed `complete` command.
- **Block the task**:
  `bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh block "<RUN_DIR>" --code "<code>" --reason "<reason>"`
- **Avoid context rereads**:
  do not use a separate read tool call on `CONTEXT_FILE` unless the printed work order is missing required details.
