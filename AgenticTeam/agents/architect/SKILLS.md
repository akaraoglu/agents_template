# SKILLS.md - Architect

- **Prepare the deterministic worker context and visible work order**:
  `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh run '<ENVELOPE_JSON>'`
- **Use rooted inputs from the generated output**:
  - printed `WORK_ORDER_BEGIN` / `WORK_ORDER_END`
  - printed `DRAFT_TEMPLATE_BEGIN` / `DRAFT_TEMPLATE_END`
- **Request additional rooted context when needed**:
  `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh read "<RUN_DIR>" "<RELATIVE_PATH>"`
- **Write only to the exact runtime-owned draft path**:
  `write` with `path=<DRAFT_FILE>` and `content=<architecture markdown>`
- **Finish or block through the runtime**:
  - `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh complete "<RUN_DIR>"`
  - `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh repair "<RUN_DIR>"`
  - `bash /home/alik/workspace/clawspace/bin/architect_run_task.sh block "<RUN_DIR>" --code <code> --reason "<exact reason>"`
