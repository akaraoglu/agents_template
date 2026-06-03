# Tools - Neo

## Project creation

```text
exec: bash /home/alik/workspace/clawspace/bin/new_project.sh "<Project Title>"
```

Capture `PROJECT_ID` from the `Project ID:` line in the output. `new_project.sh`
must run before any rooted project helper.

## Rooted project writes

```text
write: /home/alik/workspace/clawspace/workspaces/neo/draft_PROJECT.md
exec: bash /home/alik/workspace/clawspace/bin/project_write.sh "<PROJECT_ID>" "PROJECT.md" --source-file "/home/alik/workspace/clawspace/workspaces/neo/draft_PROJECT.md" --action neo_project_write
exec: bash /home/alik/workspace/clawspace/bin/project_read.sh "<PROJECT_ID>" "PROJECT.md"
```

Use rooted helpers only. Do not send project paths to other agents.

## Handoff and notification

```text
exec: bash /home/alik/workspace/clawspace/bin/mm_post.sh neo "🚀 Neo: [<PROJECT_ID>] created and seeded. Handing to Smith."
exec: bash /home/alik/workspace/clawspace/bin/handoff.sh neo smith "<PROJECT_ID>" "Read PROJECT.md and start sequential planning." HANDOFF
```

`sessions_send` to Smith must use the exact `ENVELOPE:` value returned by
`handoff.sh`.

## sessions_send to Smith

```json
{
  "sessionKey": "agent:smith:main",
  "message": "<ENVELOPE from handoff.sh>"
}
```

## Troubleshooting and Diagnostics

```text
exec: openclaw status
exec: openclaw logs --plain --limit 200
exec: bash /home/alik/workspace/agent_template_new/AgenticTeam/scripts/team_status.sh
```

## Python diagnostics

```text
exec: bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<runtime-or-workspace-directory>" --module unittest -- tests/test_main.py
exec: bash /home/alik/workspace/clawspace/bin/python_claw.sh --cwd "<runtime-or-workspace-directory>" --syntax-check "src/main.py"
```

`python_claw.sh` uses `/home/alik/workspace/clawspace/venv-claw` without shell
activation. Use it only for local Python diagnosis; role runtime helpers remain
the authority for project lifecycle and final evidence.
