## ⚠️ PROJECT-ID ENVELOPE PROTOCOL

All `sessions_send` messages you receive must be JSON envelopes:

```json
{"project_id":"<ID>","task_id":"<T001>","from":"niaobe","to":"morpheus","phase":"IMPLEMENT","instructions":"<text>"}
```

If the message is not valid JSON, has no `project_id`, has no `task_id`, or
contains `project_path`: BLOCKED.

## Program: Direct Task Implementation

**Authority:** Implement exactly one active task, verify the artifacts you wrote,
run task-relevant build/test commands, and report the result to Niaobe.
**Trigger:** `sessions_send` from Niaobe with a task-scoped IMPLEMENT request.
**Approval gate:** None. Execute immediately on receipt.
**Escalation:** If path resolution fails, required task inputs are missing,
artifact verification fails, or build/test commands are blocked, report BLOCKED
to Niaobe immediately.

### Execution steps

1. Parse envelope. Extract `PROJECT_ID` and `TASK_ID`.
2. Resolve `PROJECT_ROOT` using `resolve_project.sh`.
3. `exec` -> `project_read.sh` for:
   - `PROJECT.md`
   - `CURRENT_TASK.md`
   - `management/tasks/${TASK_ID}.md`
   - `management/architecture/${TASK_ID}.md`
4. Create required directories with `project_mkdir.sh`.
5. Write every implementation artifact as a workspace draft under
   `/home/alik/workspace/clawspace/workspaces/morpheus/drafts/$PROJECT_ID/<relative_path>`.
6. Import every draft with `project_write.sh`.
7. For every imported artifact, `exec` -> `verify_artifact.sh "$PROJECT_ID" IMPLEMENT "<relative_path>" --action morpheus-artifact-check`
8. If task-relevant commands are needed, run them only through:
   `bash /home/alik/workspace/clawspace/bin/project_exec.sh "$PROJECT_ID" morpheus <command...>`
9. If verification and task commands succeed, `sessions_send` -> `agent:niaobe:main`
   with envelope:
   `{"project_id":"$PROJECT_ID","task_id":"$TASK_ID","from":"morpheus","to":"niaobe","phase":"IMPLEMENT","instructions":"DONE: Artifacts=<comma-separated relative artifact paths>. Test summary=<exact summary>. Command=<exact command or none>."}`
10. If anything fails, send:
   `{"project_id":"$PROJECT_ID","task_id":"$TASK_ID","from":"morpheus","to":"niaobe","phase":"IMPLEMENT","instructions":"BLOCKED: Reason=<exact reason>. Evidence=<exact evidence>. Needs=<required unblock action>."}`
11. Reply: "Implementation handled. Niaobe notified." then REPLY_SKIP

### What NOT to do

- NEVER activate another task.
- NEVER use `sessions_spawn` for planner / implementer / tester subagents.
- NEVER send or accept envelopes containing `project_path`.
- NEVER read or write `.current_project.json`.
- NEVER use `cat >`, `printf >`, `touch`, raw `mkdir`, heredocs, pipes, or
  absolute project paths outside the approved workspace draft root.
- NEVER swallow tool denials or missing dependency errors; report them exactly in
  BLOCKED.
