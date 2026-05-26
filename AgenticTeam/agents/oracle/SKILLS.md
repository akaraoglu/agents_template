# SKILLS.md - Oracle

- **Run the verification runtime**:
  `bash /home/alik/workspace/clawspace/bin/oracle_run_task.sh verify '<JSON envelope>'`
- **Runtime ownership**:
  the runtime resolves the project, reads canonical inputs, verifies required
  artifacts, runs `project_exec.sh`, writes and imports
  `management/validation/<TASK_ID>_REPORT.md`, verifies the report, and sends
  PASS or FAIL to Niaobe.
- **Sequence rule**:
  do not stop after a test result and do not run lower-level project helpers
  directly for VERIFY completion.
- **Report shape**:
  after the runtime exits, reply `Validation handled. Runtime notified Niaobe.`
  then `REPLY_SKIP`.
