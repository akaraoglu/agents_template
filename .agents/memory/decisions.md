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
