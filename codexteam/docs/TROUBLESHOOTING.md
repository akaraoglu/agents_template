# Troubleshooting

## Profile Not Found

Run `inspect-execution-catalog.py profile --backend <backend> --profile
<profile>`. Profiles must be curated, qualified, and host-available.

For OpenCode, select a curated profile and explicit `provider_default` reasoning.

## Result Is Partial

Inspect `output.stdout_tail`, `output.stderr_tail`, and `errors` in the saved result. The worker may have returned malformed JSON, wrong scope fields, copied template content, or no evidence.

## Artifact Report Is Correction Needed

Inspect `results/reports/<TASK>-<attempt>.json`. Correct missing required fields,
invalid JSON, unsafe evidence paths, or non-string list entries with
`--feedback-mode format-only`; terminal prose is not part of the contract.

## Execution Specification Mismatch

New attempts pin `execution-spec.json` before worker execution. A digest,
identity, backend, model, reasoning, permission, guidance, or gate-routing
mismatch fails before feedback/final execution. Preserve the attempt for audit;
do not edit or regenerate the sidecar. A material capability change requires a
new attempt. Pre-cutover active attempts with no current execution specification
must be drained or abandoned and are not backfilled.

## Turn Has No Final Message

Use the launcher-reported diagnostics. Feedback keeps team/task/attempt/role and
workspace but omits backend/profile/reasoning/AgentSpec selectors.

OpenCode records the same opaque ID as both `thread_id` and
`opencode_session_id`; continuation derives backend from ExecutionSpec.

Do not assume the OpenCode SDK fixes local-model finalization. Both Ornith and Qwen failed the structured-output capability gate with `StructuredOutputError`; Qwen produced zero structured results in three exact-session trials. SDK finalization remains disabled. Inspect each OpenCode `<turn>.metrics.json` for `model_steps`, `backend_usage`, and `context_bytes` when profiling repeated calls or guidance reads.

## Resume Uses the Wrong Model or Reasoning Level

ExecutionSpec persists and validates backend, model, profile, reasoning mapping,
and backend material. Pre-cutover attempts are not resumed.

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
