# .agents

This folder contains reusable working documents that guide Codex in this repository.

## Layout
- `capabilities/`: tool usage, boundaries, and coding standards
- `skills/`: repeatable workflows for common engineering tasks
- `playbooks/`: task recipes for bug fixes, features, and incidents
- `memory/`: durable lessons, decisions, and changelog entries
- `templates/`: reusable writing templates for PRs, triage, and reports

## Boundary
- `.agents/` is Codex-only.
- Keep project-specific runtime, deployment, and application behavior outside this folder unless it is explicitly agent guidance.
- Do not store local model catalogs, machine-specific configuration, credentials, or generated environment files here.

## Maintenance
- Update these files when repo norms change.
- Prefer the smallest document that captures the lesson.
- Keep entries concise and action-oriented.
