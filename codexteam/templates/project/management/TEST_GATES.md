# Test Gates

Status: Unconfigured - T001 must configure the argument arrays in `management/TEST_GATES.toml` before implementation approval. The TOML file is authoritative for execution; this document explains ownership and evidence policy.

## Development Gate

- Owner: Developer
- Purpose: Prove changed algorithms/components and one basic executable path.
- Required coverage: focused unit or algorithm tests, changed-area regression coverage, and one startup/import/command/request smoke check.
- Canonical commands: `management/TEST_GATES.toml` `[development].commands`
- Expected maximum duration: `[development].expected_max_seconds`
- Executor: `run-test-gate.py . --gate development`
- Evidence record: `results/gates/development.json`

The Developer runs this gate before returning a draft and after every source correction. Passing it does not prove integration acceptance.

## Integration Gate

- Owner: Test Engineer (`tester` protocol role)
- Purpose: Provide the local CI-equivalent system and regression gate.
- Required coverage: the Development Gate first, then applicable integration, system, acceptance, negative, lifecycle, concurrency, security, browser, environment, and manifest checks.
- Canonical commands: `management/TEST_GATES.toml` `[integration].commands`
- Expected maximum duration: `[integration].expected_max_seconds`
- Executor: `run-test-gate.py . --gate integration`
- Evidence record: `results/gates/integration.json`

External CI must invoke this command or an exact wrapper around it. The Test Engineer reruns affected checks after the final Developer revision. Passing records pin both the normalized gate configuration and the configured verification-path manifest, so changed commands or source/test inputs make earlier evidence stale.
The Integration Gate runs the Development Gate first.

## Expectation Integrity

- Test expectations come from `PROJECT.md`, approved acceptance criteria, and accepted decisions.
- Every modified assertion, fixture expectation, or golden value requires a requirement, decision, or confirmed test-defect reference.
- A test must not be weakened merely to make current implementation output pass.
- Product defects return to the same Developer session through the Project Lead before finalization.
- The Reviewer audits source changes, test changes, gate composition, and named evidence.
