# Local Codex Adapter Guide

`./.agents/scripts/spawn-subagent.sh` is the only supported live worker boundary when invoked from the guaranteed CodexTeam base folder.

The shell file is a thin compatibility wrapper over `codexteam_tools.spawn`. The Python implementation:

1. validates phase, team, task, attempt, role, profile, workspace, and paths;
2. injects role guidance into the initial draft handoff;
3. persists a private per-attempt Codex home, exact thread ID, model/provider/catalog, reasoning effort, and verbosity under ignored project runtime storage;
4. resumes feedback and finalization by exact session ID, never `--last`, while replaying the stored profile settings so global defaults cannot corrupt a local-model continuation;
5. enforces a process-group timeout while preserving resumable interrupted sessions;
6. keeps drafts and feedback out of `results/`;
7. persists JSONL, final-message, and stderr diagnostics for every turn;
8. validates and atomically persists one deterministic result v1 JSON after acceptance.

When the launcher is called by a Project Lead already contained in Codex `workspace-write`, local-profile worker turns add `--trust-parent-sandbox`. The worker skips a second sandbox namespace but remains contained by its parent. The launcher rejects authenticated OpenAI profiles in this mode, and the option must not be used from an ordinary host terminal.

Use `--dry-run` before every new profile, workspace layout, or orchestration change. Conversation text is review material, not trusted state; only a schema-valid final result and independent verification may advance project state.
