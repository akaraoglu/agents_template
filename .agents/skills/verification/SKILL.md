---
name: verification
description: Verify a change with risk-based tests, static checks, builds, and final inspection. Use after implementation, during bug fixes, before delivery, or whenever correctness evidence is requested.
---

# Verification

## Purpose

Produce reliable evidence that the requested behavior works, regressions are
controlled, and the change is ready for review or delivery.

## Inputs

- Acceptance criteria and material risks
- Changed files and affected interfaces
- Repository-native test and quality-gate commands
- Existing test conventions and CI configuration

## Workflow

1. Inspect repository configuration to identify applicable checks: tests,
   formatting, linting, type checking, static or security analysis, builds,
   migrations, packaging, integration, end-to-end, and smoke tests.
2. Map acceptance criteria and risks to observable verification.
3. Prefer behavior-focused tests through public interfaces:
   - name tests for outcomes
   - keep each test focused on one behavior
   - use minimal deterministic fixtures
   - use real internal components and mock external boundaries
   - cover relevant success, boundary, and failure paths
4. For bug fixes, demonstrate the original failure when practical before
   confirming the fix.
5. Run checks progressively:
   - direct reproduction or focused test
   - affected module or package suite
   - format, lint, type, build, and static checks for changed areas
   - broader integration or full suites when risk or repository policy warrants
6. Classify failures as product, test, environment, dependency, permission, or
   unresolved. Fix root causes rather than relaxing valid expectations.
7. Inspect the final diff and status for generated artifacts, snapshots, caches,
   accidental files, or unrelated changes.
8. Record exact commands, exit outcomes, relevant observations, skipped checks,
   and remaining uncertainty.

## Expected Output

Verification evidence tied to acceptance criteria and risk, not merely a list
of commands that happened to pass.

## Validation

- New or changed behavior has practical regression coverage where available.
- The smallest relevant checks and all required repository gates were run.
- Test quality and assertions were inspected, not inferred from green status.
- Final report distinguishes passing, failing, blocked, and skipped checks.

## Cautions

- Do not run broad, costly, destructive, or production-connected checks without
  need and authorization.
- Do not rewrite expected values without proving the behavior change is intended.
- Do not overfit tests to private implementation details.
- Do not call a check read-only if it writes snapshots, caches, generated files,
  databases, or external state.
- A blocked check is not a pass.

## Related Guidance

- `.agents/skills/engineering-workflow/SKILL.md`
- `.agents/skills/implementation/SKILL.md`
- `.agents/skills/testing/SKILL.md`
- `.agents/skills/code-review/SKILL.md`
- `.agents/skills/python/SKILL.md`
- `.agents/capabilities/tools.md`
