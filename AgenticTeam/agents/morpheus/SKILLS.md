# SKILLS.md - Morpheus

- **Use the runtime task packet**:
  read the current `TASK_PACKET_BEGIN` / `TASK_PACKET_END` message and copy
  the packet paths and commands exactly.
- **Use virtual team thinking**:
  think through Planner -> Implementer -> Tester phases in the main session.
  Do not spawn child sessions.
- **Create implementation drafts**:
  write every artifact under `DRAFT_WRITE_ROOT` using the same
  project-relative path that should be imported.
- **Write the runtime manifest**:
  `MANIFEST_WRITE_FILE` must be JSON with `artifacts` and `test_command`.
  Do not invent validation evidence; the runtime records validation after
  importing drafts and running `project_exec`.
- **Report the task**:
  run the packet's `REPORT_COMMAND` only after every required draft and the
  manifest exist. `REPORT_COMMAND` takes `RUN_DIR`, never `DRAFT_WRITE_ROOT`.
- **Repair when requested**:
  if reporting prints `WORKER_RUNTIME_REPAIR_REQUIRED[...]`, follow the
  printed repair constraints, edit only allowed paths, and rerun the printed
  `RUN_DIR` report command.
- **Block the task**:
  run the packet's `BLOCK_COMMAND` with the exact reason.
- **Do not prepare**:
  never call `morpheus_run_task.sh prepare`; the runtime bootstraps the task
  before sending the packet.
- **Run local Python diagnosis when needed**:
  `bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<DRAFT_WRITE_ROOT>" --module unittest -- tests/test_main.py`
  uses `/home/alik/workspace/clawspace/venv-claw` without shell activation; its
  output is not DONE evidence, so final acceptance still requires
  `REPORT_COMMAND`.
