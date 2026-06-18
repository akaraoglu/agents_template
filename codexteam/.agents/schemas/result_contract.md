# Result Contract (Subagent → Leader)
Reference only — not enforced by Python. Every subagent returns a JSON report in this shape.
Version: 1.0 | Created: 2026-06-17

## Purpose
Define the standardized result every subagent returns after completing (or failing) a delegated task. The Leader parses this to verify completion, update TASKS.md, and decide whether to advance to the next phase. Dashboard-ready: each JSON file can be read by any consumer without extra tooling.

## Schema Shape
```json
{
  "result_id": "res-t002-dev-001",
  "team_id": "fibonacci-demo",
  "task_id": "t002",
  "agent_role": "developer",
  "attempt_id": "att-001",
  "status": "completed | failed | partial | blocked | needs_review",
  "summary": "Implemented fibonacci.py with CLI arg parsing...",
  "output": {
    "exit_code": 0,
    "stdout_tail": "...",
    "stderr_tail": "",
    "duration_seconds": 45.2
  },
  "file_changes": [
    {"path": "src/fibonacci.py", "action": "created", "size_bytes": 1024},
    {"path": "tests/test_fibonacci.py", "action": "modified", "size_bytes": 512}
  ],
  "evidence": [
    {
      "type": "test_output",
      "artifact_ref": "workspace/projects/<team_id>/test-results.log",
      "summary": "pytest passed 4/4 tests",
      "content": "...truncated output...",
      "metadata": {"pass_count": 4, "fail_count": 0}
    },
    {
      "type": "code_review",
      "artifact_ref": "workspace/projects/<team_id>/src/fibonacci.py",
      "summary": "Function signature and docstrings compliant"
    }
  ],
  "requested_followups": [
    {
      "action_type": "request_review | delegate_task | request_approval",
      "target_role": "qa_agent | leader",
      "task_id": "t003",
      "reason": "Implementation complete, needs QA verification"
    }
  ],
  "warnings": ["Used temporary test data"],
  "limitations": ["No performance benchmarks included"],
  "produced_at": "2026-06-17T15:30:00+03:00"
}
```

## Status Values
| Status | Meaning | Leader Action |
|--------|---------|---------------|
| `completed` | All completion criteria met, artifacts on disk | Advance to next task or verify independently |
| `failed` | Task could not be done; blocking error | Retry with different approach or escalate |
| `partial` | Some criteria met, others missing | Review what's missing, delegate gap-filling |
| `blocked` | Waiting on external dependency or permission | Unblock or reroute |
| `needs_review` | Work done but requires Leader/Peer inspection before advance | Leader runs verification gate |

## Evidence Types
| Type | When to use |
|------|-------------|
| `test_output` | Unit/integration tests ran and passed/failed |
| `code_review` | Static review of code against spec/conventions |
| `file_manifest` | List of created/modified files |
| `cli_invocation` | Command-line test run output |
| `spec_compliance` | Manual checklist of PROJECT.md requirements |

## Required Fields
| Field | Required | Notes |
|-------|----------|-------|
| `result_id` | ✅ | Format: `res-<task>-<role>-<seq>` |
| `team_id` | ✅ | Must match the handoff's team_id |
| `task_id` | ✅ | Must match the handoff's task_id |
| `agent_role` | ✅ | Role that produced this result |
| `attempt_id` | ✅ | Format: `att-<seq>`; increments on retries |
| `status` | ✅ | One of the 5 status values above |
| `summary` | ✅ | 1-2 sentence summary of outcome |
| `file_changes` | ✅ | Even if empty array — dashboard needs it |
| `evidence` | ⚙️ | At least one entry recommended |
| `produced_at` | ✅ | ISO-8601 timestamp |

## Storage Convention
Every result is persisted to:
```
<workspace_root>/results/<task_id>-<timestamp>.json
```
This makes the project folder dashboard-ready at zero extra cost. A future dashboard can glob `results/*.json` and render status, timelines, and evidence chains.

## Notes
- This contract is markdown-reference only. No JSON schema validator enforces it today.
- Subagents should emit this JSON as the LAST thing on stdout so spawn-subagent.sh can capture it cleanly.
- When we extract `parse-result.py`, it will validate against this shape.
