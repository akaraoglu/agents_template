# PROJECT

This file is the workspace-level project charter and execution contract. Keep it aligned with the authoritative control-plane state.

## Identity

- Project ID: `[replace_me]`
- Human name: `[replace_me]`
- Priority: `LOW | MEDIUM | HIGH | URGENT`
- Project status: `NEW | ACTIVE | VERIFICATION_PENDING | DONE | BLOCKED | CANCELLED`
- Runtime status: `NEW | READY | ACTIVE | PAUSE_REQUESTED | PAUSED | WAITING_EXTERNAL | WAITING_VERIFICATION | BLOCKED | DONE | CANCELLED`
- Assigned project orchestrator: `Niobe`
- Assigned software orchestrator: `Morpheus`
- Workspace ref: `[absolute_workspace_path]`
- Repo root: `[absolute_repo_root]`
- Branch or worktree id: `[branch_or_worktree_id]`
- Last clean commit or checkpoint: `[git_sha_or_named_checkpoint]`

## Summary

Describe the project in 3-6 sentences. State the problem, the expected user or operator outcome, and the business or operational reason this work exists.

## Goals

- `[goal 1]`
- `[goal 2]`
- `[goal 3]`

## Non-Goals

- `[non-goal 1]`
- `[non-goal 2]`

## Acceptance Criteria

- `[criterion 1 with observable pass condition]`
- `[criterion 2 with observable pass condition]`
- `[criterion 3 with observable pass condition]`

## Constraints

- Technical constraints: `[libraries, platforms, interfaces, safety limits]`
- Process constraints: `[review, testing, deployment, regulatory, or timing rules]`
- Environment constraints: `[network, hardware, secrets, sandbox limits]`

## System Context

- Upstream inputs: `[documents, systems, teams, APIs, or humans this project depends on]`
- Downstream consumers: `[who uses the result]`
- Key artifacts expected: `project_charter`, `architecture_spec`, `software_delivery_package`, `verification_report`

## Repositories And Commands

- Primary repo or repos: `[paths or repo names]`
- Build command: `[replace_me]`
- Test command: `[replace_me]`
- Lint or static-check command: `[replace_me]`
- Run or demo command: `[replace_me]`

## Architecture Notes

- Existing design references: `[docs, diagrams, code areas]`
- Known technical boundaries: `[components, interfaces, ownership lines]`
- Known risk areas: `[areas likely to fail or require design review]`

## External Dependencies

- `[dependency 1 and current status]`
- `[dependency 2 and current status]`

## Open Questions

- `[question 1]`
- `[question 2]`

## Operator Notes

- Preferred escalation path: `[MASTER | Neo | AgentSmith | other operator process]`
- Pause or switch sensitivity: `[why this workspace is or is not safe to interrupt mid-cycle]`
- Recovery hints: `[how to restore this workspace if interrupted]`
