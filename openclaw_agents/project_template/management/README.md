# Management Workspace

This folder is the document-driven management layer for one project.

Core flow:
- `AgentSmith`: discussion, challenge, clarification
- `Architect`: scope, milestones, stories, tasks, management validation
- `Morpheus`: software-team execution orchestration
- `Oracle`: technical validation and truth-checking

Document model:
- `PROJECT.md`: project identity, scope, goals, constraints, success criteria
- `MILESTONES.md`: milestone plan and exit criteria
- `BACKLOG.md`: prioritized story index
- `STATUS.md`: current state, active work, blockers, and next actions
- `DECISIONS.md`: durable management and architecture decisions
- `RISKS.md`: risks, assumptions, and unanswered questions
- `stories/`: story definitions
- `tasks/`: concrete execution tasks

Rules:
- Every task should map to a story.
- Every story should support a milestone or an explicit goal.
- `done` is not `verified`.
- Architect owns management validation after execution.
