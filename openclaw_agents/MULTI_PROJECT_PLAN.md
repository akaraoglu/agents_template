# Multi-Project Runtime Plan

This document defines how to evolve the current OpenClaw and Zulip setup from a
single-project workspace into one shared runtime that can serve multiple
projects cleanly.

## Goal

Keep one generic agent runtime and one generic Zulip integration, while moving
project-specific state into reusable per-project folders built from
`project_template/`.

## Problem With The Current Shape

The current shape assumes one active `PROJECT.md` at the workspace root. That is
fine for a single project, but it causes two problems once one AgentSmith needs
to help across multiple projects:

- project context is mixed into the shared control workspace
- AgentSmith and other roles are tempted to read one project's `PROJECT.md`
  even when the discussion is generic or belongs to a different project

## Target Split

### Global, Shared Runtime

These stay in the shared control workspace:
- `.agents/`
- `.agents/project_registry.json`
- shared OpenClaw prompts and role definitions
- shared OpenClaw wrapper scripts
- shared Docker and sandbox setup
- Zulip bridge code and bot wiring
- global runtime state and logs
- future project registry and active-project selection state

### Per-Project Workspace

These move into each project folder:
- `PROJECT.md`
- `management/`
- project source code and assets
- project-specific notes or outputs
- any project-local tests, configs, and supporting docs

## Recommended Folder Layout

```text
YOUR_AGENT_HOME/
├── .agents/
├── zulip/
├── projects/
│   ├── project-alpha/
│   │   ├── PROJECT.md
│   │   └── management/
│   └── project-beta/
│       ├── PROJECT.md
│       └── management/
└── shared/
```

`project_template/` should be copied into each `projects/<project-slug>/`
folder as the initial document scaffold.

## Recommended Role Behavior

- `AgentSmith`: global by default, project-agnostic until a specific project is
  selected or a project-scoped question is asked
- `Architect`: reads and writes project documents for the selected project
- `Morpheus`: executes software work against the selected project workspace
- `Oracle`: validates technical truth against the selected project workspace

## What To Move Out Of The Single-Project Root

When converting a single-project workspace to the multi-project model, move:
- the root `PROJECT.md`
- `management/`
- any project-specific task notes
- any project-specific acceptance or planning files

Do **not** move:
- `.agents/`
- shared prompt files
- shared bridge code
- shared OpenClaw template config
- shared sandbox state roots

## Next Runtime Step

The natural next runtime change is a project registry and active-project
selection layer.

Recommended future commands:
- `/project list`
- `/project use <slug>`
- `/project status`
- `/project clear`

Recommended shared registry assets:
- `.agents/project_registry.example.json`
- `.agents/project_registry.json` (local, untracked)
- `.agents/scripts/project_registry.py`

This keeps AgentSmith generic by default while still letting Architect,
Morpheus, and Oracle work against the correct project when needed.

## Migration Checklist

1. Keep the shared control workspace generic.
2. Create `projects/<slug>/` from `project_template/`.
3. Move project documents into that project folder.
4. Move or point the software codebase into the same project folder.
5. Add the project to the future registry.
6. Make AgentSmith load project context only on demand, not on every message.
