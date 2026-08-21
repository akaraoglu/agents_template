# Worker Adapter Guide

`./.agents/scripts/spawn-subagent.sh` is the supported live worker boundary when invoked from the guaranteed CodexTeam base folder. New drafts require explicit curated backend, backend-scoped profile, and reasoning selection.

The shell file is a thin compatibility wrapper over `codexteam_tools.spawn`. The Python implementation:

1. validates phase, team, task, attempt, role, profile, workspace, and paths;
2. injects role guidance into the initial draft handoff;
3. persists a private per-attempt Codex home, exact thread ID, model/provider/catalog, reasoning effort, and verbosity under ignored project runtime storage;
4. resumes feedback by exact session ID, never `--last`; new semantic attempts finalize locally, while legacy formats resume the provider;
5. enforces a process-group timeout while preserving resumable interrupted sessions;
6. keeps drafts and feedback out of `results/`;
7. persists JSONL, final-message, and stderr diagnostics for every turn;
8. validates and atomically persists one deterministic result current JSON after acceptance.

Attempts use `artifact-report-v1`. Workers write the launcher-derived report
under `results/reports/`; terminal output is diagnostic. After acceptance the
launcher seals identity, Lead-selected status, accepted file changes, process
metadata, and timestamps without another backend turn. Attempts without the
current artifact format pin are historical and are not resumed.

Direct-context OpenCode attempts are stricter: canonical handoffs declare a
bounded report path, exact source line ranges, and fixed verification argv.
OpenCode receives the source excerpts in its prompt with `read`, `grep`, `glob`,
and `bash` denied and edits restricted to literal role-allowed task files. The
launcher ignores terminal content, requires `Disposition: ready_for_review` in
the report, validates the change manifest, and runs only configured gate commands
inside a networkless read-only bubblewrap boundary before creating the semantic payload.

Every new draft also resolves an `execution-spec` in memory. Dry-run displays
it without mutation; live draft writes it once before launching the worker.
Feedback and final verify the original digest and reject backend, role, profile,
reasoning, permission, or route drift. Attempts without the specification are
not resumed. The record contains the handoff path and
SHA-256 only, never handoff or feedback text.

## Disabled OpenCode Backend

OpenCode implementation, qualification evidence, and historical attempt readers
are retained, but supported commands reject new OpenCode drafts and feedback.
Codex is the only enabled execution backend. The details below are historical
runtime documentation and must not be used as launch instructions.

Historical profiles include Qwen 3.8, Qwen 3.6, Muse Glimmer, and Ornith. Qwen
3.8 preserved its native renderer/parser and pinned `num_ctx=262144`; Muse pinned
`num_ctx=131072`, temperature `0.6`, top-k `20`, and top-p `0.95`. `opencode`
was required on `PATH`, Ollama exposed the selected model, and one OpenCode
version remained installed for the complete attempt. The launcher created an attempt-private OpenCode home,
XDG state, provider configuration containing only the selected model and its
curated context/output limits, primary role agent, workspace baseline, and exact
OpenCode session. It pins project `AGENTS.md`, role policy, selected guidance,
OpenCode version, model, and configuration digest. Feedback turns use
`--session <exact-id>`; they never use `--continue` or `--fork`. New semantic
attempts finalize locally; legacy pinned formats retain exact-session provider
finalization.

The historical `qwen38-27b-context` profile required explicit `low`, `medium`, or
`high` reasoning. Its attempt-private config loaded exactly one CodexTeam plugin whose source path,
options, and SHA-256 are covered by the backend config digest. The plugin applies
that reasoning effort on every model request, archives hook-visible or
provider-referenced full tool output as mode-`0600` files, and projects at most a
6 KB tool-result body into the next model request. Bash failures retain bounded
failure lines and tail context with an instruction to inspect source before a
root-cause conclusion; grep/glob results retain match count, matching paths, and
representative matches; other large results use UTF-8-safe head and tail excerpts
with an explicit omitted-byte marker. A manifest records call ID, tool, byte
count, digest, archive filename, and compaction status. Persisted OpenCode tool
parts remain unchanged. This ignored archive is not an OS confidentiality
boundary from a same-user shell-capable worker.

OpenCode JSONL provides transport events, not a valid `result` guarantee. The launcher validates semantic drafts externally, preserves baseline-derived net file changes, and seals accepted results deterministically. Legacy pinned formats retain the externally validated textual final path.

## Additional Codex Profiles

The curated Codex backend also exposes optional local profiles
`qwen38-27b`, `muse-glimmer`, and `gemma4-26b`. They use the existing
`ollama_local` provider and Codex's normal workspace sandbox. Their dated smoke
evidence is recorded in `docs/CODEX_LOCAL_PROFILE_QUALIFICATION.md`. Installed
`ornith35b`, `gpt56-luna`, and `gpt56-terra` are not curated until a live
same-session smoke succeeds.

OpenCode SDK JSON-schema finalization is not enabled. Exact-session capability checks returned `StructuredOutputError`; deterministic sealing avoids that unsupported provider capability for new attempts without a retry or fallback protocol.

OpenCode metrics sidecars add observational `context_bytes`, bounded per-step token records, first/last/max step input, tool counts, and per-tool UTF-8 text-output bytes. `worker_prompt_bytes` is the exact CodexTeam stdin payload. Other byte fields are labeled local components and may overlap; they are not estimates of the complete provider prompt and are never converted into estimated tokens.

A matched three-run Reviewer experiment compared the default `verification.md` plus `coding-standards.md` bundle with `verification.md` alone on a read-only artifact task. The reduced bundle improved median input, tool calls, and duration, but its mean input barely changed because of a 166K-token outlier, and only one of three reduced-bundle drafts gave a clear correct PASS. Role defaults therefore remain unchanged; use explicit `--skill-file` only for approved experiments.

A separate matched three-run deterministic Reviewer comparison kept the default guidance fixed and compared models. Tuned Qwen achieved two strict clean passes versus Ornith's zero, with median input 10,088 versus 11,897 tokens, median output 686 versus 1,105 tokens, and one versus three median tool calls. This evidence makes Qwen the preferred OpenCode Reviewer candidate for further bounded evaluation; it does not change role manifests or the default Codex backend.

This backend intentionally disables inherited OpenCode configuration, MCP, LSP, plugins, external skills, nested agents, project config discovery, and cloud providers. `--reasoning-effort`, `--trust-parent-sandbox`, and `--run-guard` fail rather than being ignored. OpenCode permissions are not an OS sandbox; shell-capable workers still require workspace auditing, Lead review, and independent verification.

The backend has passed disposable same-session correction and result-validation canaries. Treat it as operational but not yet proven token-efficient or first-pass reliable.

Qwen 3.8 passed exact-file edit/assertion, same-session correction, artifact
JSON, native function-call, clean-stop, and 262K 100%-GPU checks before
OpenCode execution was disabled. Historical handoffs pin `small`
(600-second) or `complex` (1200-second) execution. Complex work uses accepted
same-session checkpoints before deterministic finalization.

For the enabled Codex backend, an already-contained Project Lead may use `--trust-parent-sandbox` after the documented same-surface Ollama preflight.

Use `--dry-run` before every new profile, workspace layout, or orchestration change. Conversation text is review material, not trusted state; only a schema-valid final result and independent verification may advance project state.
