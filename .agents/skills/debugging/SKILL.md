---
name: debugging
description: Diagnose defects, regressions, failing tests, and unexplained runtime behavior through reproducible evidence and hypothesis testing. Use before implementing a bug fix when the root cause is not already proven.
---

# Debugging

## Purpose

Find and demonstrate the root cause of a failure with minimal guesswork before
changing behavior.

## Inputs

- Symptom, error, regression, or failing check
- Expected behavior and reproduction steps when available
- Relevant logs, traces, metrics, tests, code, configuration, and recent changes

## Workflow

1. Define expected versus observed behavior and the affected environment.
2. Reproduce the problem in the smallest deterministic scope. Prefer a
   non-interactive command or focused test before a full service or UI flow.
3. Preserve evidence: exact command, input, output, logs, timestamps, and state.
4. Locate the boundary where behavior first diverges from expectations.
5. Form one falsifiable hypothesis at a time. Predict what evidence would prove
   or disprove it before changing code.
6. Inspect data flow, configuration, dependencies, recent changes, error paths,
   resource lifetime, concurrency, and external boundaries relevant to that
   hypothesis.
7. Reduce the reproduction further or add temporary diagnostics when useful.
   Remove temporary artifacts before completion.
8. Confirm the root cause independently from the visible symptom.
9. Implement the smallest root-cause fix through `implementation` when edits are
   authorized.
10. Add regression coverage and verify both the original reproduction and nearby
    behavior through `verification`.

## Expected Output

A concise diagnosis containing the reproduction, root cause, supporting
evidence, affected scope, and either a verified fix or the next discriminating
experiment.

## Validation

- The reproduction is reliable or its environmental limitations are documented.
- Evidence distinguishes the root cause from correlated symptoms.
- The fix removes the reproduction without weakening valid behavior or tests.
- Resources started for debugging are stopped, while user-owned sessions and
  evidence are preserved.

## Cautions

- Do not make speculative changes across several areas at once.
- Do not delete user-owned logs, sessions, databases, or reproductions.
- Do not attach debuggers, modify production state, or contact external services
  without authorization.
- Do not record secrets or sensitive payloads in diagnostic artifacts.

## Related Guidance

- `.agents/playbooks/bugfix-playbook.md`
- `.agents/skills/implementation/SKILL.md`
- `.agents/skills/verification/SKILL.md`
- `.agents/memory/corrections.md`
