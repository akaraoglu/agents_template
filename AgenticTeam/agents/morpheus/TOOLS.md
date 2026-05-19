# Tools — Morpheus

## sessions_spawn (your primary tool)

Spawn each sub-agent with a clear, complete prompt. Always include absolute file paths.

```json
{
  "prompt": "Read SPEC_DETAILED.md at <absolute_path>. Write TASKS.md at <folder>/TASKS.md listing every implementation task in order. Each task: file path, function/class to write, test to add. Be exhaustive. No placeholders.",
  "model": "ollama/gemma4:26b"
}
```

## sessions_send to Niaobe (DONE)

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "DONE: Build complete. All tests pass. Files created: <list of files>. Test output: <summary>."
}
```

## sessions_send to Niaobe (BLOCKED)

```json
{
  "sessionKey": "agent:niaobe:main",
  "message": "BLOCKED: Build failed after 3 fix cycles. Project: <folder_id>. Last error: <exact error>."
}
```

## Key file paths

```
<folder>/design/SPEC_DETAILED.md   ← read this first
<folder>/TASKS.md                  ← Planner writes this
<folder>/tests/                    ← Tester writes tests here
<folder>/TASKS.md                  ← verify exists before spawning Implementer
```
