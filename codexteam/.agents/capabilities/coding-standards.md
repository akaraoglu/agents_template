# Coding Standards

Follow the existing codebase before introducing new patterns.

## General
- Keep functions, modules, and components focused.
- Prefer composition over duplication.
- Use names that reflect domain intent, not temporary implementation details.
- Preserve existing behavior unless the task explicitly changes it.
- Reuse existing helpers and utilities before introducing new dependencies.

## Simplicity
- Aim for simple, maintainable solutions that are easy to read and modify.
- Do not over-engineer.
- Introduce new abstractions only when they clearly reduce complexity.
- Make the smallest change that solves the problem.
- Avoid unrelated cleanup in the same patch.
- Do not add dependencies unless the gain is clear and necessary.

## Fail Fast
- Do not add defensive code that hides bugs.
- If something should be initialized but is not, let it fail early and clearly.
- Avoid "helpful" defaults that mask missing data.

## Data Access
- Avoid introducing dictionary-style access for structured objects unless the codebase already models that data as mappings or the user explicitly asks for it.
- Prefer explicit attributes, properties, or typed access when the structure is known.

## Error Handling
- Do not add `try/except` blocks unless explicitly requested or already required by the surrounding code.
- If an operation fails, it should fail clearly where it happens.

## Constants and Defaults
- Hardcoded constants are allowed only at initialization or configuration boundaries.
- Do not hardcode values at call sites or access points.
- Do not embed default values in getters or accessors that hide missing data.

## Documentation and Explanations
- Do not add documentation comments or docstrings unless asked.
- Add inline comments only when the code would otherwise be hard to understand.
- Keep explanations clear and concise, assuming intermediate engineering knowledge.

## Safety
- Validate inputs at system boundaries.
- Do not log secrets or sensitive user data.
- Handle errors explicitly where failure is expected or user-visible.
