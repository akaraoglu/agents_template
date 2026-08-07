# Corrections Memory

## Purpose

Record evidence-backed, repository-wide mistakes that future agents should not
repeat. Put subsystem-specific corrections in that subsystem's guidance.

## Entries

- Do not treat a worker or tool result as completion without inspecting the
  artifact and performing appropriate independent verification.
- Do not turn every plan into a blocking approval cycle. Ask the user only when
  an unresolved choice materially affects behavior, scope, compatibility, or
  risk.
- Do not duplicate changing subsystem paths, profiles, or runtime defaults in
  root memory; use the subsystem's current source and scoped guidance.
- Do not infer edit authority from broad workspace or filesystem permissions.
