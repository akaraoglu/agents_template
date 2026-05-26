# SKILLS.md - Architect

- **Prepare the deterministic worker context**:
  `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh prepare '<ENVELOPE_JSON>'`
- **Read rooted inputs from the generated files**:
  - `read <HANDOFF_FILE>`
  - `read <CONTEXT_FILE>`
- **Request additional rooted context when needed**:
  `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh read "<RUN_DIR>" "<RELATIVE_PATH>"`
- **Write only to the exact runtime-owned draft path**:
  `write <DRAFT_FILE>`
- **Finish or block through the runtime**:
  - `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh complete "<RUN_DIR>"`
  - `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh block "<RUN_DIR>" --code <code> --reason "<exact reason>"`
