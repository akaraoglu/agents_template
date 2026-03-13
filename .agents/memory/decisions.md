# Decisions Log

Record durable repo or process decisions here, especially behavior or tooling updates that should remain true over time.

## Entry Template
- Date:
- Decision:
- Context:
- Consequences:
- Status:

## Entries

- Date: 2026-03-12
- Decision: Keep `AGENTS.md` short and store detailed operating guidance under `.agents/`.
- Context: The older `AGENTS.md` combined workflow, environment, style, and logging rules in one file.
- Consequences: Repo-wide guidance is easier to maintain and each topic has a single clear home.
- Status: Accepted

- Date: 2026-03-12
- Decision: Use `.agents/memory/decisions.md` for durable behavior and tooling updates instead of a separate `AGENTS_update.md`.
- Context: The previous workflow proposed a second top-level file for ongoing agent updates.
- Consequences: Persistent updates stay inside the existing memory structure and avoid duplicate sources of truth.
- Status: Accepted

- Date: 2026-03-13
- Decision: The OpenClaw template will use `PROJECT.md` as the single project-specific context file and will generate `openclaw.json` locally from `openclaw.template.json`.
- Context: The previous OpenClaw folder contained machine-specific paths, committed runtime state, and project-specific assumptions that made it unsuitable as a reusable template.
- Consequences: The OpenClaw template is now portable across projects while still supporting local Docker-backed execution that needs absolute config paths at runtime.
- Status: Accepted

- Date: 2026-03-13
- Decision: The local OpenClaw team will use a `manager` role as the orchestrator, with `run_team.sh` coordinating manager, planner, coder, and tester externally.
- Context: The desired team shape includes a dedicated orchestrator, but embedded local mode may not expose direct in-agent delegation tools consistently.
- Consequences: The template has a stable manager-led workflow now, while remaining compatible with current local execution limits.
- Status: Accepted
