---
name: engineering-workflow
description: Route substantial coding work through discovery, design, implementation, verification, and review. Use for multi-file changes, behavior changes, bug fixes, refactors, or work with material compatibility or operational risk.
---

# Engineering Workflow

## Purpose

Provide a complete, risk-based lifecycle without forcing ceremony onto trivial
tasks.

## Inputs

- User goal and task mode
- Applicable repository guidance
- Affected code, tests, configuration, and interfaces
- Repository-native validation commands

## Workflow

1. **Discover and scope**
   - Use `discovery-scoping` when the affected boundary is not obvious or work
     spans several repository areas.
   - Confirm whether the task is analysis, planning, implementation, review, or
     delivery.
   - Inspect relevant guidance, code, tests, configuration, and current changes.
   - Define acceptance criteria, non-goals, constraints, and affected interfaces.
2. **Assess risk**
   - Consider compatibility, data migration, security, privacy, concurrency,
     performance, dependencies, operations, and rollback.
   - Scale planning and verification to the material risks, not file count alone.
3. **Plan and design**
   - Use `planning-design` when the implementation path is not immediate or the
     change affects architecture, interfaces, persisted data, or several units.
   - Map acceptance criteria to code changes and verification.
4. **Implement**
   - Use `implementation` and any applicable language skill.
   - Keep the change coherent, minimal, and separated from unrelated work.
5. **Verify**
   - Use `verification` to run focused checks first and broader gates as risk
     requires.
   - Add practical regression coverage for behavior changes and bug fixes.
6. **Review**
   - Review the final diff against requirements, risk, tests, and repository
     conventions.
   - Use `code-review` for formal review requests or high-risk self-review.
7. **Report**
   - State the outcome, important implementation decisions, checks and results,
     skipped validation, and residual risks.

## Expected Output

A complete change or analysis whose scope, design rationale, implementation,
verification evidence, and remaining uncertainty are traceable to the request.

## Validation

- Every acceptance criterion is implemented or explicitly unresolved.
- Material risks have matching controls or verification.
- Final diff and working-tree state contain no unintended task changes.
- Reported verification matches commands actually run.

## Cautions

- Do not turn a request for a plan or review into implementation.
- Do not require a formal written plan for a clear, low-risk, localized edit.
- Do not mistake passing tests for adequate coverage or complete review.
- Do not publish, commit, or deploy without explicit authorization.

## Related Guidance

- `.agents/skills/discovery-scoping/SKILL.md`
- `.agents/skills/planning-design/SKILL.md`
- `.agents/skills/implementation/SKILL.md`
- `.agents/skills/verification/SKILL.md`
- `.agents/skills/code-review/SKILL.md`
- `.agents/capabilities/boundaries.md`
