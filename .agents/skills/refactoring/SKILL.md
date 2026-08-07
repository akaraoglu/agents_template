---
name: refactoring
description: Improve code structure while preserving externally observable behavior. Use for extraction, simplification, decomposition, dependency cleanup, or reorganization without intended feature changes.
---

# Refactoring

## Purpose

Make structure measurably simpler or safer while preserving behavior and
contracts.

## Inputs

- Target code and structural problem
- Existing interfaces, dependents, and behavior tests
- Repository quality gates and compatibility requirements

## Workflow

1. Confirm the task is behavior-preserving and state the structural objective.
2. Identify public APIs, schemas, side effects, ordering, errors, performance
   characteristics, and other behavior that must remain stable.
3. Establish a baseline with focused tests, characterization tests, static
   analysis, or reproducible behavior.
4. Choose the smallest structural transformation that addresses the problem.
5. Refactor in coherent increments and inspect each diff. Avoid combining feature
   work, broad renaming, dependency changes, or formatting churn.
6. Preserve tests that describe behavior; update tests tied only to changed
   internals when necessary.
7. Run the baseline after each risky boundary and complete risk-based
   verification.
8. Review whether the result is actually simpler in dependency direction,
   responsibility, duplication, or readability.

## Expected Output

A focused structural change with evidence that observable behavior and supported
interfaces remain unchanged.

## Validation

- Baseline and final behavior match.
- Public contracts and compatibility-sensitive formats remain stable.
- The resulting structure is simpler according to the stated objective.
- No feature behavior or unrelated cleanup entered the diff.

## Cautions

- Do not label a behavior change as a refactor.
- Do not remove apparently dead code without checking dynamic, configuration,
  plugin, serialization, and external-entry usage.
- Do not create abstractions whose only benefit is reducing line count.

## Related Guidance

- `.agents/skills/implementation/SKILL.md`
- `.agents/skills/verification/SKILL.md`
- `.agents/skills/code-review/SKILL.md`
