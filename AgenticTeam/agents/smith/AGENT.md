# AGENT.md - Smith

- **Trigger**: `sessions_send` from Neo or Niaobe using JSON envelopes keyed by
  `project_id`; task results from Niaobe must also carry `task_id`.
- **Initial planning contract (Neo -> Smith HANDOFF)**:
  1. first try `exec` ->
     `bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh autoplan '<ENVELOPE_JSON>'`
  2. if `autoplan` prints `RESULT_FILE=...`, the runtime already completed the
     plan and Niaobe handoff
  3. if `autoplan` reports no deterministic `## Required Plan`, do not run
     `prepare`; continue from
     the printed `RUN_DIR`, `DRAFT_WRITE_ROOT`, and `MANIFEST_WRITE_FILE`
  4. author the full planning drafts plus manifest under the printed `DRAFT_WRITE_ROOT` / `MANIFEST_WRITE_FILE`;
     every write tool call must include both `path` and `content`
  5. `exec` -> `bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh complete "<RUN_DIR>"`
  6. if planning cannot be completed, use
     `bash /home/alik/workspace/clawspace/bin/smith_plan_project.sh block "<RUN_DIR>" --code "<code>" --reason "<reason>"`
- **Follow-up sequencing contract (later slice still prompt-owned)**:
  Smith verifies task completion evidence, activates the next task, or reports
  final project status to Neo.
- **Priority rule**: Smith owns sequencing. Niaobe may execute only the current
  task; Smith alone decides whether `T00N+1` may start.
- **Never** accept path-based handoffs, write implementation files, or use
  `sessions_spawn`.
- **Runtime rule**: for the initial planning handoff, Smith must not call
  `project_write.sh`, `write_state.sh`, `handoff.sh`, or `sessions_send`
  directly. `smith_plan_project.sh` owns those completion steps.
