# Tools - Architect

## Return contract to Niaobe

Use only JSON envelopes keyed by `project_id`.

- Never send plain text DONE/BLOCKED messages.
- Never include `project_path` or absolute project file paths in the envelope.
- A printed JSON block is not delivery. `architect_run_task.sh` owns the actual
  return path to Niaobe.

## File operations

```text
exec: bash /home/alik/workspace/clawspace/bin/architect_run_task.sh run "<ENVELOPE_JSON>"
read: printed WORK_ORDER_BEGIN / WORK_ORDER_END if needed
exec: bash /home/alik/workspace/clawspace/bin/architect_run_task.sh read "<RUN_DIR>" "<RELATIVE_PATH>"
write: <DRAFT_FILE>
exec: bash /home/alik/workspace/clawspace/bin/architect_run_task.sh complete "<RUN_DIR>"
exec: bash /home/alik/workspace/clawspace/bin/architect_run_task.sh repair "<RUN_DIR>"
exec: bash /home/alik/workspace/clawspace/bin/architect_run_task.sh block "<RUN_DIR>" --code "<CODE>" --reason "<EXACT_REASON>"
```

Do not invent paths. Use only the `RUN_DIR`, `CONTEXT_FILE`, and `DRAFT_FILE`
printed by `run` or `repair`.
Never use heredocs, pipes, or shell redirection with project file writes.

## Python diagnostics

```text
exec: bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<runtime-or-workspace-directory>" --module unittest -- tests/test_main.py
exec: bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<runtime-or-workspace-directory>" --syntax-check "src/main.py"
```

`python_claw.sh` uses `/home/alik/workspace/clawspace/venv-claw` without shell
activation. Use it only for local Python diagnosis; `architect_run_task.sh`
remains the authority for lifecycle and final delivery.
