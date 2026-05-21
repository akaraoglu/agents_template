# Tools - Oracle

## Return contract to Niaobe

Use only JSON envelopes keyed by `project_id` and `task_id`.

- Never send plain text PASS/FAIL messages.
- Never include `project_path` or absolute project file paths in the envelope.

## Run tests

```text
exec: bash /home/alik/workspace/clawspace/bin/resolve_project.sh "<PROJECT_ID>"
exec: bash /home/alik/workspace/clawspace/bin/project_exec.sh "<PROJECT_ID>" oracle <project-native verification command>
```

Capture the FULL `STDOUT_BEGIN` / `STDERR_BEGIN` output. Every line matters.

## File operations

```text
exec: bash /home/alik/workspace/clawspace/bin/resolve_project.sh "<PROJECT_ID>"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "CURRENT_TASK.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/architecture/<TASK_ID>.md"
write: /home/alik/workspace/clawspace/workspaces/oracle/drafts/<PROJECT_ID>/<TASK_ID>_REPORT.md
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/validation/<TASK_ID>_REPORT.md" --source-file "/home/alik/workspace/clawspace/workspaces/oracle/drafts/<PROJECT_ID>/<TASK_ID>_REPORT.md" --action oracle_project_write
exec: bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" VERIFY "management/validation/<TASK_ID>_REPORT.md" --action oracle-write --contains "<TASK_ID>"
```

Treat any rooted helper result with `OUTCOME_JSON.status != "OK"` as BLOCKED or FAIL, not success.
Never use heredocs, pipes, or shell redirection with project file writes.

## sessions_send to Niaobe (PASS)

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "{\"project_id\":\"<PROJECT_ID>\",\"task_id\":\"<TASK_ID>\",\"from\":\"oracle\",\"to\":\"niaobe\",\"phase\":\"VERIFY\",\"instructions\":\"PASS: task verification complete. Evidence: <brief summary>.\"}"
}
```

## sessions_send to Niaobe (FAIL)

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "{\"project_id\":\"<PROJECT_ID>\",\"task_id\":\"<TASK_ID>\",\"from\":\"oracle\",\"to\":\"niaobe\",\"phase\":\"VERIFY\",\"instructions\":\"FAIL: <summary of failed criteria and tests>.\"}"
}
```
