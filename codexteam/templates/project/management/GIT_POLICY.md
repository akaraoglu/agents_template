# Local Git Policy

## Repository Boundary

The project is expected to be an exact standalone Git repository root. The Local Git Steward must refuse parent-repository fallback.

## Commit Boundaries

T001 names milestone or important-task boundaries. A code boundary becomes commit-ready only after current Development and Integration Gate records, Reviewer acceptance, synchronized project state, and required documentation. An architecture-only boundary requires accepted architecture review evidence.

## Tracked Content

Stage only Project Lead-approved source, tests, fixtures, configuration, architecture, user documentation, canonical management state, accepted compact results, and referenced verification evidence.

## Excluded Content

Never stage `.codexteam/runtime/`, credentials, secrets, caches, build outputs, temporary files, backups, raw model logs, or unrelated changes.

## Commit Rules

- One coherent local commit per authorization.
- Explicit literal staging paths only; never `git add .` or `git add -A`.
- Existing staged changes require explicit ownership or the operation blocks.
- Git identity must already be configured.
- Active commit hooks require human handling and block the automated commit.
- Amend, reset, clean, restore, checkout, merge, tag, push, remote PR creation, release, and publication are prohibited.

## Commit Message

Use a concise imperative subject and a body that identifies the milestone, accepted task IDs, and gate or architecture-review evidence.
