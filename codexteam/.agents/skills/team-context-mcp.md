# CodexTeam Context MCP Skill

## Purpose

Give the Project Lead bounded, structured, read-only CodexTeam context without
repeated repository scans, full result dumps, or large shell-output cycles.

## When To Use

Use when the Project Lead needs current state from an initialized project:
orientation, task selection, handoff preparation, attempt review, gate review,
result validation, cost diagnosis, memory lookup, repository search, or change
triage.

Do not load this skill for an uninitialized new-project proposal. Do not use the
MCP tools to infer that a mutation, test, or acceptance check occurred.

## Inputs Needed

- Exact project directory name under `./projects`
- The decision being made
- Task ID, attempt ID, role, query, or filter only when required
- Canonical artifact path when a returned summary identifies evidence to inspect

## Workflow

1. Discover `codexteam-context` once when its tools are not already visible.
2. Call the smallest tool that answers the current question:

| Need | Tool |
|---|---|
| Current focus and active attempts | `get_active_task` |
| Progress, attention items, gates, and Git state | `get_project_overview` |
| Bounded filtered ledger rows | `list_tasks` |
| One canonical handoff | `get_task_handoff` |
| Handoff, dependencies, role boundary, concurrent work, and gates | `get_task_context` |
| Attempt state, bounded turns, token deltas, and result fields | `get_attempt_summary` |
| Development and Integration Gate configuration and freshness | `get_gate_status` |
| Result identity, contract, and referenced evidence | `validate_result_record` |
| Expensive turns and tool-cycle indicators | `get_cost_hotspots` |
| Project decisions and configured team memory | `search_team_memory` |
| Ranked bounded source matches | `search_repository` |
| Git status, diff statistics, suspicious paths, and bounded excerpts | `get_change_summary` |

3. Chain another MCP call only when the first result exposes a specific missing
   dependency. Do not call the full tool set as a routine preflight.
4. Respect truncation, freshness, and `query_stats`. Open only a named source or
   artifact when the Lead must inspect exact content.
5. Use canonical CodexTeam commands for every mutation and for captured
   verification evidence. A read-only MCP response is context, not proof that a
   gate or product check passed.
6. If a tool is unavailable or returns an error, retry once only when input or
   relevant state changed. Otherwise use the narrow existing command or file
   read and record the fallback reason.
7. Reuse the resulting facts in worker handoffs and review. Do not make a worker
   rediscover accepted context.

## Commands To Run

MCP calls use the Codex tool interface and require no shell command. When tool
discovery fails, diagnose registration once:

```bash
codex mcp get codexteam-context
```

The registered server entry point is `scripts/team-context-mcp.py`. Do not start
a second server manually during a normal Lead turn.

## Expected Output

- Bounded structured fields tied to the exact project, task, or attempt
- Source paths or evidence references when deeper inspection is needed
- `query_stats` describing duration, returned bytes, source bytes, and cache use
- No repository mutation

## Validation

- Returned identity matches the requested project, task, attempt, and role.
- Truncation or stale evidence is visible before a decision is made.
- The Lead does not claim tests, acceptance, or closure from context alone.
- A sufficient MCP result is not followed by a broad duplicate shell scan.
- Failures use one narrow fallback rather than repeated unchanged calls.

## Common Mistakes Or Failure Modes

- Calling every context tool at each phase boundary
- Repeating MCP results with `find`, broad `rg`, full JSONL, or full result dumps
- Treating a summary or fresh-looking gate record as independent verification
- Using repository search when the handoff already names the exact file
- Retrying an unchanged failed call
- Expecting an already-running Codex process to reload newly registered servers
- Asking a worker to repeat context already accepted by the Project Lead

## Related Files

- `.agents/skills/project-lead.md`
- `.agents/skills/subagent-orchestration.md`
- `.agents/skills/verification.md`
- `scripts/team-context-mcp.py`
- `src/codexteam_tools/context_mcp.py`
