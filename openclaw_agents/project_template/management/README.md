# Management Workspace

This folder is the document-driven management layer for one project.

Core flow:
- `AgentSmith`: discussion, challenge, clarification, routing
- `Neo`: direct technical execution and deep technical help
- `Niaobe`: project loop and project decisions
- `Architect`: scope, milestones, stories, tasks, acceptance criteria
- `Morpheus`: software-team execution orchestration
- `Oracle`: technical validation and truth-checking
- `Yoda`: critique, reframing, and second opinions

Document model:
- `PROJECT.md`: stable charter and operating model
- `MILESTONES.md`: milestone plan and exit criteria
- `BACKLOG.md`: prioritized story index
- `STATUS.md`: current state, active work, blockers, and next actions
- `DECISIONS.md`: durable management and architecture decisions
- `RISKS.md`: risks, assumptions, and unanswered questions
- `stories/`: story definitions
- `tasks/`: concrete execution tasks

Recommended split:
- `PROJECT.md` answers:
  - what the project is
  - why it exists
  - what success looks like
  - who does what
  - how work moves through the system
- `MILESTONES.md` answers:
  - which milestone comes next
  - what exits each milestone
- `BACKLOG.md` answers:
  - what work exists and how it is prioritized
- `STATUS.md` answers:
  - what is true right now
  - what is blocked
  - what happens next

Rules:
- Every task should map to a story.
- Every story should support a milestone or an explicit goal.
- `done` is not `verified`.
- Do not duplicate backlog, milestone tables, or daily status inside `PROJECT.md`.
- `PROJECT.md` should stay stable; `STATUS.md` should change more often.
- Oracle or explicit human review determines `verified`.
