# Nested Worker Sandbox Recovery

## Purpose

Recover a CodexTeam worker launched by a Project Lead that is itself already running inside a Codex `workspace-write` sandbox.

## When To Use

Use before starting a local worker from an already-sandboxed Project Lead, or when that worker reports any of:

- `failed to initialize in-process app-server client: Read-only file system`; or
- `bwrap: No permissions to create new namespace`; or
- a connection failure to the local Ollama endpoint.

## Diagnosis

Read the single printed worker stderr file and its adjacent session record, if present. Do not search global Codex history, inspect launcher source, add `/tmp`, or mirror the project.

- An authenticated OpenAI worker reuses the source Codex home for credentials. That home is read-only inside the parent sandbox, so this nested route is unsupported.
- A local worker uses a private project-local Codex home, but its default `workspace-write` mode can try to create a redundant nested `bwrap` sandbox.
- `--trust-parent-sandbox` avoids that redundant filesystem namespace, but it does not restore host loopback or network access hidden by the parent sandbox.
- A successful `--dry-run` proves command construction only. It does not contact Ollama or prove that the selected execution surface can reach the model.

## Execution-Surface Preflight

Before the first draft, test the local model endpoint from the same execution surface that will launch the worker:

```bash
curl -fsS http://127.0.0.1:11434/api/version
```

- If this succeeds inside the Project Lead sandbox, a local worker may use `--trust-parent-sandbox` to avoid redundant `bwrap` setup.
- If it fails there but succeeds from the host, the parent sandbox cannot reach host Ollama. Run the launcher from an approved host-level execution surface and omit `--trust-parent-sandbox` so the worker receives its normal sandbox.
- MCP is not required for local-worker spawning. `codex mcp list` from the global home does not prove the contents of an attempt-private Codex home; diagnose the exact home recorded for that attempt only when MCP startup appears in its named stderr.

## Recovery Route A: Reachable From The Parent Sandbox

Keep the exact project path and preserve failed attempts as result-free diagnostics. Start one intentional new attempt with a local model profile and `--trust-parent-sandbox`:

```bash
./.agents/scripts/spawn-subagent.sh \
  --phase draft --profile <local-profile> --reasoning-effort medium \
  --team <project-id> --task <task-id> --attempt <new-attempt> --role <role> \
  --workspace <exact-created-path> --timeout 300 \
  --prompt-file <exact-created-path>/management/tasks/<task-id>.md \
  --trust-parent-sandbox
```

This option skips only the redundant worker sandbox. The already-running Project Lead sandbox remains the filesystem boundary. Keep the flag identical on feedback and final turns for that attempt.

## Recovery Route B: Host Ollama Is Hidden From The Parent Sandbox

Run the same launcher command from an approved host-level execution surface, without `--trust-parent-sandbox`. Use that same host-level route for draft, feedback, and final so session scope remains stable. The worker's normal `workspace-write` sandbox remains enabled.

Changing from a nested trusted-parent route to a host-level normal-sandbox route is a material execution-configuration change. If the prior attempt produced no result, preserve its diagnostics and use one new attempt. Do not create a new attempt for an ordinary transient endpoint outage when the execution route has not changed.

## Safety Boundary

- Use `--trust-parent-sandbox` only from a Project Lead already contained by Codex `workspace-write` and only after the same-surface Ollama preflight succeeds.
- Use only a local profile. The launcher rejects authenticated OpenAI profiles in this mode.
- Never use the flag from an ordinary host terminal; the normal worker sandbox is required there.
- Do not copy `auth.json`, request broader filesystem access, or move the project to `/tmp`.

## Validation

- Draft status becomes `draft_ready` without the app-server, `bwrap`, or model-endpoint error.
- `session.json` records the selected `trust_parent_sandbox` value.
- Worker writes remain under the exact project root.
- Feedback and finalization resume the same thread, attempt, profile, role, workspace, and execution route.

## Stop Condition

If the same-surface preflight succeeds and one correctly configured local attempt still cannot start or use tools, record a genuine execution-surface blocker and stop. Do not repeat equivalent retries.

## Related Files

- `.agents/skills/subagent-orchestration.md`
- `.agents/capabilities/tools.md`
- `src/codexteam_tools/spawn.py`
- `docs/TROUBLESHOOTING.md`
