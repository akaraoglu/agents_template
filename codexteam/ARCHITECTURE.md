# Architecture

Status: Unapproved - MCP-first worker context contract draft for T018.

## Context And Boundaries

CodexTeam project lead and worker roles retrieve project, task, attempt, gate, change, and repository context via the bound `codexteam-context` MCP server. Bash discovery and broad repository scans are prohibited for context retrieval.

## MCP-first Worker Context Contract

### First-call rule
Workers must call the smallest allowed `codexteam-context` tool first for context. Do not use Bash `find`, recursive `ls`, broad `grep`, or `read_mcp_resource` to rediscover context. Native file reads are allowed only after an MCP response names an exact artifact or source target.

### Role-specific allowed tools
The following tool sets are bound per role policy and preserved:

- architect: `get_task_context`, `search_team_memory`, `search_repository`, `get_change_summary`
- developer: `get_task_context`, `search_repository`, `get_gate_status`, `get_change_summary`
- tester: `get_task_context`, `get_change_summary`, `get_gate_status`
- reviewer: `get_task_context`, `get_attempt_summary`, `validate_result_record`, `get_gate_status`, `get_change_summary`
- git_steward: `get_task_context`, `get_change_summary`, `get_gate_status`

MCP servers per role: `codexteam-context` bound; `local-docs` for architect/developer; `playwright` for tester.

### Examples
- Developer first call for task T018: `get_task_context` → inspect handoff, dependencies, role boundary, gates. If handoff names uncertain paths, call `search_repository` once. Follow with `get_gate_status` and `get_change_summary` only when first result exposes missing dependency.
- Tester first call: `get_task_context` → derive expectations, then `get_change_summary` for triage.
- Reviewer first call: `get_task_context` + `get_attempt_summary` → compare claims, then `validate_result_record`.
- Architect first call: `get_task_context` + `search_team_memory` scope=discoveries for prior notes, then `search_repository` for bounded matches.

### Fallback rules
If a tool is unavailable or returns error, retry once only when input or relevant state changed. Otherwise use narrow existing command or file read and record fallback reason. Do not chain full tool set as routine preflight. Do not repeat unchanged failed calls.

### Prohibitions
- `read_mcp_resource` is not a supported context tool and must not be used for discovery.
- The `resources/read` tool is not advertised by `src/codexteam_tools/context_mcp.py`. Supported tools are: get_active_task, get_project_overview, list_tasks, get_task_handoff, get_task_context, get_attempt_summary, get_gate_status, validate_result_record, get_cost_hotspots, search_team_memory, search_repository, get_change_summary.
- No broad discovery via Bash, `find`, recursive `ls`, broad `grep`.
- Workers must not supply `project` argument; launcher binds project and removes schema field.

## Repository Layout

See existing project structure.

## Components And Dependencies

`codexteam-context` MCP server provides read-only bounded context. Role policies in `roles/*.toml` define allowed tools and preserve permissions.

## Data And Control Flow

Context flow: Launcher binds project → worker calls allowed MCP tools → MCP returns bounded fields → worker inspects named exact paths only.

## Security And Operations

Trust boundary: MCP responses are context, not proof of gate pass.

## Test Architecture

Unchanged.

## Decisions And Risks

See `docs/decisions/2026-08-27_mcp_first_worker_context_contract.md`.
