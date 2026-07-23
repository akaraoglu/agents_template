# Development Testing Skill

## Purpose

Prove the changed algorithm or component works and that the product can execute one basic path before independent integration testing begins.

## When To Use

Use on every Developer assignment that changes source, runtime configuration, build behavior, or a user-visible workflow.

## Inputs Needed

- Active Developer handoff and approved acceptance criteria
- Changed source and existing unit, algorithm, regression, and smoke conventions
- Project-defined development-gate argument arrays from `management/TEST_GATES.toml`
- Known constraints, supported environments, and relevant prior defects

## Workflow

1. Map each changed behavior to a focused unit, algorithm, or component test.
2. Add a regression test for the assigned defect or boundary when the behavior can be asserted at development-test scope.
3. Run the smallest changed-area command first.
4. Run the complete configured development gate, including one startup or happy-path smoke check.
5. Self-review failures and the implementation diff; fix only Developer-owned source and tests.
6. Preserve exact commands and observations in a project-relative evidence artifact when the handoff requires one.
7. Report integration, system, browser, security, and environment coverage as unverified until the Test Engineer runs the integration gate.

## Commands To Run

Run `run-test-gate.py <project-root> --gate development`. The executor loads the `[development].commands` arrays from `management/TEST_GATES.toml` without a shell and writes `results/gates/development.json`. The gate must cover algorithm/unit behavior and a smoke path. It may also contain project-standard build, type, lint, or static checks.

## Expected Output

- Focused Developer-owned tests under the project convention, normally `tests/unit/` and `tests/smoke/`
- A passing configured development gate or exact classified failures
- A draft that distinguishes development evidence from independent integration acceptance

## Validation

- Changed algorithms and important branches have expectation-bearing tests.
- The smoke check exercises a real startup, import, command, request, or equivalent basic product path.
- Commands are reproducible from the project root.
- No integration, CI, or independent-acceptance claim is made from this gate alone.

## Common Mistakes Or Failure Modes

- Running only the new test while ignoring existing changed-area tests
- Calling a mocked unit test an integration check
- Omitting the smoke path because unit tests pass
- Editing Test Engineer-owned integration, acceptance, regression, fixture, or golden artifacts
- Finalizing while the Project Lead has an unresolved Test Engineer product defect for the same assignment

## Related Files

- `.agents/skills/implementation.md`
- `.agents/skills/integration-testing.md`
- `management/TEST_GATES.toml`
- `management/TEST_GATES.md`
- Active Developer handoff under `management/tasks/`
