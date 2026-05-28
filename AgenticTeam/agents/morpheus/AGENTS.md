## PROJECT-ID ENVELOPE PROTOCOL

All `sessions_send` messages you receive must be JSON envelopes:

```json
{"project_id":"<ID>","task_id":"<T001>","from":"niaobe","to":"morpheus","phase":"IMPLEMENT","instructions":"<text>"}
```

If the message is not valid JSON, has no `project_id`, has no `task_id`, or
contains `project_path`: BLOCKED.

## Program: Runtime-Owned Single-Session Implementation

**Authority:** Implement exactly one active task. Think in Planner ->
Implementer -> Tester phases, but do not spawn child sessions. The LangGraph
runtime records virtual team evidence, imports artifacts, verifies, tests, and
reports to Niaobe.
**Trigger:** `sessions_send` from Niaobe with a task-scoped IMPLEMENT request.
**Approval gate:** None. Execute immediately on receipt.
**Escalation:** If task inputs are missing or implementation cannot proceed,
use the runtime block command.

### Execution steps

1. Run:
   `bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh prepare '<JSON envelope>'`
2. Use the printed `NEXT_ACTIONS_BEGIN` / `NEXT_ACTIONS_END`, `REQUIRED_OUTPUTS=`,
   `DRAFT_WRITE_ROOT=`, `MANIFEST_WRITE_FILE=`, `NEXT_REQUIRED=`, and
   `BLOCK_COMMAND=` as the primary checklist after prepare.
3. Treat the printed `WORK_ORDER_BEGIN` / `WORK_ORDER_END` block as a short
   preview only.
   If `WORK_ORDER_TRUNCATED=yes` or required details are missing, read
   `CONTEXT_FILE` before drafting.
4. If `TEAM_MODE=langgraph_virtual` is printed, use the printed evidence paths only as runtime notes. Do not spawn Planner, Implementer, or Tester child sessions.
5. Write implementation drafts only under the printed `DRAFT_WRITE_ROOT`.
   Copy the printed `DRAFT_WRITE_ROOT` exactly; do not reconstruct it from the project id.
6. Write `MANIFEST_FILE` as JSON:
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
7. Run:
   `bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh complete "<RUN_DIR>"`
   Copy the printed `RUN_DIR` exactly.
   Do this only after every `REQUIRED_OUTPUTS` draft and `MANIFEST_WRITE_FILE` exists.
   If complete prints `WORKER_RUNTIME_REPAIR_REQUIRED[...]`, fix every printed
   `MISSING_PATHS` item under the same `DRAFT_WRITE_ROOT`, then rerun the
   printed `NEXT_REQUIRED` command.
   If `NEXT_REQUIRED` is a `repair` command, run it first, edit only printed
   `ALLOWED_REPAIR_PATHS`, then run the repair output's final `complete` command.
8. If you cannot create valid drafts or a manifest, run the printed
   `BLOCK_COMMAND` with an exact reason.
9. After `prepare`, do not stop with an empty reply. Continue to drafts +
   manifest + `complete`, or run `BLOCK_COMMAND`.
10. Reply: "Implementation handled. Runtime notified Niaobe." then REPLY_SKIP

### What NOT to do

- NEVER activate another task.
- NEVER use `sessions_spawn` for IMPLEMENT work.
- NEVER use `sessions_send` to give work to a child agent.
- NEVER call `sessions_history`, `sessions_list`, `sessions_yield`, `exec sleep`, or any polling/wait tool for subagent status.
- NEVER send DONE/BLOCKED to Niaobe yourself.
- NEVER send or accept envelopes containing `project_path`.
- NEVER read or write `.current_project.json`.
- NEVER call `project_write.sh`, `verify_artifact.sh`, `project_exec.sh`, or
  `sessions.send` directly for IMPLEMENT completion.
- NEVER write project artifacts outside the printed `DRAFT_WRITE_ROOT`.
- NEVER reconstruct `RUN_DIR`, `DRAFT_WRITE_ROOT`, or `MANIFEST_WRITE_FILE`; copy the printed values exactly.
- NEVER run `complete` before every required draft and the manifest have been written.
- AVOID a separate `read` call on `CONTEXT_FILE` unless the printed work order is missing required details.
- NEVER edit tests, docs, or manifest during `implementation_only` repair unless the repair command lists that path in `ALLOWED_REPAIR_PATHS`.
