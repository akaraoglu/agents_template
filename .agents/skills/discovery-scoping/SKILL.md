---
name: discovery-scoping
description: Establish task mode, repository context, acceptance criteria, affected interfaces, and authorized scope before substantial work. Use when a task spans multiple areas or its implementation boundary is not obvious.
---

# Discovery and Scoping

## Purpose

Build enough repository context to choose a safe workflow without treating broad
read access as broad edit authorization.

## Inputs

- User request and constraints
- Repository root and applicable nested guidance
- Working-tree state and relevant project configuration

## Workflow

1. Determine task mode and whether edits or delivery operations are authorized.
2. Locate the repository root and relevant nested `AGENTS.md` or equivalent
   project guidance.
3. Inspect status and note pre-existing changes that must be preserved.
4. Locate affected entry points, dependents, tests, configuration, build commands,
   and similar implementations.
5. State acceptance criteria, non-goals, compatibility-sensitive interfaces, and
   material risks.
6. Ask one targeted question only when unresolved ambiguity materially changes
   behavior, scope, or risk; otherwise proceed with a stated reasonable
   assumption.
7. Select the smallest applicable lifecycle skills and verification scope.

## Expected Output

A bounded task definition and evidence-based next action or plan.

## Validation

- Relevant instructions and repository conventions were inspected.
- Scope distinguishes readable context from authorized edits.
- Pre-existing user changes and sensitive boundaries are identified.
- Acceptance criteria and verification path are actionable.

## Cautions

- Do not perform broad repository exploration when a focused inspection answers
  the question.
- Do not modify files merely to discover whether a solution works.
- Do not assume machine or network access beyond the task's authorization.

## Related Guidance

- `.agents/skills/engineering-workflow/SKILL.md`
- `.agents/skills/planning-design/SKILL.md`
- `.agents/capabilities/boundaries.md`
- `.agents/capabilities/tools.md`
