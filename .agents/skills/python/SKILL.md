---
name: python
description: Apply repository-aware Python implementation and testing practices. Use when reading, changing, testing, or reviewing Python code after first inspecting the project's configured version, environment, style, and tools.
---

# Python

## Purpose

Add Python-specific engineering guidance without imposing one project's
environment, formatter, framework, or package layout on another.

## Inputs

- Supported Python versions and packaging configuration
- Repository environment, dependency manager, formatter, linter, type checker,
  test runner, and CI commands
- Existing source and test conventions

## Workflow

1. Inspect `pyproject.toml`, lockfiles, test configuration, CI, contributor
   guidance, and nearby code before selecting commands or syntax.
2. Use the repository's environment and package manager. Do not replace it with
   `pip`, `uv`, Poetry, Conda, or another tool by preference.
3. Match the supported Python version and configured formatting, imports,
   typing, and documentation conventions.
4. Apply the relevant references:
   - `references/typing.md`
   - `references/testing.md`
   - `references/async.md`
   - `references/logging.md`
5. Keep validation, exceptions, and cleanup explicit at system boundaries.
6. Run focused tests and configured Python quality gates through the repository's
   native commands.

## Expected Output

Python code and tests that fit the repository's supported versions, public
contracts, runtime model, and configured quality gates.

## Validation

- Code parses and runs on supported Python versions.
- Configured formatter, linter, type checker, tests, and build checks pass where
  applicable.
- Async changes do not block event-loop paths or leak tasks and resources.
- Tests verify public behavior with deterministic, minimal setup.

## Cautions

- Do not mandate `from __future__ import annotations`, union syntax, docstring
  style, import direction, file layout, or formatter unless the repository does.
- Do not universally ban `Any`, assertions, synchronous I/O, or exception
  handling; apply the context-sensitive rules in the references.
- Do not add Pydantic, pytest, or another dependency merely because examples use
  it.

## Related Guidance

- `.agents/skills/implementation/SKILL.md`
- `.agents/skills/verification/SKILL.md`
- `.agents/capabilities/coding-standards.md`
- `.agents/capabilities/tools.md`
