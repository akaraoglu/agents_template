# SKILLS.md - Morpheus

- **Prepare a task runtime**:
  `bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh prepare '<JSON envelope>'`
- **Use the generated handoff**:
  use the printed `NEXT_ACTIONS_BEGIN` / `NEXT_ACTIONS_END`, `RUN_DIR`,
  `RUNTIME_DIR`, `DRAFT_WRITE_ROOT`, `MANIFEST_WRITE_FILE`, `NEXT_REQUIRED`,
  and `BLOCK_COMMAND`.
  Copy printed paths exactly; do not reconstruct them from the project id.
  `MANIFEST_WRITE_FILE` is inside `DRAFT_WRITE_ROOT`.
  If `REQUIRED_OUTPUTS=` is printed, every listed path must be present in the drafts and manifest.
  Treat `WORK_ORDER_BEGIN` / `WORK_ORDER_END` as a short preview only.
  If `WORK_ORDER_TRUNCATED=yes`, read `CONTEXT_FILE` before drafting.
- **Use virtual team thinking**:
  if `TEAM_MODE=langgraph_virtual` is printed, think through Planner -> Implementer -> Tester phases in the main session.
  Do not spawn child sessions. The runtime records team evidence files during completion.
- **Create implementation drafts**:
  write every artifact under `DRAFT_WRITE_ROOT` using the same project-relative path that should be imported.
- **Write the runtime manifest**:
  `MANIFEST_WRITE_FILE` must be JSON with `artifacts` and `test_command`.
- **Complete the task**:
  `bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh complete "<RUN_DIR>"`
  run this only after every `REQUIRED_OUTPUTS` draft and `MANIFEST_WRITE_FILE` exist.
- **Repair when requested**:
  if complete prints `WORKER_RUNTIME_REPAIR_REQUIRED[...]`, create or update every printed `MISSING_PATHS` item and rerun the printed `NEXT_REQUIRED`.
  If `NEXT_REQUIRED` is a `repair` command, run it first, edit only printed
  `ALLOWED_REPAIR_PATHS`, then run the final printed `complete` command.
- **Block the task**:
  run the printed `BLOCK_COMMAND` with the exact reason
- **Avoid context rereads**:
  do not use a separate read tool call on `CONTEXT_FILE` unless the printed work order is missing required details.
  Do not stop after `prepare`; continue to drafts + manifest + `complete`, or run `BLOCK_COMMAND`.
