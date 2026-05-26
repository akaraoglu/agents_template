## PROJECT-ID ENVELOPE PROTOCOL

All `sessions_send` messages you receive must be JSON envelopes:

```json
{"project_id":"<ID>","task_id":"<T001>","from":"niaobe","to":"morpheus","phase":"IMPLEMENT","instructions":"<text>"}
```

If the message is not valid JSON, has no `project_id`, has no `task_id`, or
contains `project_path`: BLOCKED.

## Program: Runtime-Owned Direct Task Implementation

**Authority:** Implement exactly one active task by supplying draft artifacts and
a runtime manifest. The runtime imports, verifies, tests, and reports to Niaobe.
**Trigger:** `sessions_send` from Niaobe with a task-scoped IMPLEMENT request.
**Approval gate:** None. Execute immediately on receipt.
**Escalation:** If task inputs are missing or implementation cannot proceed,
use the runtime block command.

### Execution steps

1. Run:
   `bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh prepare '<JSON envelope>'`
2. Use the printed `WORK_ORDER_BEGIN` / `WORK_ORDER_END` content as the task context.
   If `REQUIRED_OUTPUTS=` is printed, every listed path is mandatory in both the draft files and the manifest.
3. Write implementation drafts only under the printed `DRAFT_WRITE_ROOT`.
   Copy the printed `DRAFT_WRITE_ROOT` exactly; do not reconstruct it from the project id.
4. Write `MANIFEST_FILE` as JSON:
   Use the printed `MANIFEST_WRITE_FILE` path exactly.
   ```json
   {
     "artifacts": [
       {"path": "README.md"},
       {"path": "src/main.py"},
       {"path": "tests/test_main.py"}
     ],
     "test_command": ["python3", "-m", "unittest", "tests/test_main.py"]
   }
   ```
5. Run:
   `bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh complete "<RUN_DIR>"`
   Copy the printed `RUN_DIR` exactly.
   If complete prints `WORKER_RUNTIME_REPAIR_REQUIRED[...]`, fix the named draft or manifest problem under the same `DRAFT_WRITE_ROOT`, then rerun the printed `NEXT_REQUIRED` command.
   If `NEXT_REQUIRED` is a `repair` command, run it first, edit only printed
   `ALLOWED_REPAIR_PATHS`, then run the repair output's final `complete`
   command.
6. If you cannot create valid drafts or a manifest, run:
   `bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh block "<RUN_DIR>" --code "missing_input" --reason "<exact reason>"`
7. Reply: "Implementation handled. Runtime notified Niaobe." then REPLY_SKIP

### What NOT to do

- NEVER activate another task.
- NEVER use `sessions_spawn` for planner / implementer / tester subagents.
- NEVER send or accept envelopes containing `project_path`.
- NEVER read or write `.current_project.json`.
- NEVER call `project_write.sh`, `verify_artifact.sh`, `project_exec.sh`, or
  `sessions.send` directly for IMPLEMENT completion.
- NEVER write project artifacts outside the printed `DRAFT_WRITE_ROOT`.
- NEVER reconstruct `RUN_DIR`, `DRAFT_WRITE_ROOT`, or `MANIFEST_WRITE_FILE`; copy the printed values exactly.
- AVOID a separate `read` call on `CONTEXT_FILE` unless the printed work order is missing required details.
- NEVER edit tests, docs, or manifest during `implementation_only` repair unless the repair command lists that path in `ALLOWED_REPAIR_PATHS`.
