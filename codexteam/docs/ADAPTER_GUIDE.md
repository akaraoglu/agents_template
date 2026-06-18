# Adapter Guide

Adapters connect worker execution surfaces to the CodexTeam core.

## MVP Adapters

- `dry_run`: exercises orchestration without launching workers.
- `manual`: records provided human output.
- `codex_exec`: invokes `codexteam/scripts/codex_local_run.py` through structured arguments.

The local Codex adapter requires an approval id and a policy decision before process execution.

