---
name: code-review
description: Review a change for correctness, regressions, security, compatibility, design quality, and test adequacy. Use for review requests, pull-request review, pre-delivery audits, and structured implementation self-review.
---

# Code Review

## Purpose

Find actionable defects and risks in a proposed change. Review is read-only
unless the user separately authorizes fixes.

## Inputs

- Review scope and base or acceptance criteria
- Complete diff and relevant working-tree state
- Affected source, tests, configuration, documentation, and public contracts
- Available verification evidence

## Workflow

1. Establish the exact review scope, comparison base, and whether the review is
   independent or a self-review.
2. Inspect status and the complete diff, including new, deleted, generated, and
   configuration files.
3. Read enough surrounding code and tests to understand intended behavior.
4. Review in this order:
   - correctness and acceptance-criteria gaps
   - regressions, boundary conditions, and error paths
   - security, privacy, authorization, and trust boundaries
   - concurrency, cleanup, resource lifetime, and operational failure modes
   - API, schema, migration, protocol, and backward compatibility
   - performance risks proportional to the affected path
   - test adequacy, determinism, and whether assertions prove behavior
   - documentation, configuration, rollout, and observability impact
   - unnecessary complexity or divergence from repository conventions
5. Verify suspicious claims with focused read-only analysis or safe commands when
   practical. Do not assume a green suite proves correctness.
6. Report findings first, ordered by severity. Include file and line references,
   impact, evidence, and the condition that triggers the problem.
7. If no findings exist, state that explicitly and identify residual risks or
   verification gaps.
8. Stop after the report unless fixes were explicitly requested.

## Severity

- **Critical:** security compromise, data loss, severe outage, or unusable core
  behavior likely in normal operation
- **High:** material correctness regression, broken contract, or missing safety
  control
- **Medium:** real defect or maintenance risk with bounded impact
- **Low:** minor robustness or quality issue worth addressing

Avoid reporting pure preference as a defect unless it violates an established
repository rule or creates concrete risk.

## Expected Output

A findings-first review with precise evidence, followed by assumptions, open
questions, and a brief summary only when useful.

## Validation

- Every finding is actionable, reproducible or logically demonstrated, and tied
  to the reviewed change or an effect it omitted.
- Severity reflects impact and likelihood rather than style preference.
- Review covers tests and omitted effects, not only modified production lines.
- The report does not claim independence when authored by the implementer.

## Cautions

- Do not modify code during a review-only task.
- Do not flood the report with formatting nits that automated tools own.
- Do not require unrelated cleanup as a condition of accepting the change.
- Do not hide a lack of findings behind a generic summary.

## Related Guidance

- `.agents/skills/verification/SKILL.md`
- `.agents/skills/implementation/SKILL.md`
- `.agents/templates/report-template.md`
- `.agents/capabilities/coding-standards.md`
