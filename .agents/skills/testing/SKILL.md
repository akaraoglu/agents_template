---
name: testing
description: Design or improve automated tests that provide durable evidence of behavior. Use when adding test coverage, repairing brittle tests, choosing a test layer, or evaluating test quality.
---

# Testing

## Purpose

Create focused, deterministic tests at the lowest layer that proves the required
behavior without coupling unnecessarily to implementation details.

## Inputs

- Behavior, regression, or risk to verify
- Existing test layout, frameworks, fixtures, and commands
- System boundaries and integration points

## Workflow

1. Inspect existing tests and repository conventions for the affected area.
2. Define the observable behavior and why a test is needed.
3. Choose the appropriate layer:
   - unit for isolated logic and edge cases
   - component or integration for collaboration and boundaries
   - end-to-end or smoke for critical user or deployment paths
4. Build the smallest deterministic scenario that distinguishes correct from
   incorrect behavior.
5. Prefer public interfaces, real internal collaborators, and mocked or fake
   external boundaries.
6. Cover relevant success, boundary, validation, and failure paths without
   duplicating equivalent cases.
7. For a regression, demonstrate that the test detects the original defect when
   practical.
8. Run focused tests, inspect failures and warnings, then use `verification` for
   broader gates.

## Expected Output

Tests that read as behavioral specifications, fail for the targeted defect or
missing behavior, and remain stable through valid internal refactoring.

## Validation

- Each test has a clear behavioral purpose.
- Fixtures are minimal, deterministic, isolated, and safely cleaned up.
- Assertions prove the outcome rather than incidental mechanics.
- The selected layer covers the risk without unnecessary cost or flakiness.

## Cautions

- Do not weaken assertions, rewrite golden files, or add retries merely to get a
  pass.
- Do not mock the subject under test or every internal collaborator.
- Do not rely on wall-clock sleeps when deterministic synchronization exists.
- Do not require test coverage where no practical automated seam exists without
  documenting the alternative verification and residual risk.

## Related Guidance

- `.agents/skills/verification/SKILL.md`
- `.agents/skills/python/references/testing.md`
- `.agents/capabilities/tools.md`
