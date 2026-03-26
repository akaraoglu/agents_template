# Project Template

This folder is the reusable per-project scaffold for a shared OpenClaw and
Zulip setup.

Use it when one global agent runtime should serve multiple projects without
duplicating the same project-management documents again and again.

## Purpose

`project_template/` is for project-specific state only:
- project summary and scope
- goals, constraints, and success criteria
- milestones, stories, and tasks
- risks, decisions, and status

It should **not** contain:
- shared agent prompts
- shared OpenClaw runtime config
- shared Zulip bridge code
- global Docker or sandbox state

Those stay in the shared control workspace under `.agents/`.

## Recommended Use

For each new project:

1. Copy `project_template/` into your project folder.
2. Rename or place it as the project root contents.
3. Fill in `PROJECT.md`.
4. Start using `management/` for milestones, stories, tasks, and status.
5. Point the shared runtime at that project when Architect, Morpheus, or
   Oracle need project-scoped context.

## Expected Structure

```text
your-project/
├── PROJECT.md
└── management/
    ├── README.md
    ├── STATUS.md
    ├── MILESTONES.md
    ├── BACKLOG.md
    ├── DECISIONS.md
    ├── RISKS.md
    ├── stories/
    │   ├── README.md
    │   └── STORY_TEMPLATE.md
    └── tasks/
        ├── README.md
        └── TASK_TEMPLATE.md
```

The project's source code, assets, and supporting files live beside these
documents in the same project workspace.

## Role Model

- `AgentSmith`: discussion, challenge, clarification, routing
- `Architect`: document-driven project management and validation
- `Morpheus`: software execution orchestration
- `Oracle`: technical validation and truth-checking

## Notes

- Keep the project documents factual and current.
- Prefer updating `management/STATUS.md` after every meaningful change.
- Use story and task templates consistently so the agents can reason about
  status and ownership without guessing.
