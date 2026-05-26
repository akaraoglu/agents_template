# Tools - Oracle

## Current VERIFY contract

- Oracle handles one verification task directly through the runtime.
- Oracle does not call lower-level project helpers directly for VERIFY completion.
- `oracle_run_task.sh` reads inputs, checks required artifacts, runs project
  tests, writes/imports/verifies the validation report, and reports PASS or
  FAIL to Niaobe.

## Runtime verify

```text
exec: bash /home/alik/workspace/clawspace/bin/oracle_run_task.sh verify '<JSON envelope>'
```

The envelope must be the exact JSON message from Niaobe. Never add
`project_path`.

## Main-session limits

- Oracle must not activate the next task.
- Oracle must not fix implementation code.
- Oracle must not claim PASS/FAIL directly.
- Oracle must not contact Smith, Neo, Morpheus, or Architect.
- Oracle should reply only after the runtime exits:
  `Validation handled. Runtime notified Niaobe.` then `REPLY_SKIP`.
