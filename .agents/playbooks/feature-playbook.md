# Feature Playbook

## Goal

Add or intentionally change behavior while preserving repository coherence and
making compatibility and verification explicit.

## Preconditions

- Requested outcome and acceptance criteria are known.
- Implementation is authorized.
- Relevant entry points, interfaces, and repository conventions are identified.

## Steps

1. Use `discovery-scoping` to identify affected behavior, interfaces, tests,
   non-goals, and material risks.
2. Inspect similar features and existing architecture.
3. Use `planning-design` when the change is multi-part or affects public APIs,
   schemas, persisted data, dependencies, security, or operations. Compare
   alternatives only when the choice materially matters.
4. Define the smallest coherent feature slice and map acceptance criteria to
   implementation and verification.
5. Implement through established patterns using `implementation` and applicable
   language guidance.
6. Add practical coverage for new behavior, boundaries, and relevant failures.
7. Run risk-based checks through `verification`.
8. Self-review the final diff for correctness, compatibility, unnecessary scope,
   and required documentation or rollout work.

## Verification

- Acceptance criteria work through observable interfaces.
- Regression coverage exists or its practical limitation is explained.
- Required repository quality gates pass.
- Compatibility, migration, operational, and documentation effects are handled.

## Recovery

- Prefer an isolated feature flag or repository-defined rollback mechanism when
  the design requires staged rollout.
- Reverting or disabling deployed behavior requires explicit operational
  authority and preservation of unrelated user work.
- Record intentionally deferred work and residual risks.

## Related Guidance

- `.agents/skills/engineering-workflow/SKILL.md`
- `.agents/skills/planning-design/SKILL.md`
- `.agents/skills/implementation/SKILL.md`
- `.agents/skills/verification/SKILL.md`
