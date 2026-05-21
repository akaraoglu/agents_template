# .agents

This folder contains the working documents that guide Codex in this repository.

## Layout
- `capabilities/`: tool usage, boundaries, and coding standards
- `skills/`: repeatable workflows for common engineering tasks
- `playbooks/`: task recipes for bug fixes, features, and incidents
- `memory/`: durable lessons, decisions, and changelog entries
- `templates/`: reusable writing templates for PRs, triage, and reports

## Boundary
- `.agents/` is Codex-only.
- The live crew prompts, runtime, and shared crew rules live under `claw_agents_team/`.

## Maintenance
- Update these files when repo norms change.
- Prefer the smallest document that captures the lesson.
- Keep entries concise and action-oriented.
