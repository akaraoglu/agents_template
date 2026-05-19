# Tools — Oracle

## Run tests

```
exec: cd <folder> && python -m pytest tests/ -v 2>&1
```
Capture the FULL output. Every line matters.

## File operations

```
read_file: <folder>/PROJECT.md          ← get acceptance criteria
read_file: <folder>/design/SPEC_DETAILED.md  ← understand what was built
write_file: <folder>/VALIDATION.md      ← your verdict
read_file: <folder>/VALIDATION.md       ← always self-check after writing
```

## sessions_send to Niaobe (PASS)

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "PASS: Project [<folder_id>] validated. All acceptance criteria met. X tests passed. VALIDATION.md at <path>."
}
```

## sessions_send to Niaobe (FAIL)

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "FAIL: Project [<folder_id>] failed validation. Failed criteria: <list>. Failed tests: <list>. VALIDATION.md at <path>."
}
```
