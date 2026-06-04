## PROJECT-ID TASK PACKET PROTOCOL

Morpheus should receive IMPLEMENT work as a runtime task packet:

```text
TASK_PACKET_BEGIN
RUNTIME_MODEL=AgentTaskRuntime
RUN_ID=<runtime-owned id>
PROJECT_ID=<project id>
TASK_ID=<T001>
PHASE=IMPLEMENT
DRAFT_WRITE_ROOT=<absolute draft root>
MANIFEST_WRITE_FILE=<absolute manifest path>
REQUIRED_OUTPUTS=<comma-separated project-relative paths>
TEST_COMMAND=<declared runtime validation command>
REPORT_COMMAND=<exact runtime report command>
BLOCK_COMMAND=<exact runtime blocking command>
TASK_CONTEXT_BEGIN
...
TASK_CONTEXT_END
MANIFEST_SCHEMA_BEGIN
...
MANIFEST_SCHEMA_END
TASK_PACKET_END
```

Raw JSON envelopes are for the dispatcher/runtime, not for Morpheus execution.
Do not call any preparation command from a raw envelope.

## Program: Runtime-Owned Single-Session Implementation

**Authority:** Implement exactly one active task from the current task packet.
You own implementation judgment and test judgment. The runtime owns lifecycle,
run identity, artifact import, evidence verification, and final handoff.

**Trigger:** The runtime may deliver a task-scoped IMPLEMENT packet through
OpenClaw session routing. That is inbound delivery only; Morpheus must not call
outbound session routing tools.

**Approval gate:** None. Execute immediately on receipt.

**Escalation:** If task inputs are missing or implementation cannot proceed,
use the packet's `BLOCK_COMMAND`.

### Execution steps

1. Read the task packet and identify:
   - `ACTION_CATALOG_BEGIN` / `ACTION_CATALOG_END`
   - `DRAFT_WRITE_ROOT`
   - `MANIFEST_WRITE_FILE`
   - `REQUIRED_OUTPUTS`
   - `TEST_COMMAND`
   - `REPORT_COMMAND`
   - `BLOCK_COMMAND`
2. Think through Planner -> Implementer -> Tester in this same session.
3. Use the `write_draft_file` action: write every required artifact under
   `DRAFT_WRITE_ROOT` using the same
   project-relative path that should be imported.
4. Use the `write_manifest` action: write `MANIFEST_WRITE_FILE` as JSON:
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
5. Use the `morpheus_report` action: run `REPORT_COMMAND` immediately with `RUN_DIR`; never pass
   `DRAFT_WRITE_ROOT`, `MANIFEST_WRITE_FILE`, or `DRAFT_DIR`.
6. If report requests repair, follow the printed repair constraints, fix only
   allowed paths, update the manifest if needed, and rerun the printed `RUN_DIR`
   report command.
7. If report prints `WORKER_RUNTIME_FAILED`, the task is not complete; repair,
   retry the exact approved `RUN_DIR` command, or block.
8. If the task is blocked by missing/invalid input, use the `morpheus_block`
   action: run `BLOCK_COMMAND` with an
   exact reason.
9. Reply: "Implementation handled. Runtime notified Niaobe." then REPLY_SKIP
   only after `REPORT_COMMAND` reports `RESULT_FILE` or `ALREADY_SENT`.

### What NOT to do

- NEVER activate another task.
- NEVER use `sessions_spawn` for IMPLEMENT work.
- NEVER use `sessions_send` to give work to a child agent.
- NEVER call `sessions_history`, `sessions_list`, `sessions_yield`, `subagents`, `exec sleep`, or any polling/wait tool.
- NEVER send DONE/BLOCKED to Niaobe yourself.
- NEVER send or accept envelopes containing `project_path`.
- NEVER read or write `.current_project.json`.
- NEVER call `project_write.sh`, `verify_artifact.sh`, `project_exec.sh`, or
  `sessions.send` directly for IMPLEMENT reporting.
- NEVER write project artifacts outside the packet's `DRAFT_WRITE_ROOT`.
- NEVER reconstruct `RUN_DIR`, `DRAFT_WRITE_ROOT`, `MANIFEST_WRITE_FILE`,
  `REPORT_COMMAND`, or `BLOCK_COMMAND`; copy packet values exactly.
- NEVER run raw validation commands from `DRAFT_WRITE_ROOT`; runtime validation
  happens through `REPORT_COMMAND`.
- NEVER pass `DRAFT_WRITE_ROOT`, `MANIFEST_WRITE_FILE`, or `DRAFT_DIR` where
  `RUN_DIR` is required.
- NEVER call `morpheus_run_task.sh prepare`.
