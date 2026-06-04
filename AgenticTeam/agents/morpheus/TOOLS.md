# Tools - Morpheus

Use the task packet's allowed actions. Packet-scoped `read`, `write`, and
`exec` remain available only to complete those actions: read packet context,
write drafts and the manifest, and run exact approved wrapper commands.

## 1. Task Packet

Morpheus work starts from a `TASK_PACKET_BEGIN` message. The packet already
contains the runtime-owned task context and exact paths/commands.

Do not run a preparation command.

## 2. Writing Artifacts

Action: `write_draft_file`

Write all implementation draft files under:

```text
<DRAFT_WRITE_ROOT>/<project-relative-path>
```

Copy `DRAFT_WRITE_ROOT` from the task packet exactly.

## 3. Runtime Manifest

Action: `write_manifest`

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

Action: `morpheus_report`

Once drafts and manifest are ready, finish through the packet's exact
`REPORT_COMMAND`. Pass only the packet's `RUN_DIR`; never pass
`DRAFT_WRITE_ROOT`, `MANIFEST_WRITE_FILE`, or `DRAFT_DIR`.

If reporting requests repair, edit only the printed allowed paths and rerun
the printed `RUN_DIR` report command. If reporting prints
`WORKER_RUNTIME_FAILED`, the task is not complete.

## 5. Project Blocking

Action: `morpheus_block`

If the task is blocked by invalid or missing input, run the packet's exact
`BLOCK_COMMAND`.

## 6. Python Diagnostics

Action: `python_claw`

```text
bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<DRAFT_WRITE_ROOT>" --module unittest -- tests/test_main.py
bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<DRAFT_WRITE_ROOT>" --syntax-check "src/main.py"
```

`python_claw.sh` uses `/home/alik/workspace/clawspace/venv-claw` without shell
activation. Use it only to diagnose or repair drafts. Its output is never DONE
evidence; final acceptance still requires the packet's `REPORT_COMMAND`.

## 7. Session Routing Boundary

The runtime may deliver a task packet to Morpheus through OpenClaw session
routing. Morpheus must not call outbound session routing tools, including
`sessions_send`, `sessions_spawn`, `sessions_list`, `sessions_history`,
`sessions_yield`, or `subagents`.
