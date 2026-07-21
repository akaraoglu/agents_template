# Team Brief

## Outcome

- Project: {{PROJECT_NAME}}
- Project ID: `{{PROJECT_ID}}`
- Goal: {{PROJECT_GOAL}}

## Current Truth

- Phase: initialized canary
- Active task: `T001` — validate the controlled fixture
- Responsible AI: `fixture-lead-01` (leader)
- Last verified outcome: workspace initialized; no worker result or product exists yet
- Next handoff: complete `management/tasks/T001.md`, then run the Project Lead gate

## Authority Order

1. `PROJECT.md` defines product scope and acceptance criteria.
2. The active `management/tasks/T*.md` file defines the bounded assignment.
3. An accepted result and its evidence prove worker output.
4. `TASKS.md`, `PROJECT_STATE.md`, and `CURRENT_TASK.md` record leader-verified status.

This brief is orientation. Report any conflict to the Project Lead.

## Team

- Project Lead: reviews drafts, authorizes finalization, verifies results, and closes state.
- Developer: implements the complete CLI and focused tests.
- Tester: gathers independent acceptance evidence without repairing source.
- Reviewer: audits evidence and spot-checks behavior without rewriting it.
- Documenter: aligns operator-facing documentation with verified truth.

## Working Agreement

- Each task has one responsible AI, one session, and one logical attempt.
- The worker drafts first; deterministic Project Lead checks gate finalization.
- Finalization emits exactly one `result-v1` file.
- Independent verification precedes every state transition.
- No automatic retry, model transfer, or hidden repair is allowed.
- A failed run preserves the project and session for explicit same-session recovery.

## Constraints

- Python standard library only; Python 3.12 or newer.
- Product range is `0..15`; output is deterministic UTF-8 text.
- All writes stay inside `{{PROJECT_ROOT}}`.
- The clean five-task run uses exactly ten agent turns.
