# Python Testing

## Principles

- Test through the public interface and assert observable outputs, side effects,
  persisted state, and errors.
- Prefer tests that survive internal refactoring when behavior is unchanged.
- Name tests for the scenario and expected outcome.
- Keep each test focused on one behavior or one coherent interaction.
- Use minimal deterministic fixtures and keep setup close to the test unless it
  is genuinely shared.
- Use real internal components when practical; mock external services, clocks,
  randomness, slow resources, and other explicit boundaries.

## Structure

- Separate arrange, act, and assert conceptually. Add whitespace or descriptive
  comments only when they improve readability.
- Include success, boundary, validation, and relevant failure cases.
- For regressions, make the test fail for the original defect when practical.
- Avoid assertions about private fields, exact call counts, or helper selection
  unless those details are themselves contractual.
- Keep test data free of credentials and sensitive personal information.

## Async and Resource Tests

- Use the repository's configured async test support.
- Make timeouts bounded and avoid sleeps as synchronization when deterministic
  signals are available.
- Use fresh state for tests that involve event loops, sessions, databases,
  caches, temporary files, or global registries.
- Verify cleanup, cancellation, transaction rollback, and resource closure when
  those behaviors are material.

## Execution

- Use the repository's configured test runner and plugins.
- Run the focused test first, then the affected suite and broader gates according
  to risk.
- Do not add a plugin or parallel execution mode unless it is already configured
  or explicitly needed.
- Treat warnings, collection errors, skipped tests, and flaky retries as evidence
  to inspect rather than an automatic pass.
