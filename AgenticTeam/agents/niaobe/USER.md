# Team — Niaobe

## Smith (your manager)
General Manager. Sends you one active task at a time. Report `TASK_DONE` or
`TASK_BLOCKED` to him only.
Session key: `agent:smith:main`

## Architect (designer)
Reads `PROJECT.md`, `CURRENT_TASK.md`, and `management/tasks/Txxx.md`; writes
`management/architecture/Txxx.md`.
Session key: `agent:architect:main`

## Morpheus (builder)
Implements the current task directly, writes task artifacts under `src/` and
`tests/`, and reports exact artifact paths plus test evidence.
Session key: `agent:morpheus:main`

## Oracle (validator)
Validates the current task and writes `management/validation/Txxx_REPORT.md`.
Session key: `agent:oracle:main`

## Chain
Master → Neo → Smith → **Niaobe** → {Architect, Morpheus, Oracle}
