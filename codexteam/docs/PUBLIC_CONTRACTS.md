# Public Contracts

## Compatibility Policy

- Task IDs are uppercase `T` plus 3-6 digits.
- Contract version `1.0` fields cannot be removed or renamed without a version change.
- Optional fields may be added only when existing consumers remain valid.
- CLI exit codes and dry-run behavior are public operator contracts.

## Handoff V1

Machine-readable schema: `schemas/handoff-v1.json`.

Required scope includes handoff ID, team ID, task ID, attempt ID, role, profile, workspace, task context, constraints, and completion criteria.

## Result V1

Machine-readable schema: `schemas/result-v1.json`.

The Python validator performs additional semantic checks for canonical IDs, UTC timestamps, bounded summaries, relative paths, evidence requirements, and copied template content.

## Command Exit Codes

- `init-project.py`: `0` success; `2` invalid input or unsafe path.
- `update-tasks.py`: `0` success/no change; `2` invalid ledger or update.
- `verify-result.py`: `0` valid; `1` invalid JSON/contract; `2` expectation mismatch.
- `spawn-subagent.sh`: `0` draft ready or valid final result; `1` failed/correction needed; `2` invalid invocation or session scope; `3` interrupted by timeout with session retained when possible.
- `close-loop.sh`: `0` closed/already closed; `1` invalid result/artifact/state; `2` independent verification failure.

## Mutation Rule

Workers may write handoff-scoped project files during draft and feedback turns. Their conversation artifacts remain under ignored session storage, and those phases never write `results/<task>-<attempt>.json`. An accepted final turn writes that one deterministic result. Only the leader closure command updates task completion and delivery state.
