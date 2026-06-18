# Handoff Contract (Leader → Subagent)
Reference only — not enforced by Python. Each subagent prompt is built from this shape.
Version: 1.0 | Created: 2026-06-17

## Purpose
Define what the Leader sends to each role subagent when delegating a task. The JSON is injected into the system/task prompt; it can also be logged for dashboard auditing.

## Schema Shape
```json
{
  "handoff_id": "hand-t002-dev",
  "team_id": "<project-id>",
  "task_id": "t002",
  "agent_role": "developer | tester | reviewer | documenter",
  "model_profile": "qwen36-27b | gemma4-26b",
  "workspace_root": "/home/alik/workspace/codexspace/projects/<team_id>",
  "task_context": {
    "title": "Implement fibonacci.py CLI script",
    "description": "Full description of what to build/verify...",
    "dependencies_completed": ["t001"],
    "priority": "high | medium | low"
  },
  "constraints": {
    "max_runtime_seconds": 300,
    "allowed_tools": ["bash", "python3"],
    "sandbox": "workspace-write",
    "output_format": "json_result_contract_v1"
  },
  "instructions": {
    "system_prompt": "<role-specific skills injected here>",
    "task_prompt": "<specific task details>",
    "completion_criteria": [
      "file_exists:src/fibonacci.py",
      "tests_pass:true"
    ]
  }
}
```

## Field Descriptions
| Field | Required | Description |
|-------|----------|-------------|
| `handoff_id` | ✅ | Unique handoff identifier: `hand-<task>-<role>` |
| `team_id` | ✅ | Project/workspace ID matching the project folder name |
| `task_id` | ✅ | Task reference from TASKS.md (e.g., `t002`) |
| `agent_role` | ✅ | Role being delegated to |
| `model_profile` | ✅ | Local codex model profile to use |
| `workspace_root` | ✅ | Absolute path to the project directory |
| `task_context.title` | ✅ | Short title of what to do |
| `task_context.description` | ✅ | Detailed instructions for the subagent |
| `task_context.dependencies_completed` | ✅ | List of task IDs that must be done before this one |
| `constraints.max_runtime_seconds` | ⚙️ | Max runtime; default 300 if omitted |
| `constraints.allowed_tools` | ⚙️ | Tools the subagent may use; default all available |
| `instructions.completion_criteria` | ✅ | Checkable conditions marking the task done |

## Profile Selection Matrix (from orchestration skill)
| Role | Model | Rationale |
|------|-------|-----------|
| Developer | `qwen36-27b` | Strong code generation and reasoning |
| Tester | `qwen36-27b` | Needs to write test scripts and validate edge cases |
| Reviewer | `gemma4-26b` | Lighter model sufficient for compliance checks |
| Documenter | `gemma4-26b` | Doc generation is text-heavy, lower compute needed |

## Notes
- This contract is markdown-reference only. No JSON schema validator enforces it today.
- Dashboard consumers can parse this shape directly from spawn-subagent.sh logs.
