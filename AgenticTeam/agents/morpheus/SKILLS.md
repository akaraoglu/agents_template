# SKILLS.md - Morpheus

- **Workspace exploration**:
  read `PROJECT.md`, the active task file, and relevant source/tests before editing.

- **Implementation**:
  use the OpenClaw file tools only inside the current task's writable paths.

- **Testing**:
  create or update tests and run the narrowest useful validation command when your available tools allow it.

- **Completion**:
  return the required `WORK_RESULT_JSON_BEGIN` / `WORK_RESULT_JSON_END` envelope only after implementation and validation are complete.

- **Blocking**:
  return `BLOCKED` with an exact reason when the current task needs a path outside the writable scope.
