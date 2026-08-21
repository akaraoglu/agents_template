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

## Planned Lane Test Sequence

During an explicit `PLANNED LANE` checkpoint, define the focused tests and any real-browser smoke scenario before production edits, but do not run write-producing test commands. After `PLAN ACCEPTED`, prefer a cheap failing unit, characterization, component, or contract test when it can express the behavior without coupling to implementation details. Define a stable browser-smoke scenario early, but run Chromium after implementation by default; a pre-implementation browser run is justified only when its expected failure is deterministic, quick, and informative.

The Developer runs at most the targeted browser smoke required by the Development Gate. The Test Engineer owns the broader Chromium, multi-viewport, integration, and regression suite. Store verbose browser logs as artifacts and return concise status, duration, failed-test names, and artifact paths.

## Workflow

1. Identify the current `AC-*` references implemented by the assignment and map
   each changed behavior to a focused unit, algorithm, or component test. Treat
   the Verification Plan as the validation route, not as evidence that a check ran.
2. Add a regression test for the assigned defect or boundary when the behavior can be asserted at development-test scope.
3. Run the smallest changed-area command first.
4. Run the complete configured development gate, including one startup or happy-path smoke check.
   Capture high-volume CLI output inside the test harness and report only the assertion result; do not dump a large successful payload into the agent transcript.
5. Self-review failures and the implementation diff; fix only Developer-owned source and tests.
6. Preserve exact commands and observations in a project-relative evidence artifact when the handoff requires one.
7. Report integration, system, broad-browser, security, and environment coverage as unverified until the Test Engineer runs the integration gate.

## Commands To Run

Run `run-test-gate.py <project-root> --gate development`. The executor loads the `[development].commands` arrays from `management/TEST_GATES.toml` without a shell and writes `results/gates/development.json`. The gate must cover algorithm/unit behavior and a smoke path. It may also contain project-standard build, type, lint, or static checks.

## Expected Output

- Focused Developer-owned tests under the project convention, normally `tests/unit/` and `tests/smoke/`
- A passing configured development gate or exact classified failures
- A draft that distinguishes development evidence from independent integration acceptance
- Applicable `AC-*` references with implementation and Development Gate evidence,
  without claiming independent acceptance

## Validation

- Changed algorithms and important branches have expectation-bearing tests.
- The smoke check exercises a real startup, import, command, request, or equivalent basic product path.
- Commands are reproducible from the project root.
- No integration, CI, or independent-acceptance claim is made from this gate alone.

## Common Mistakes Or Failure Modes

- Running only the new test while ignoring existing changed-area tests
- Calling a mocked unit test an integration check
- Omitting the smoke path because unit tests pass
- Running the full Chromium or multi-viewport regression suite instead of the targeted Development Gate smoke
- Editing Test Engineer-owned integration, acceptance, regression, fixture, or golden artifacts
- Finalizing while the Project Lead has an unresolved Test Engineer product defect for the same assignment

## Related Files

- `.agents/skills/implementation.md`
- `.agents/skills/integration-testing.md`
- `management/TEST_GATES.toml`
- `management/TEST_GATES.md`
- Active Developer handoff under `management/tasks/`
