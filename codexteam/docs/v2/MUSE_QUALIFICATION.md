# Muse Glimmer Qualification

Status: `QUALIFIED` again on 2026-08-11 after upgrading to Ollama `0.32.9`.
All exact metadata, four direct Ollama, and three minimal OpenCode checks passed
in one invocation with no retries or fallback. This result permits, but does not
itself pass, the full adaptive canary.

The gate pins `muse-glimmer:30b` at digest
`de878ce33ad81d060001db1469a02eebe4d86f0ad58cfe52dc062fdcbe4464c1`.
Model-free checks run first and require the Ollama family, 131072 context, and
completion/tools/thinking/vision capabilities, plus OpenCode `1.18.16` and the
effective schema-valid Muse model metadata.

Run a model-free preview:

```bash
./scripts/v2/codexteam.py qualify-muse --opencode --dry-run --workspace /absolute/empty/path --json
```

Run only the four direct Ollama checks:

```bash
./scripts/v2/codexteam.py qualify-muse --direct-only --workspace /absolute/empty/path --timeout 600 --json
```

Run the complete qualification once:

```bash
./scripts/v2/codexteam.py qualify-muse --opencode --workspace /absolute/empty/path --timeout 600 --json
```

Direct checks issue exactly one request each with no retries or fallback:

- text uses `max_tokens=512` and requires exact `READY` plus `stop`;
- JSON uses `max_tokens=1024` and requires exact `{"status":"READY"}`;
- thinking uses `max_tokens=512` and requires nonempty reasoning, nonempty
  `READY` content, and `stop`;
- tool calling uses `max_tokens=2048` and requires exactly
  `get_magic_number` with JSON arguments `{"seed":7}` and `tool_calls` finish.

The OpenCode checks use private product/runtime state and pinned config. They
require a tool-free strict `SemanticResponse`, a read-only README session, and a
writable session that creates only `src/qualified.txt`, followed by a read-only
candidate on the exact session. The manifest audit requires exact content
`QUALIFIED\n` and no other product change.

The result is written to `<workspace>/qualification-result.json`. A gate is
`QUALIFIED` only when every required selected check passes. `DRY_RUN` is not a
qualification. On failure the workspace and bounded private evidence paths are
preserved. Reasoning text is never copied into the result; only its character
count and SHA-256 digest are reported.

The post-upgrade successful result is preserved at
`/tmp/opencode/codexteam-v2-muse-qualification-ollama-0329/qualification-result.json`.
