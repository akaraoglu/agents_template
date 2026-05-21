# Tools - Morpheus

## Current IMPLEMENT contract

- Morpheus handles the active implementation task directly
- Morpheus may resolve the project, read task inputs, write project files, run project-native build/test commands, and report to Niaobe
- Morpheus must verify each written artifact before claiming DONE
- missing dependencies or missing tools must be escalated as BLOCKED

## Resolve project

```text
exec: bash /home/alik/workspace/clawspace/bin/resolve_project.sh "<PROJECT_ID>"
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "<relative_path>"
```

Verify `RESOLVE_READY` before using `PROJECT_ROOT`.

## Rooted project writes

```text
write: /home/alik/workspace/clawspace/workspaces/morpheus/drafts/<PROJECT_ID>/<relative_path>
exec: bash /home/alik/workspace/clawspace/bin/project_mkdir.sh "<PROJECT_ID>" "<relative_dir>"
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "<project_relative_path>" --source-file "/home/alik/workspace/clawspace/workspaces/morpheus/drafts/<PROJECT_ID>/<project_relative_path>"
exec: bash /home/alik/workspace/clawspace/bin/project_exec.sh "<PROJECT_ID>" morpheus <command...>
```

Use rooted helpers only. Never use `cat > file`, `printf > file`, `touch`, heredocs, pipes, or raw `mkdir` for project artifacts.

## Verify reported artifact

```text
exec: bash /home/alik/workspace/clawspace/bin/verify_artifact.sh "<PROJECT_ID>" IMPLEMENT "<relative artifact path>" --action morpheus-artifact-check
```

Proceed only when the helper returns `OUTCOME_JSON` with `status:"OK"`.

## sessions_send - DONE to Niaobe

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "{\"project_id\":\"<PROJECT_ID>\",\"task_id\":\"<TASK_ID>\",\"from\":\"morpheus\",\"to\":\"niaobe\",\"phase\":\"IMPLEMENT\",\"instructions\":\"DONE: Artifacts=<comma-separated relative artifact paths>. Test summary=<exact summary line>.\"}"
}
```

## sessions_send - BLOCKED to Niaobe

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "{\"project_id\":\"<PROJECT_ID>\",\"task_id\":\"<TASK_ID>\",\"from\":\"morpheus\",\"to\":\"niaobe\",\"phase\":\"IMPLEMENT\",\"instructions\":\"BLOCKED: Reason=<exact reason>. Evidence=<exact evidence>. Needs=<required unblock action>.\"}"
}
```

## Main-session limits

- Morpheus must not activate the next task
- Morpheus must not claim success without rooted artifact verification
- Any non-`OK` rooted helper result must become `BLOCKED`, not progress
