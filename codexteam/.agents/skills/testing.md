# Testing Skill

## Purpose

Produce deterministic behavioral evidence and diagnose failures without silently changing requirements or production code.

## When To Use

Use for test design, test execution, bug reproduction, integration checks, and independent acceptance testing.

## Inputs Needed

- Approved acceptance criteria and active handoff
- Changed files or feature area
- Existing test conventions and commands
- Expected observable behavior

## Workflow

1. Map each requested check to an approved behavior.
2. Inspect existing tests and prefer the smallest relevant command first.
3. Keep fixtures deterministic and avoid implementation-detail assertions.
4. Run the check and preserve exact command output or a referenced artifact.
   For repeated CLI-output checks, use the project's capture-capable test code or subprocess API. Do not create `run1.txt`, `run2.txt`, scratch scripts, or shell-redirection artifacts in the project root.
5. Classify a failure as product behavior, test expectation, environment, or unresolved evidence.
6. Report the command, observed result, classification, artifact, and recommendation to the Project Lead.
7. Do not change production code or approved expectations unless separately assigned.

## Communication Example

Good: “`tree 0` differs from the approved base-case contract; the failing output is preserved in `results/t004-tree-zero.txt`. Classification: product defect. Recommendation: return to the developer.”

Bad: silently change the expected value or production code until the test passes.

## Expected Output

- Reproducible commands and observed results
- Focused behavioral tests when assigned
- Honest failure classification and evidence references

## Validation

- New tests fail before the fix when practical and pass afterward.
- Evidence is reproducible by another agent.
- No flaky timing or environment assumption is introduced.
- Testing does not silently redefine the product contract.

## Common Mistakes

- Reporting only “tests pass” without the command
- Repairing source while acting as independent tester
- Treating an environment failure as a product defect
- Editing expected output to manufacture a pass
- Leaving exploratory scripts or repeated-output scratch files in the delivered project
- Using shell redirection for determinism evidence when an exact-output test can capture both runs safely

## Related Files

- `.agents/skills/verification.md`
- `.agents/skills/subagent-orchestration.md`
- Approved acceptance criteria in `PROJECT.md`
