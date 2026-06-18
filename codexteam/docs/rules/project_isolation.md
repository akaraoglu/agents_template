# Mandatory Project Encapsulation

## Purpose
To maintain workspace hygiene, prevent environment pollution, and ensure that multiple projects can coexist without interference or file name collisions.

## Rule
All work related to a specific project (source code, tests, documentation, and SDX artifacts) **must** be contained within its own dedicated subdirectory created at the start of Phase 1.

## Standard Operating Procedure
1.  **Initialization:** The very first step of any new project must be the creation of a unique project directory under a `projects/` or similar container (e.g., `./projects/project-name/`).
2.  **Context Switching:** All subsequent commands, `cd` operations, and file writes for that project must occur strictly within this subdirectory.
3.  **Workspace Hygiene:** The root workspace (`/home/alik/workspace/agent_template/codexteam`) is reserved exclusively for orchestration metadata, configuration, and the `projects/` container. It must **never** contain project-specific source code or documentation.

## Mandatory Workspace Path
**The primary working context for all active projects and teams is strictly defined as:**
`/home/alik/workspace/agent_template/codexteam/codexspace_a/`

*   **All new `projects/` must be initialized within this path.**
*   **All new `teams/` must be initialized within this path.**

Never default to the root workspace (`.../codexteam/`) for project-specific work.
