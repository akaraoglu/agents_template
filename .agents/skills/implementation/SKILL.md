---
name: implementation
description: Implement an approved or well-understood change safely and minimally. Use whenever production code, tests, configuration, documentation, or migrations will be edited.
---

# Implementation

## Purpose

Make the smallest coherent change that satisfies the request while preserving
unrelated behavior and user work.

## Inputs

- Accepted requirements or implementation plan
- Relevant code, tests, configuration, and repository guidance
- Applicable language skill and repository-native commands

## Workflow

1. Confirm implementation is authorized and requirements are sufficiently clear.
2. Inspect the working tree and distinguish pre-existing changes from task work.
3. Read the affected implementation, tests, call sites, and public contracts.
4. Select the smallest design consistent with existing patterns.
5. Implement in coherent increments:
   - preserve interfaces unless change is intentional
   - keep validation at trust boundaries
   - preserve error, cleanup, cancellation, and concurrency semantics
   - update migrations, generated sources, lockfiles, or documentation through
     repository-approved workflows
6. Add or update tests for observable behavior, regressions, and relevant error
   paths. Explain when practical automated coverage is unavailable.
7. Inspect incremental diffs for accidental scope, stale code, debug artifacts,
   or unrelated formatting.
8. Use `verification` before declaring completion.
9. Self-review the final diff against requirements and material risks.

## Expected Output

A focused implementation with matching tests and required documentation or
configuration updates, ready for independent review or delivery.

## Validation

- Requested behavior and acceptance criteria are satisfied.
- Unrelated behavior, public contracts, and user changes are preserved.
- Relevant focused and broader checks pass or blockers are documented.
- Final diff contains no temporary diagnostics, secrets, or unintended files.

## Cautions

- Do not broaden scope to make adjacent code ideal.
- Do not add speculative compatibility code, abstractions, or dependencies.
- Do not modify generated files manually when a generator is authoritative.
- Do not weaken tests or error handling merely to make checks pass.
- Do not claim independent review from an implementation self-review.

## Related Guidance

- `.agents/skills/planning-design/SKILL.md`
- `.agents/skills/verification/SKILL.md`
- `.agents/skills/code-review/SKILL.md`
- `.agents/capabilities/boundaries.md`
- `.agents/capabilities/coding-standards.md`
