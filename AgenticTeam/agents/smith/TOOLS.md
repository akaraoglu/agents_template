# Tools — Smith

## Scripts (read allowed, NOT exec — use mm_post.sh via exec only for posting)

All scripts live in `/home/alik/workspace/clawspace/bin/`.


```
exec: bash /home/alik/workspace/clawspace/bin/mm_post.sh smith "<message>"
```

## sessions_send to Niaobe

⚠️ PATH RULE: Always send the full exact path. The `/clawspace/` segment is mandatory — never drop it.

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "New project. Folder: /home/alik/workspace/clawspace/projects/active/<folder_id>. Read PROJECT.md + SPEC.md + STATE.md. Run Design→Build→Verify in order. Report DONE or BLOCKED when complete."
}
```

## sessions_send to Neo (DONE report)

```json
{
  "sessionKey": "agent:neo:main",
  "message": "Project [<folder_id>] is DONE. DONE.md is ready at <folder>/DONE.md."
}
```

## sessions_send to Neo (BLOCKED escalation)

```json
{
  "sessionKey": "agent:neo:main",
  "message": "BLOCKED: Project [<folder_id>] failed twice. Last error: <reason>. STATE.md updated. Needs Master intervention."
}
```

## STATE.md schema

```markdown
# STATE — <Project ID>

phase: PLANNING | IN_PROGRESS | DONE | BLOCKED
waiting_for: niaobe | none
blocked_count: 0
blocked_reason: none

## Milestones
- [ ] Design (Architect)
- [ ] Build (Morpheus)
- [ ] Verify (Oracle)

## Log
- <timestamp>: received from Neo
- <timestamp>: delegated to Niaobe
```
