# AGENT.md - Architect

- **Trigger**: `sessions_send` from Niaobe with a JSON envelope keyed by
  `project_id` and `task_id`.
- **Contract**:
  1. call `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh prepare '<ENVELOPE_JSON>'`
  2. read the generated `handoff.json` and `context.md`
  3. if more project context is needed, call
     `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh read "<RUN_DIR>" "<RELATIVE_PATH>"`
  4. write the architecture draft only to the exact `DRAFT_FILE` produced by
     `prepare`
  5. call `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh complete "<RUN_DIR>"`
  6. if the task cannot be completed, call
     `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh block "<RUN_DIR>" --code <code> --reason "<exact reason>"`
- **Never** use raw project paths, shell redirection, heredocs, or plain-text
  status messages.
- Never call `sessions_send`, `project_read.sh`, `project_write.sh`, or
  `verify_artifact.sh` directly from the prompt path; the worker runtime owns
  those protocol steps.
