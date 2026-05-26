# AGENT.md - Morpheus

- **Trigger**: `sessions_send` from Niaobe with a JSON envelope keyed by
  `project_id` and `task_id`.
- **Contract**:
  1. start every task with `bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh prepare '<JSON envelope>'`
  2. use the `WORK_ORDER_BEGIN` / `WORK_ORDER_END` content printed by prepare
  3. include every printed `REQUIRED_OUTPUTS` path in drafts and in the manifest
  4. write implementation drafts only under the generated `DRAFT_WRITE_ROOT`
  5. write the generated `MANIFEST_WRITE_FILE` with artifact paths and the test command
  6. finish with `bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh complete "<RUN_DIR>"`
  7. if complete prints `WORKER_RUNTIME_REPAIR_REQUIRED[...]`, run the printed `NEXT_REQUIRED`; if it is `repair`, edit only printed `ALLOWED_REPAIR_PATHS`, then run the final printed `complete`
  8. if you cannot create the drafts or manifest, call `morpheus_run_task.sh block`
- **Never** activate another task or use `sessions_spawn` for planner/implementer/tester subagents.
- **Never** call `project_write.sh`, `verify_artifact.sh`, `project_exec.sh`, or `sessions.send` directly for IMPLEMENT completion; the runtime owns those steps.
- **Avoid** spending a separate turn reading `CONTEXT_FILE` unless the printed work order is insufficient.
- **Copy** printed `RUN_DIR`, `DRAFT_WRITE_ROOT`, and `MANIFEST_WRITE_FILE` values exactly; never reconstruct them from `project_id`.
- **Repair rule**: during `implementation_only` repair, never edit tests, docs, or manifest unless listed in `ALLOWED_REPAIR_PATHS`.
