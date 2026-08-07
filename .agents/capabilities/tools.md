# Tools and Environment

Use repository-native tooling first. Inspect local scripts, manifests,
configuration, CI workflows, and contributor documentation before inventing
commands or installing dependencies.

## Discovery

- Identify the repository root and relevant nested guidance.
- Determine the language, package manager, build system, and configured quality
  gates from repository files rather than assumptions.
- Reuse the project's environment and lockfiles.
- Prefer existing scripts and task runners over reconstructed command chains.
- Treat generated files according to their documented generation workflow.

## Execution

- Run the smallest relevant command first, then broaden checks according to
  risk and repository requirements.
- Inspect actual output before changing code in response to a failure.
- Distinguish product failures from test, tool, dependency, permission, and
  environment failures.
- Do not install global tools, change machine configuration, or contact paid or
  production services without authorization.
- Account for commands that write caches, snapshots, lockfiles, generated code,
  databases, or artifacts when operating in read-only mode.

## Search and Inspection

- Prefer precise repository-aware search and file listing tools.
- Read enough surrounding code and tests to understand contracts before editing.
- Inspect version-control status and preserve pre-existing changes.

## Reporting

- Record exact validation commands and observed outcomes.
- If a gate cannot run, state what was attempted, why it was blocked, and what
  remains unverified.
- Never convert a missing tool, unavailable service, or skipped check into a
  claimed pass.

Language-specific environment and command guidance belongs in the applicable
skill, such as `.agents/skills/python/SKILL.md`.
