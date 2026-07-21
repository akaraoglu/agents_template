# Team Execution Plan

Execute tasks in `TASKS.md` order. Each worker reads the matching handoff in `management/tasks/`, writes only within allowed paths, and returns a schema-valid result under `results/`. The leader independently verifies the result before advancing state.
