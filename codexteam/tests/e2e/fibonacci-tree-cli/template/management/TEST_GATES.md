# Test Gates

Status: Configured for the controlled Fibonacci fixture.

## Development Gate

- Owner: Developer
- Canonical command: `python3 -B -m unittest discover -s tests -v`
- Smoke commands: direct CLI checks for `0`, `1`, `4`, `15`, `--help`, and invalid input
- Expected maximum duration: 30 seconds
- Evidence artifact: `results/t002-development.txt`

The Developer runs this gate before returning the T002 draft and after each product correction.

## Integration Gate

- Owner: Test Engineer (`tester` protocol role)
- Canonical commands: run the Development Gate first, then direct CLI checks for all AC1-AC8 cases and compare input `4` with `golden/fib-4.txt`
- Expected maximum duration: 60 seconds
- Evidence artifact: `results/t003-acceptance.txt`

The repository runner executes the same commands as its deterministic product gate. The Test Engineer classifies failures and returns product defects to the same Developer session through the Project Lead.

## Expectation Integrity

The fixed expectations come from `PROJECT.md` and `golden/fib-4.txt`. This controlled T003 assignment does not authorize test or golden changes. A suspected expectation defect must be reported to the Project Lead rather than changed to match current output.
