# Agent Operational Rules (Leader's Memory)

## 1. Workspace Hierarchy & Separation of Concerns
*   **Platform Layer (`docs/`):** Permanent architectural documentation for CodexTeam development.
*   **Agent Layer (`.agents/`):** Real-time operational constraints, self-improvement logs, and execution logic used by the Agent.
*   **Project Layer (`projects/<name>/` or `codexspace_a/projects/<name>/`):** All task-specific source code, tests, and SDD artifacts.

## 2. Mandatory Workspace Path (The "Single Source of Truth")
All active project work must be executed within:
`/home/alik/workspace/agent_template/codexteam/codexspace_a/`

**Never default to the root workspace (`.../codexteam/`) for project-specific work.**

## 3. Project Isolation Rule
Every new project must have its own dedicated subdirectory. Do not pollute the root or the `agents/` directory with project files.

## 4. Permission Protocol
If any operation (e.g., writing to `.agents/`) requires escalated privileges or fails due to "Read-only" constraints, I must use the `justification` parameter in `exec_command` to ask for permission to attempt an escalation or seek user intervention.
