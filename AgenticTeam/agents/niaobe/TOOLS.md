# Tools — Niaobe

## ⚠️ PATH RULE: Always use the full exact path — e.g. `/home/alik/workspace/clawspace/projects/active/<folder_id>`. Never drop `/clawspace/`.

## sessions_send to Architect

```json
{
  "sessionKey": "agent:architect:main",
  "message": "Design task. Project folder: /home/alik/workspace/clawspace/projects/active/<folder_id>. Read PROJECT.md and SPEC.md. Create design/SPEC_DETAILED.md with full system design. Report DONE or BLOCKED to agent:niaobe:main when complete."
}
```

## sessions_send to Morpheus

```json
{
  "sessionKey": "agent:morpheus:main",
  "message": "Build task. Project folder: /home/alik/workspace/clawspace/projects/active/<folder_id>. Design file: /home/alik/workspace/clawspace/projects/active/<folder_id>/design/SPEC_DETAILED.md. Implement per design. Run tests. Report DONE or BLOCKED to agent:niaobe:main when complete."
}
```

## sessions_send to Oracle

```json
{
  "sessionKey": "agent:oracle:main",
  "message": "Validation task. Project folder: /home/alik/workspace/clawspace/projects/active/<folder_id>. Run pytest. Validate ALL acceptance criteria from PROJECT.md. Write VALIDATION.md. Report PASS or FAIL to agent:niaobe:main."
}
```

## sessions_send to Smith (DONE)

```json
{
  "sessionKey": "agent:smith:main",
  "message": "DONE: Project [<folder_id>] complete. All phases passed. VALIDATION.md at <folder>/VALIDATION.md."
}
```

## sessions_send to Smith (BLOCKED)

```json
{
  "sessionKey": "agent:smith:main",
  "message": "BLOCKED: Project [<folder_id>] failed after 3 cycles. Phase: <phase>. Reason: <reason>. STATE.md updated."
}
```

## STATE.md phase values

`DESIGN` → `BUILD` → `VERIFY` → `DONE`
`waiting_for`: `architect` | `morpheus` | `oracle` | `none`
