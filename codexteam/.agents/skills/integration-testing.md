# Integration Testing Skill

## Purpose

Engineer and run an independent CI-equivalent gate that detects regressions across components, workflows, environments, and approved system boundaries without repairing production code.

## When To Use

Use after a Developer draft and development-gate evidence exist, before the Developer is finalized when both roles are working on the same deliverable.

## Inputs Needed

- Approved requirements, acceptance criteria, decisions, and Test Engineer handoff
- Developer draft, changed files, and development-gate evidence
- Existing integration, system, acceptance, regression, fixture, and golden conventions
- Project-defined integration-gate argument arrays from `management/TEST_GATES.toml`

## Workflow

1. Derive expectations from approved project truth, not from the current implementation output.
2. Map acceptance criteria and affected existing behavior to integration, regression, negative, lifecycle, concurrency, security, browser, or environment checks as applicable.
3. Inspect existing tests before editing. Add or modify Test Engineer-owned tests and controlled fixtures only when the handoff authorizes the paths. When a browser is necessary, use the role-allowed Playwright inspection tools for a bounded observation and prefer `browser_find` over a full snapshot when one text target is sufficient. Do not use screenshots, form input, clicks, uploads, keyboard input, page evaluation, or arbitrary browser code in the inspection-only pilot.
4. For every changed assertion or golden value, record the requirement, accepted decision, or confirmed test defect that justifies the change.
5. Demonstrate a relevant failure before the product fix when practical, then preserve the passing rerun after correction.
6. Run the configured integration gate. It must include the development gate before broader checks.
7. Classify every failure as product defect, test defect, environment defect, or unresolved evidence.
8. Return product defects to the same Developer session through the Project Lead. Never modify production source while acting as Test Engineer.
9. After the final Developer revision, rerun the affected checks and complete integration gate before either role claims acceptance.

## Commands To Run

Run `run-test-gate.py <project-root> --gate integration`. The executor loads `management/TEST_GATES.toml`, always runs the Development Gate first, executes integration arrays without a shell, and writes `results/gates/integration.json`. External CI must invoke the same gate or an exact wrapper around it so local and CI acceptance cannot drift.

## Expected Output

- Requirement-backed tests under the project convention, normally `tests/integration/` and related fixture, test-data, or golden directories
- Exact CI-equivalent commands, observations, environment notes, and failure classifications
- Reusable evidence under `results/`
- A clear PASS, FAIL, or unresolved disposition without production repairs

## Validation

- The integration gate includes the development gate.
- Existing assertions are not weakened merely to obtain a pass.
- Added tests cross a real boundary when integration is claimed; mocks alone do not prove system integration.
- Playwright MCP observations identify what to test; repository-owned browser tests and the Integration Gate remain the acceptance evidence.
- Repeated runs are deterministic or limitations are explicit.
- The Reviewer can trace each changed expectation and acceptance claim to project truth and named evidence.

## Common Mistakes Or Failure Modes

- Copying current implementation output into a golden file without an approved expectation
- Modifying Developer-owned unit or smoke tests without a separate explicit assignment
- Repairing source instead of returning a classified product defect
- Running a broad suite without proving the affected acceptance criteria
- Using a different local command than the external CI gate
- Finalizing evidence produced before the last Developer revision

## Related Files

- `.agents/skills/development-testing.md`
- `.agents/skills/verification.md`
- `.agents/skills/subagent-orchestration.md`
- `management/TEST_GATES.toml`
- `management/TEST_GATES.md`
- Active Test Engineer handoff under `management/tasks/`
