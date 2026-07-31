# Troubleshooting

## Profile Not Found

Confirm `$CODEX_HOME/<profile>.config.toml` or `~/.codex/<profile>.config.toml` exists. Established execution roles default to `qwen36-27b`; Feature Planner defaults to `gpt54-mini` and accepts an explicit `qwen36-27b` local override. `gemma4-26b` is an optional secondary profile.

## Result Is Partial

Inspect `output.stdout_tail`, `output.stderr_tail`, and `errors` in the saved result. The worker may have returned malformed JSON, wrong scope fields, copied template content, or no evidence.

## Turn Has No Final Message

Use the launcher-reported `<turn>.stderr.txt` and adjacent `<turn>.jsonl` files. If `session.json` contains the exact thread ID, send focused feedback with the same team, task, attempt, role, profile, and workspace. Do not start a new attempt merely because one turn ended without a message.

## Resume Uses the Wrong Model or Reasoning Level

Current sessions persist and replay model, provider, model catalog, reasoning effort, and verbosity. If older session metadata lacks those fields, verify the intended profile before continuing. Never replace exact-session resume with `--last`.

## Nested Worker Cannot Initialize, Use Bwrap, or Reach Ollama

If a worker launched by an already-sandboxed Project Lead reports an app-server read-only error or cannot create a `bwrap` namespace, read only the printed stderr and session record. Do not add `/tmp`, mirror the project, search global Codex history, or repeat equivalent attempts.

Follow `.agents/playbooks/nested-worker-sandbox.md`. Preflight `http://127.0.0.1:11434/api/version` from the same execution surface. If reachable there, preserve the failed attempt and use one intentionally configured local attempt with `--trust-parent-sandbox` on every turn. The flag skips the redundant worker namespace; it does not restore host loopback hidden by the parent sandbox.

If the endpoint fails inside the parent but succeeds on the host, run the launcher from an approved host-level execution surface without `--trust-parent-sandbox`. Keep that route on feedback and final turns. A result-free attempt may change IDs when switching routes because the execution configuration changed materially; a transient outage on the same route is not a reason for a new attempt. `--dry-run` does not contact the model.

Authenticated OpenAI workers are not supported through this nested subprocess route because their credential-bearing Codex home is outside the parent writable root. Run them from the host-level E2E surface instead. Never use `--trust-parent-sandbox` from an ordinary terminal.

MCP is not required to spawn a local worker. Check `mcp_allowed_servers`, `mcp_effective_servers`, and `mcp_missing_servers` in the dry-run, `session.json`, or `turn-state.json`; a global `codex mcp list` alone does not prove role access. Authenticated OpenAI workers execute against the source Codex home, while local workers use the attempt-private copy, so the launcher enforces the same role allowlist through per-process `-c mcp_servers.<name>.enabled=<bool>` overrides.

If a non-interactive Playwright navigation reports `user cancelled MCP tool call`, verify that the server keeps its narrow `enabled_tools` list and `browser_navigate` has `approval_mode = "approve"`. Do not switch the whole server to unconditional approval. If Leader GitHub reads fail, verify `gh auth status`, credential inheritance, and one live read before starting another GitHub-dependent Lead attempt; never store a token in repository or role files.

## Prompt Text Executes in the Shell

Put Markdown-rich or metacharacter-rich instructions in a file and pass `--prompt-file`. Do not embed backticks or command substitutions in a double-quoted `--prompt` shell argument.

## Closure Cannot Find Evidence

Every `file_changes` path and `evidence[].artifact_ref` in a completed result must exist inside the project root. Correct a malformed final response through the same resumable attempt. Start a new attempt only for an intentional transfer, irrecoverable session loss, material scope change, or explicit abandonment; never invent missing evidence.

## Verification Command Fails

Run the same argument-array command from the project root. `close-loop.sh` leaves task state unchanged on failure and prints the captured output tail.

## Local Model Hangs

Use the repository playbook `.agents/playbooks/add-ollama-model-to-codex.md` to verify profile names, context-window alignment, KV-cache configuration, and GPU residency.
