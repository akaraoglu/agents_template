# Worker Adapter Guide

`./.agents/scripts/spawn-subagent.sh` is the supported live worker boundary when invoked from the guaranteed CodexTeam base folder. It defaults to Codex and accepts an explicit OpenCode canary backend.

The shell file is a thin compatibility wrapper over `codexteam_tools.spawn`. The Python implementation:

1. validates phase, team, task, attempt, role, profile, workspace, and paths;
2. injects role guidance into the initial draft handoff;
3. persists a private per-attempt Codex home, exact thread ID, model/provider/catalog, reasoning effort, and verbosity under ignored project runtime storage;
4. resumes feedback and finalization by exact session ID, never `--last`, while replaying the stored profile settings so global defaults cannot corrupt a local-model continuation;
5. enforces a process-group timeout while preserving resumable interrupted sessions;
6. keeps drafts and feedback out of `results/`;
7. persists JSONL, final-message, and stderr diagnostics for every turn;
8. validates and atomically persists one deterministic result v1 JSON after acceptance.

## OpenCode Canary Backend

Use `--backend opencode --profile muse-glimmer` for `ollama/muse-glimmer:30b`, `--profile ornith35b` for `ollama/ornith:35b`, or `--profile qwen36-27b` for tuned `ollama/qwen3.6-27b:latest`. `opencode` must be on `PATH`, Ollama must expose the selected model, and the same OpenCode version must remain installed for the complete attempt. The launcher creates an attempt-private OpenCode home, XDG state, provider configuration containing only the selected model, primary role agent, workspace baseline, and exact OpenCode session. It pins project `AGENTS.md`, role policy, selected guidance, OpenCode version, model, and configuration digest. Feedback and final turns use `--session <exact-id>`; they never use `--continue` or `--fork`.

OpenCode JSONL provides transport events, not a valid `result-v1` guarantee. The launcher extracts text, validates the result externally, preserves baseline-derived net file changes, rejects undeclared or extra result paths, and keeps malformed finalization resumable for same-session feedback.

OpenCode SDK JSON-schema finalization is not enabled. Exact-session capability checks returned `StructuredOutputError` for Ornith and for all three Qwen trials; Qwen also failed with the normal tool-capable agent, so read-only final permissions were not the cause. The production adapter therefore keeps the proven textual final path and external validation; it does not silently fall back from an SDK path.

OpenCode metrics sidecars add observational `context_bytes`, bounded per-step token records, first/last/max step input, tool counts, and per-tool UTF-8 text-output bytes. `worker_prompt_bytes` is the exact CodexTeam stdin payload. Other byte fields are labeled local components and may overlap; they are not estimates of the complete provider prompt and are never converted into estimated tokens.

A matched three-run Reviewer experiment compared the default `verification.md` plus `coding-standards.md` bundle with `verification.md` alone on a read-only artifact task. The reduced bundle improved median input, tool calls, and duration, but its mean input barely changed because of a 166K-token outlier, and only one of three reduced-bundle drafts gave a clear correct PASS. Role defaults therefore remain unchanged; use explicit `--skill-file` only for approved experiments.

A separate matched three-run deterministic Reviewer comparison kept the default guidance fixed and compared models. Tuned Qwen achieved two strict clean passes versus Ornith's zero, with median input 10,088 versus 11,897 tokens, median output 686 versus 1,105 tokens, and one versus three median tool calls. This evidence makes Qwen the preferred OpenCode Reviewer candidate for further bounded evaluation; it does not change role manifests or the default Codex backend.

This backend intentionally disables inherited OpenCode configuration, MCP, LSP, plugins, external skills, nested agents, project config discovery, and cloud providers. `--reasoning-effort`, `--trust-parent-sandbox`, and `--run-guard` fail rather than being ignored. OpenCode permissions are not an OS sandbox; shell-capable workers still require workspace auditing, Lead review, and independent verification.

The backend has passed disposable same-session correction and result-validation canaries. Treat it as operational but not yet proven token-efficient or first-pass reliable.

For the default Codex backend, an already-contained Project Lead may use `--trust-parent-sandbox` after the documented same-surface Ollama preflight. OpenCode rejects that option and must use an approved host-level execution surface; its permissions and post-turn auditing are not an OS sandbox.

Use `--dry-run` before every new profile, workspace layout, or orchestration change. Conversation text is review material, not trusted state; only a schema-valid final result and independent verification may advance project state.
