# Coding Standards

Follow the existing codebase and its configured tools before introducing new
patterns.

## Design and Scope

- Keep modules and functions focused on a clear responsibility.
- Prefer simple composition over duplication or speculative abstraction.
- Use names that express domain intent.
- Preserve behavior and interfaces outside the requested change.
- Add dependencies only when existing code or standard facilities cannot meet
  the requirement cleanly.
- Treat public APIs, schemas, migrations, persisted data, protocols, and CLI
  behavior as compatibility-sensitive boundaries.

## Correctness

- Validate untrusted input at system boundaries.
- Make assumptions and invariants explicit where violating them would corrupt
  state or produce misleading behavior.
- Handle expected failures at the layer that can add useful context, recover,
  translate the error, or present it to the user.
- Do not catch broad errors merely to suppress them or return a misleading
  default. Unexpected failures should remain visible and diagnosable.
- Preserve resource cleanup, cancellation, transaction, and concurrency
  semantics when changing related code.

## Data and Defaults

- Use access patterns appropriate to the repository's data model and language.
- Keep configuration defaults at clear initialization or configuration
  boundaries.
- Avoid fallback values that silently hide missing required data.
- Do not hardcode duplicated policy or configuration at call sites.

## Documentation

- Prefer self-explanatory code and comments that explain why, constraints, or
  non-obvious tradeoffs rather than restating operations.
- Follow repository conventions for public API documentation and docstrings.
- Update user, API, migration, operational, or architectural documentation when
  the change makes it inaccurate.
- Avoid documentation churn unrelated to the task.

## Security and Privacy

- Never include secrets or sensitive personal data in source, fixtures, logs,
  snapshots, or examples.
- Consider injection, authorization, data exposure, resource exhaustion, and
  unsafe deserialization when changing trust boundaries.
- Prefer least-privilege behavior and safe defaults for externally controlled
  input.
