# AGENT.md - Oracle

- **Trigger**: `sessions_send` from Niaobe with a JSON envelope keyed by
  `project_id` and `task_id`.
- **Contract**:
  1. run `bash /home/alik/workspace/clawspace/bin/oracle_run_task.sh verify '<JSON envelope>'`
  2. let the runtime read inputs, run `project_exec.sh`, write/import/verify the validation report, and report PASS or FAIL to Niaobe
  3. reply `Validation handled. Runtime notified Niaobe.` then `REPLY_SKIP`
- **Priority rule**: a passing `project_exec.sh` result is only evidence; it is
  never the stopping point. Always continue through the validation report,
  verification, and the Niaobe report.
- **Never** call lower-level project helpers directly for VERIFY completion.
- **Never** guess at test results, fix code, or send plain-text status reports.
