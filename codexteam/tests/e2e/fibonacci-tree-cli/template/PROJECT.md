# {{PROJECT_NAME}}

## Goal

{{PROJECT_GOAL}}

## Users and Operators

- The operator evaluating CodexTeam's complete workflow.
- Students, educators, and developers inspecting recursive Fibonacci calls.

## MVP Scope

- Accept one positional integer `N` in the inclusive range `0..15`.
- Use `F(0) = 0` and `F(1) = 1`.
- Render the complete recursive call tree in deterministic pre-order.
- Label every node `fib(N) = VALUE`.
- Render `fib(n-1)` before `fib(n-2)` for every internal node.
- Provide useful help and concise invalid-input errors without tracebacks.
- Use only the Python standard library.

## Non-Goals

- GUI, web, interactive, export, benchmark, or alternative algorithm modes.
- Inputs above 15.
- Third-party dependencies, network access, or persistent product data.
- One-off audit or verification utilities inside the generated project.

## Requirements

- The official invocation is `python3 src/fibonacci_tree_cli.py N`.
- `src/fibonacci_tree_cli.py`, `tests/test_fibonacci_tree_cli.py`, and `README.md` are the product files.
- Every delegated task uses one responsible AI and a persistent draft-to-final attempt.
- Only the Project Lead verifies results and advances canonical state.

## Acceptance Criteria

1. Input `0` prints exactly `fib(0) = 0`.
2. Input `1` prints exactly `fib(1) = 1`.
3. Input `4` prints the exact nine-line tree in `golden/fib-4.txt` with root value 3.
4. Every non-leaf has left `n-1` and right `n-2` children with correct values.
5. Non-integer, negative, missing, and above-limit input fails nonzero without a traceback.
6. `--help` documents `0..15`, `F(0) = 0`, and `F(1) = 1`.
7. The standard-library test suite covers calculation, structure, rendering, CLI, help, and failures.
8. `README.md` contains a reproducible invocation and representative output.
9. T001 through T005 each produce one accepted final result after a draft gate.
10. Independent closure leaves all tasks completed and project delivery state consistent.

## Constraints

- Project ID: `{{PROJECT_ID}}`
- Project root: `{{PROJECT_ROOT}}`
- Created: {{CREATED_AT}}
- Runtime: Python 3.12 or newer.
- Dependencies: Python standard library only.

## Architecture Notes

Use a small immutable or plainly structured node model, pure tree calculation/rendering functions, `argparse`, and a `main()` that returns a process status. Tests must be movable with the project and invoke the CLI by project-relative path.

## Verification Plan

Run `python3 -B -m unittest discover -s tests -v`, compare input 4 with `golden/fib-4.txt`, inspect help, and exercise invalid input as separate subprocesses.

## Delivery Criteria

All five tasks are independently closed, product checks pass, documentation is reproducible, and delivery reports agree with the ledger.

## Open Questions

None. This fixture is intentionally fixed for repeatable E2E comparison.
