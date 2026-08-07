# Bugfix Playbook

## Goal

Resolve a defect at its root cause with regression evidence and minimal
behavioral risk.

## Preconditions

- Expected and observed behavior can be stated.
- Implementation is authorized.
- The affected environment and scope are known or can be investigated safely.

## Steps

1. Use `debugging` to reproduce the defect and isolate the first divergence from
   expected behavior.
2. Preserve evidence and test one root-cause hypothesis at a time.
3. Identify affected contracts, error paths, data, concurrency, and nearby
   behavior.
4. Add a focused regression test that demonstrates the defect when practical.
5. Implement the smallest root-cause fix using `implementation`.
6. Confirm the original reproduction and regression test now pass.
7. Run affected and risk-based broader checks through `verification`.
8. Review the final diff for symptom-only workarounds, weakened expectations,
   unintended compatibility changes, and missing error-path coverage.

## Verification

- The original failure is no longer reproducible for the understood reason.
- Regression coverage would detect recurrence, or an alternative check and
  residual risk are documented.
- Adjacent behavior and required quality gates remain intact.

## Recovery

- If the fix regresses behavior, isolate the task change before considering a
  revert; do not discard unrelated work.
- Any rollback, deployment, or production-state change requires explicit
  authority and the repository's operational procedure.

## Related Guidance

- `.agents/skills/debugging/SKILL.md`
- `.agents/skills/implementation/SKILL.md`
- `.agents/skills/verification/SKILL.md`
