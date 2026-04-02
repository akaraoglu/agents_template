# Workspace PROJECT.md

This file is for **workspace-level coordination** in the shared OpenClaw +
Zulip template workspace.

It is **not** the main charter for a specific shipped project.

For real project work, use:
- `projects/<slug>/PROJECT.md` as the strong top-level project charter
- `projects/<slug>/management/MILESTONES.md` for milestone gates
- `projects/<slug>/management/BACKLOG.md` for prioritized work
- `projects/<slug>/management/STATUS.md` for current truth
- `projects/<slug>/management/DECISIONS.md` for durable decisions
- `projects/<slug>/management/RISKS.md` for the risk register

## Purpose

This workspace exists to hold:
- shared agent runtime files
- shared Zulip gateway setup
- shared prompts, wrappers, and control-plane documents
- reusable project scaffolds

Use this file to describe:
- what this shared workspace is for
- how projects are selected
- what project is currently active when running locally
- what global constraints or defaults apply across projects

## Workspace Summary

- Workspace role: shared OpenClaw + Zulip control workspace
- Primary use: reusable template and local host runtime for multi-project work
- Main users: human operators plus visible roles such as `Neo`, `AgentSmith`,
  `Niaobe`, `Architect`, `Morpheus`, `Oracle`, and `Yoda`

## Current Active Project Selection

When running locally, document the currently active project here:

- Active project slug:
- Active project root:
- Why this project is active right now:

If there is no active project, say so explicitly.

## Shared Defaults

Document only cross-project defaults here:
- runtime model
- gateway model
- default visible roles
- shared sandbox or host execution rules
- shared communication rules

Do not put detailed project scope or milestone content here.

## Shared Role Model

- `Neo`: CTO-level direct-execution assistant
- `AgentSmith`: front door, intake, discussion, routing
- `Niaobe`: project manager and project-loop owner
- `Architect`: planning and documentation
- `Morpheus`: software execution manager
- `Oracle`: validation and QA
- `Yoda`: advisory critique and second opinion

## Shared Operating Rules

- visible handoffs should stay in Zulip
- detailed execution belongs in project-local files
- project-specific planning belongs under `projects/<slug>/management/`
- this workspace file should stay stable and relatively short

## Recommended Project Document Model

For each project, prefer this structure:

- `PROJECT.md`
  - stable charter and operating model
  - purpose, scope, goals, constraints, success criteria
  - role model, loops, quality gates, major architecture notes

- `management/MILESTONES.md`
  - milestone plan and exit criteria

- `management/BACKLOG.md`
  - prioritized work inventory

- `management/STATUS.md`
  - current state, blockers, and next action

- `management/DECISIONS.md`
  - durable decisions

- `management/RISKS.md`
  - risk register and assumptions

## Optional SDP

`AGENTIC_SOFTWARE_DEVELOPMENT_PLAN_TEMPLATE.md` is optional.

Use it only when a project is large enough to need a separate operating-plan
document in addition to the normal charter and management files.

For most projects in this system, a stronger project-local `PROJECT.md` plus the
management files above is the preferred default.
