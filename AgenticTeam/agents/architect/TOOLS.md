# Tools - Architect

## Return contract to Niaobe

Use only JSON envelopes keyed by `project_id`.

- Never send plain text DONE/BLOCKED messages.
- Never include `project_path` or absolute project file paths in the envelope.

## File operations

```text
exec: bash /home/alik/workspace/clawspace/bin/resolve_project.sh "<PROJECT_ID>"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "CURRENT_TASK.md"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "management/tasks/<TASK_ID>.md"
exec: bash /home/alik/workspace/clawspace/bin/project_mkdir.sh "<PROJECT_ID>" "management/architecture"
write: /home/alik/workspace/clawspace/workspaces/architect/drafts/<PROJECT_ID>/<TASK_ID>.md
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "management/architecture/<TASK_ID>.md" --source-file "/home/alik/workspace/clawspace/workspaces/architect/drafts/<PROJECT_ID>/<TASK_ID>.md" --action architect_project_write
exec: bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" DESIGN "management/architecture/<TASK_ID>.md" --action architect-write --contains "<TASK_ID>"
```

Treat any rooted helper result with `OUTCOME_JSON.status != "OK"` as BLOCKED.
Never use heredocs, pipes, or shell redirection with project file writes.

## sessions_send to Niaobe (DONE)

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "{\"project_id\":\"<PROJECT_ID>\",\"task_id\":\"<TASK_ID>\",\"from\":\"architect\",\"to\":\"niaobe\",\"phase\":\"DESIGN\",\"instructions\":\"DONE: management/architecture/<TASK_ID>.md written.\"}"
}
```

## sessions_send to Niaobe (BLOCKED)

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "{\"project_id\":\"<PROJECT_ID>\",\"task_id\":\"<TASK_ID>\",\"from\":\"architect\",\"to\":\"niaobe\",\"phase\":\"DESIGN\",\"instructions\":\"BLOCKED: Cannot complete task design. Reason: <exact reason>.\"}"
}
```
