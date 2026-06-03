# Tools - Morpheus

You have standard tools (`read`, `write`, `exec`) to manipulate your runtime
workspace and run CLI scripts.

## 1. Task Packet

Morpheus work starts from a `TASK_PACKET_BEGIN` message. The packet already
contains the runtime-owned task context and exact paths/commands.

Do not run a preparation command.

## 2. Writing Artifacts

Write all implementation draft files under:

```text
<DRAFT_WRITE_ROOT>/<project-relative-path>
```

Copy `DRAFT_WRITE_ROOT` from the task packet exactly.

## 3. Runtime Manifest

Write `MANIFEST_WRITE_FILE` with:

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

Do not invent validation evidence. Runtime validation is authoritative.

## 4. Runtime Reporting

Once drafts and manifest are ready, finish through the packet's exact
`REPORT_COMMAND`. Pass only the packet's `RUN_DIR`; never pass
`DRAFT_WRITE_ROOT`, `MANIFEST_WRITE_FILE`, or `DRAFT_DIR`.

If reporting requests repair, edit only the printed allowed paths and rerun
the printed `RUN_DIR` report command. If reporting prints
`WORKER_RUNTIME_FAILED`, the task is not complete.

## 5. Project Blocking

If the task is blocked by invalid or missing input, run the packet's exact
`BLOCK_COMMAND`.

## 6. Python Diagnostics

```text
exec: bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<DRAFT_WRITE_ROOT>" --module unittest -- tests/test_main.py
exec: bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<DRAFT_WRITE_ROOT>" --syntax-check "src/main.py"
```

`python_claw.sh` uses `/home/alik/workspace/clawspace/venv-claw` without shell
activation. Use it only to diagnose or repair drafts. Its output is never DONE
evidence; final acceptance still requires the packet's `REPORT_COMMAND`.
