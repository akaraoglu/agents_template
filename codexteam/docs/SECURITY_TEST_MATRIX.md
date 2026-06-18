# Security Test Matrix

| Category | Expected Result | Test Coverage |
| --- | --- | --- |
| Path traversal | Denied | `tests/phase1/test_paths.py`, `tests/phase3/test_policy.py` |
| Symlink escape | Denied or reported unsafe | `tests/phase1/test_paths.py`, `tests/phase5/test_workspaces.py` |
| Hidden paths | Denied by default | `tests/phase3/test_policy.py` |
| Secret-looking paths | Denied by default | `tests/phase3/test_policy.py` |
| Raw shell command | Denied | `tests/phase3/test_policy.py` |
| Process execution | Approval required | `tests/phase3/test_policy.py`, `tests/phase6/test_adapters.py` |
| Network access | Approval required | `tests/phase3/test_policy.py` |
| Merge | Approval required | `tests/phase3/test_policy.py`, `tests/phase5/test_workspaces.py` |
| Cleanup | Approval required | `tests/phase3/test_policy.py`, `tests/phase5/test_workspaces.py` |
| Worker start before plan approval | Denied | `tests/phase7/test_controller.py` |
| Worker evidence review | Required | `tests/phase4/test_engines.py`, `tests/phase7/test_controller.py` |

