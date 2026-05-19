# Tools — Architect

## File operations

```
read_file: <folder>/PROJECT.md
read_file: <folder>/SPEC.md
exec: mkdir -p <folder>/design
write_file: <folder>/design/SPEC_DETAILED.md
read_file: <folder>/design/SPEC_DETAILED.md   ← always self-check after writing
```

## sessions_send to Niaobe (DONE)

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "DONE: Design complete. SPEC_DETAILED.md written at <absolute_path>/design/SPEC_DETAILED.md."
}
```

## sessions_send to Niaobe (BLOCKED)

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "BLOCKED: Cannot complete design. Reason: <exact reason>. Project: <folder_id>."
}
```
