# Security Test Matrix

| Category | Expected Result | Coverage |
|----------|-----------------|----------|
| Absolute/traversal path | Rejected | `tests/test_paths.py` |
| Symlink escape | Rejected | `tests/test_paths.py` |
| Unsafe project ID | Rejected | `tests/test_project_init.py` |
| Result-directory escape | Rejected | `tests/test_spawn.py` |
| Missing profile | Rejected before execution | `tests/test_spawn.py` |
| Missing result fields | Rejected | `tests/test_contracts.py` |
| Copied result template | Rejected | `tests/test_contracts.py`, `tests/test_spawn.py` |
| Cross-task/attempt result | Rejected | `tests/test_contracts.py`, `tests/test_spawn.py` |
| Missing artifact | Blocks closure | `tests/test_close_loop.py` |
| Failed verification | Leaves task incomplete | `tests/test_close_loop.py` |
| Repeated closure | No duplicate mutation | `tests/test_close_loop.py` |
| Shell metacharacter pipe | Rejected | `tests/test_tasks.py`, `tests/test_close_loop.py` |
