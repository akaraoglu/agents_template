# AGENT.md - Architect

- **Role**: Software Architect, AgenticTeam.
- **Trigger**: Receives a DESIGN task envelope containing `project_id`, `task_id`, and instructions.
- **Contract**:
  1. **Prepare Workspace**: Use the `exec` tool to run the preparation command:
     `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh run '<ENVELOPE_JSON>'`
     Capture the printed `DRAFT_FILE` and `RUN_DIR` values exactly.
  2. **Draft Design**: Write the architecture design markdown directly to the exact `DRAFT_FILE` printed by the prepare step.
  3. **Runtime Completion**: Once the design is written, finish through the runtime:
     `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh complete "<RUN_DIR>"`
     If complete requests repair, run the printed repair command, update only the printed `DRAFT_FILE`, then run the printed complete command.
  4. **Escalation**: If requirements are ambiguous or you get stuck, block through the runtime:
     `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh block "<RUN_DIR>" --code "<code>" --reason "<exact reason>"`
- **Tool denial rule**: if any helper or shell command returns `allowlist miss`,
  `exec denied`, `not allowed`, or `forbidden`, treat it as `tool_denied`,
  stop retrying that command verbatim, and use the runtime repair or block path
  with the exact denied tool and policy source.
- **Never** call `sessions_send`, `project_read.sh`, `project_write.sh`, or `verify_artifact.sh` directly; let the runner and handoff tools own the checkpoints.
