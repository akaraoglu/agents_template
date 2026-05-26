# Tools - Morpheus

## Current IMPLEMENT contract

- Morpheus handles the active implementation task directly.
- Morpheus writes draft artifacts and a runtime manifest.
- `morpheus_run_task.sh` imports artifacts, verifies them, runs project tests, and reports to Niaobe.
- missing dependencies or missing tools must be escalated through the runtime block command.

## Runtime prepare

```text
exec: bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh prepare '<JSON envelope>'
```

Use the printed `WORK_ORDER_BEGIN` / `WORK_ORDER_END`, `RUN_DIR`, `RUNTIME_DIR`, `DRAFT_WRITE_ROOT`, and `MANIFEST_WRITE_FILE`.
Copy these paths exactly; do not reconstruct them from the project id.
`MANIFEST_WRITE_FILE` is inside `DRAFT_WRITE_ROOT`, so all model-written files share one base directory.
If `REQUIRED_OUTPUTS=` is printed, those paths are mandatory draft and manifest entries.

## Draft artifacts

```text
write: <DRAFT_WRITE_ROOT>/<project_relative_path>
write: <MANIFEST_WRITE_FILE>
```

`MANIFEST_FILE` must contain:

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

## Runtime complete

```text
exec: bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh complete "<RUN_DIR>"
```

If this prints `WORKER_RUNTIME_REPAIR_REQUIRED[...]`, fix the named draft or manifest issue and rerun the printed `NEXT_REQUIRED`.
If `NEXT_REQUIRED` is a `repair` command, run it first, edit only printed
`ALLOWED_REPAIR_PATHS`, then run the final printed `complete` command.

## Runtime repair

```text
exec: bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh repair "<RUN_DIR>"
```

During `implementation_only` repair, do not edit tests, docs, or manifest
unless the repair output lists that path in `ALLOWED_REPAIR_PATHS`.

## Runtime block

```text
exec: bash /home/alik/workspace/clawspace/bin/morpheus_run_task.sh block "<RUN_DIR>" --code "<code>" --reason "<reason>"
```

## Main-session limits

- Morpheus must not activate the next task
- Morpheus must not claim success directly
- Morpheus must not call lower-level project helpers for IMPLEMENT completion
- Morpheus must copy printed runtime paths exactly
- Morpheus should not spend a separate turn reading `CONTEXT_FILE` unless the printed work order is insufficient
