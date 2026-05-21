# Agentic Team Project: Architecture, Setup, and Replication Manual

This document provides a comprehensive technical blueprint and installation guide for replicating the **autonomous local agentic software development team** on another machine. It is designed to be fully readable and actionable by both human engineers and agentic AI systems.

---

## 1. System Overview & Objectives
The **Agentic Team** is a fully localized, multi-agent software development department. Rather than a single monolithic agent, it leverages a collaborative network of specialized AI agents working asynchronously. 

The primary objective of the system is to take a raw feature request/specification, design it, write clean code, discover and run unit tests, verify results against acceptance criteria, and deliver a production-ready package with 100% autonomy.

```
                    +-----------------------+
                    |  Client / Human / Neo |
                    +-----------+-----------+
                                |
                                v
                    +-----------------------+
                    |  Smith (Planning GM)  | <---------+
                    +-----------+-----------+           |
                                |                       | (Next Task Increment)
                                v                       |
                    +-----------------------+           |
                    | Niaobe (Project PM)   | ----------+
                    +-----------+-----------+
                                |
           +--------------------+--------------------+
           |                    |                    |
           v                    v                    v
+--------------------+ +--------------------+ +--------------------+
| Architect (Design) | | Morpheus (Build)   | |  Oracle (QA/Test)  |
+--------------------+ +--------------------+ +--------------------+
```

---

## 2. Technical Stack & Components
The system is built on four core layers, all running **entirely on a single local workstation** (no external API calls):

1.  **The Reasoning Engine (Local LLM)**: 
    *   **Technology**: [Ollama](https://ollama.com/) running locally.
    *   **Model**: `gemma4:26b` (a powerful, reasoning-optimized model that handles large context windows and structured JSON generation).
2.  **The Agent Framework & Control Plane**:
    *   **Technology**: **OpenClaw** gateway. OpenClaw runs as a local daemon, loading agent prompts, managing tool configurations, orchestrating agent execution runs, and persisting trajectories.
    *   **State & Cache Store**: **Redis** (running locally), storing active gateway caches, trajectories, and tool output outcomes.
3.  **The Communication Layer**:
    *   **Technology**: Local **Mattermost** server.
    *   **Interaction**: Inter-agent communication, intake triggers, status logs, and task handoffs are executed via Mattermost Direct Messages (DMs) and project channels using bot account tokens.
4.  **The Workspace & Tooling Layer**:
    *   **Technology**: Python 3, Bash, standard CLI tools.
    *   **Execution**: Each agent is allocated an isolated directory structure (`workspaces/<agent_name>`) and utilizes localized, project-rooted shell scripts to read/write files and run unit tests securely.

---

## 3. OpenClaw Engine: Tools, Skills, and MCP Architecture
OpenClaw is the backbone of the agent coordination plane. It provides sandboxed environments, implements prompt templates (skills), parses LLM outputs, executes designated tools, and handles the direct message routing loop.

### A. The Tooling System (Core Tooling Whitelist)
Each agent is configured inside `~/.openclaw/openclaw.json` with a strict whitelist of native tools. This guarantees that workers are physically restricted to tasks within their boundaries:

*   **`read`**: A high-efficiency, localized tool allowing agents to view specific lines of any file inside their assigned workspace.
*   **`write`**: Allows the agent to write raw contents to a localized file path (e.g. drafting design blueprints or source modules).
*   **`exec` (Guarded Execution)**: Allows worker agents to execute shell scripts on the host (e.g., executing `verify_artifact.sh` or running unit tests via `project_exec.sh`). 
    *   *Security/Safety Boundary*: Direct arbitrary bash commands are blocked. Execution commands must match prefix and parameter structures registered in `AgenticTeam/config/exec-approvals.json` (such as pytest, unittest, or approved helper scripts).
*   **`sessions_send` & `sessions_spawn` (Inter-Agent Communications)**:
    *   Unlike classical setups that poll Slack or Mattermost in expensive loops, OpenClaw provides a native **Agent-to-Agent Session Messaging Protocol**.
    *   `sessions_send` allows an agent to bypass Mattermost entirely for core runtime handoffs, posting structured JSON execution envelopes directly into another active agent's background session runtime queue.
    *   `sessions_spawn` (where allowed) allows parent agents to instantiate temporary sub-agents with specific prompt overlays.

### B. Cognitive Templates (Skills)
OpenClaw supports **Skills**—specialized prompt and constraint templates injected into the agent's baseline context window before reasoning begins.
*   **`plan-mode`**: Equipped on all agents in this team. It injects a standardized, goal-oriented reasoning framework that forces the agent to explicitly research the workspace, plan file and code changes as distinct diff blocks, verify its own work using automated self-checks, and write a structured summary before concluding a turn.

### C. MCP (Model Context Protocol) Servers
*   **Current Architecture**: The team currently uses **native, localized OpenClaw execution tools** (`exec`, `read`, `write`) instead of external MCP servers to keep dependencies minimal and execution fast.
*   **Replication Note**: If you choose to integrate external MCP servers (such as a database client or filesystem crawler) in your target environment, OpenClaw exposes an MCP client interface inside `openclaw.json` using the standard JSON-RPC over stdio/SSE protocol:
    ```json
    "mcpServers": {
      "sqlite-mcp": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sqlite", "--db", "/path/to/db"]
      }
    }
    ```
    Once defined, tools exposed by the MCP server automatically populate the whitelisted tools available to the selected agents.

### D. Mattermost Communication Layer (Human & Agent Boundary)
Mattermost serves as the **outer envelope** of the agentic team:
1.  **Human/Client Intake**: An external client or `@neo` posts a structured message containing requirements into a specific project channel (like `#projects`).
2.  **State Telemetry & Logging**: Agents call `project_write.sh` or logging hooks to report major milestones (e.g., "Planning complete", "Build verified") directly to public Mattermost channels for human oversight.
3.  **Out-of-Loop Handoffs**: While execution loops use direct session messaging internally for speed, initial project handoffs (such as Neo initiating Smith, or final project closures) utilize the Mattermost DM API using bot access tokens.

---

## 4. The Agent Roster & Collaboration Protocol

### Agent Roles
| Agent | Mattermost Handle | Role in Team | Primary Inputs | Primary Outputs |
| :--- | :--- | :--- | :--- | :--- |
| **Neo** | `@neo` | Intake & Interface | User Prompt | Project Specs, Intake Trigger |
| **Smith** | `@smith` | General Manager | Specification | `PLAN.md`, `BACKLOG.md`, task specifications |
| **Niaobe** | `@niaobe` | Project Manager | Handoff Envelopes | `PROJECT_STATE.md` updates, task allocations |
| **Architect** | `@architect` | Designer | Task Specification | `management/architecture/T001.md` (Design doc) |
| **Morpheus** | `@morpheus` | Implementer | Architecture Plan | Source files (`src/`), unit tests (`tests/`) |
| **Oracle** | `@oracle` | QA/Verifier | Completed Code | `management/validation/T001_REPORT.md` (Verdict) |

### Coordination via Handoff Envelopes
Agents do not communicate using unstructured chat. They communicate strictly using **JSON Handoff Envelopes** sent via Mattermost DMs. This prevents context drift and ensures strict telemetry tracking.

```json
{
  "project_id": "line-tally-20260520-2309",
  "from": "niaobe",
  "to": "morpheus",
  "phase": "IMPLEMENT",
  "task_id": "T001",
  "instructions": "Implement task T001 using CURRENT_TASK.md, management/tasks/T001.md, and management/architecture/T001.md. Report DONE or BLOCKED."
}
```

### The State Ledger Engine (`PROJECT_STATE.md`)
The single source of truth for any active project is the `PROJECT_STATE.md` file saved in the project's root folder.
*   **State transition rules**: Only `@smith` and `@niaobe` are permitted to update `PROJECT_STATE.md`.
*   **Ownership handoff**: `@smith` owns the pre-planning phase. Once `@smith` generates the backlog, ownership transitions to `@niaobe` (setting `owner: niaobe` in the markdown).
*   **Task-scoped execution**: Only one task (`active_task`) can be executed at any time. When a task completes, ownership goes back to `@smith` to plan the next increment or close the project.

---

## 5. Replicating the System: Step-by-Step Installation

Follow these steps to fully replicate this environment on a clean Linux computer.

### Step 1: System Prerequisites
Ensure the target machine has the necessary runtime dependencies installed:
```bash
sudo apt-get update
sudo apt-get install -y git curl python3 python3-pip python3-venv redis-server build-essential jq
```
Ensure Redis is running:
```bash
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

### Step 2: Install and Configure Ollama
1.  Install Ollama:
    ```bash
    curl -fsSL https://ollama.com/install.sh | sh
    ```
2.  Pull the required model (ensure your system has at least 16GB RAM to run a 26B model comfortably):
    ```bash
    ollama pull gemma4:26b
    ```

### Step 3: Install Mattermost locally
1.  Download and extract the local Mattermost developer/production package:
    ```bash
    tar -xvzf mattermost-team-tar.gz
    ```
2.  Configure database bindings (Mattermost defaults to PostgreSQL or a local SQLite cache for developer instances).
3.  Start Mattermost on the standard loopback: `http://localhost:8065`.
4.  **Create Bot Accounts**: Create six users/bot accounts in Mattermost (`neo`, `smith`, `niaobe`, `architect`, `morpheus`, `oracle`).
5.  **Generate Tokens**: Enable Personal Access Tokens in Mattermost System Console, and generate a token for each bot account.

### Step 4: Configure OpenClaw Gateway
1.  Download/clone the OpenClaw Gateway runtime.
2.  Create the default configuration directory:
    ```bash
    mkdir -p ~/.openclaw/agents
    ```
3.  Create the primary gateway configuration file `~/.openclaw/openclaw.json` mapping agent accounts to their respective model configurations. **Crucial configuration settings**:
    ```json
    {
      "modelProviders": {
        "ollama": {
          "url": "http://127.0.0.1:11434"
        }
      },
      "agents": {
        "smith": {
          "model": "gemma4:26b",
          "provider": "ollama",
          "contextWindow": 131072
        },
        "niaobe": {
          "model": "gemma4:26b",
          "provider": "ollama"
        },
        "architect": {
          "model": "gemma4:26b",
          "provider": "ollama"
        },
        "morpheus": {
          "model": "gemma4:26b",
          "provider": "ollama"
        },
        "oracle": {
          "model": "gemma4:26b",
          "provider": "ollama"
        }
      }
    }
    ```

### Step 5: Setup Workspaces and Script Files
Clone the Agentic Team repository (this template workspace) into `~/workspace/agent_template_new`.
Ensure the `.env` file exists under `AgenticTeam/` and contains the Mattermost integration tokens:
```ini
MM_URL="http://localhost:8065"
MM_NEO_TOKEN="your_neo_pat_token"
MM_SMITH_TOKEN="your_smith_pat_token"
MM_NIAOBE_TOKEN="your_niaobe_pat_token"
MM_ARCHITECT_TOKEN="your_architect_pat_token"
MM_MORPHEUS_TOKEN="your_morpheus_pat_token"
MM_ORACLE_TOKEN="your_oracle_pat_token"
```

Sync the canonical agent prompts, workspace instructions, and allowed executive scripts into live OpenClaw directories:
```bash
cd ~/workspace/agent_template_new
bash AgenticTeam/scripts/sync_agents.sh --apply
```

---

## 6. Standard Operating Procedures & Tooling

### Workspace Syncing (`sync_live_openclaw.py`)
Agents run inside sandboxed folders (`/home/alik/workspace/clawspace/workspaces/<agent_name>`). To ensure agent behaviors remain uniform:
*   The developer writes the canonical system prompts under `AgenticTeam/agents/<agent_name>/*.md`.
*   Running `sync_agents.sh --apply` triggers `sync_live_openclaw.py`, which overlays system configurations, copies fresh prompt surfaces into OpenClaw's active configurations, and populates the agent's workspaces safely.

### Telemetry Dashboard (`team_status.sh`)
Execute the telemetry script to inspect active runs, last-posted agent statuses, and active project phases:
```bash
bash AgenticTeam/scripts/team_status.sh
```

---

## 7. Operational Playbook & Troubleshooting

### Problem: Stalled or Frozen Agent Sessions
*   **Symptoms**: An agent gets locked (`.jsonl.lock` exists in their session folder), runs out of context, or halts silently.
*   **Solution**:
    1.  Verify if the model is set to `gemma4:26b`. Ensure the local Ollama registry contains this model name cleanly.
    2.  Clear locks and reset the session:
        ```bash
        bash AgenticTeam/scripts/reset_project.sh <project_id>
        ```
    3.  Inspect active sessions in `/home/alik/.openclaw/agents/<agent_name>/sessions/` and verify the trajectory JSONL file size.

### Problem: State Write Collisions
*   **Symptoms**: Stale writes from previous agent runs overwriting current state.
*   **Solution**:
    *   Ensure all writes go through `write_state.sh` which enforces `--actor` and `--expect-owner` checks to maintain clear ownership transitions.

---

## 8. Comprehensive Deep-Dive: The Eight Architectural Layers

To understand how this system operates autonomously without context drift, data leaks, or unconstrained command execution, the agentic team is structured into eight distinct, interdependent operational layers. 

```
                                  +---------------------------------------+
                                  |    Layer 7: Mattermost Boundary       | <--- (Human / Neo Intake)
                                  +-------------------+-------------------+
                                                      |
                                                      v
                                  +-------------------+-------------------+
                                  |    Layer 2: OpenClaw Orchestration    | <--- (Redis State Cache)
                                  +---------+-------------------+---------+
                                            |                   |
                     +----------------------+                   +---------------------+
                     v                                                                v
        +------------+------------+                                      +------------+------------+
        | Layer 1: Ollama LLM     |                                      | Layer 3: Inter-Agent    |
        | Reasoning (Gemma4)      |                                      | Sessions (sessions_send)|
        +-------------------------+                                      +-------------------------+
                     |                                                                |
                     v                                                                v
        +------------+------------+                                      +------------+------------+
        | Layer 4: OpenClaw Skills|                                      | Layer 5: Tooling & MCP  |
        | (plan-mode state machine)|                                     | (read, write, sqlite)   |
        +-------------------------+                                      +-------------------------+
                                                                                      |
                                                                                      v
                                                                         +------------+------------+
                                                                         | Layer 6: Guardrails     |
                                                                         | (exec-approvals allowlist)|
                                                                         +------------+------------+
                                                                                      |
                                                                                      v
                                                                         +------------+------------+
                                                                         | Layer 8: Local Workspace|
                                                                         | (workspaces/ & scripts) |
                                                                         +-------------------------+
```

### Layer 1: Cognitive & Reasoning Layer (The Local LLM)
*   **Core Engine**: Ollama running locally.
*   **Model**: `gemma4:26b` (Reasoning-optimized, large context architecture).
*   **Specifications**:
    *   **Context Window**: Bounded at `131,072` tokens via `openclaw.json` configuration to comfortably handle extensive trajectory histories, multi-file code diffs, and multiple prompt imports.
    *   **JSON Enforcement**: Instructed to strictly output structured thoughts and formal Tool Call payloads, ensuring reliable interaction with the control plane.
*   **Role**: Serves as the cognitive heart. It does not run scripts, write files, or speak directly to users. It processes the conversation transcript and system inputs to decide what step to take next.

### Layer 2: Orchestration & Gateway Control Plane (OpenClaw Daemon)
*   **Gateway Service**: OpenClaw gateway daemon.
*   **State & Telemetry Store**: Bounded to **Redis** (running locally), caching runtime variables, active subagent runs (in `~/.openclaw/subagents/runs.json`), session locks, and trajectory logs.
*   **Operational Core**:
    *   Bootstraps the agents by loading their unique md-based system surfaces (`AGENT.md`, `SKILLS.md`, `TOOLS.md`).
    *   Translates LLM response packages into safe execution runs. If the LLM proposes a tool call, OpenClaw halts inference, executes the tool on the host, registers the output in the outcome cache, and appends the result to the LLM's next-turn context.
    *   Maintains isolation by preventing agents from accessing another's active trajectory logs directly.

### Layer 3: Inter-Agent Session Messaging Layer (Fast-Loop Intercom)
*   **Core Mechanics**:
    *   Classical agent workflows communicate via slow HTTP webhooks (like Slack/Mattermost channels) using expensive polling loops.
    *   This system uses OpenClaw's native **Agent-to-Agent Sessions Protocol** (`sessions_send`, `sessions_spawn`, `sessions_list`, `sessions_history`).
*   **Functionality**:
    *   Allows worker agents to bypass external message APIs completely during runtime pipeline loops.
    *   `sessions_send` posts structured JSON envelopes directly into another active agent's workspace session queue (`agent:<target_agent>:main`).
    *   **Benefits**: Slashes handoff latencies from minutes to milliseconds, contains context within clean JSON execution payloads, and avoids spamming public team channels with micro-level execution telemetry.

### Layer 4: Injected Behavior & Constraints Layer (OpenClaw Skills)
*   **Technology**: OpenClaw unified **Skills** (System prompt templates injected dynamically into the LLM system prompt envelope).
*   **Primary Template**: `plan-mode` (configured under `AgenticTeam/skills/plan-mode/SKILL.md`).
*   **State Machine Enforced**:
    1.  **PLAN Mode**: Read-only workspace investigation. The agent must research the filesystem, verify requirements, and end with a `[PLAN]` summary block.
    2.  **PROPOSE Mode**: The agent proposes exact file modifications (inline diffs) or specific commands under `[PROPOSE]` and waits for manager/user approval.
    3.  **EXECUTE Mode**: Entered only after receiving explicit manager/user confirmation keywords ("approved", "go", "do it"). Label actions with `[EXECUTE]`.
*   **Escalation Logic**: Enforces uniform behavior when encountering failures: the agent must freeze execution, draft a standardized `BLOCKED_REPORT.md` (reusing `AgenticTeam/templates/BLOCKED_REPORT.md`), and DM their direct manager immediately.

### Layer 5: Tooling & Extensibility Layer (Native API & MCP Servers)
*   **Native Tools**:
    *   `read`: High-efficiency, scoped file-reader preventing workspace leaks.
    *   `write`: Bounded file-writer to construct files safely before deployment.
    *   `exec`: Sandboxed shell runner on the local system.
*   **MCP (Model Context Protocol) Integration**:
    *   **What it is**: An open standard protocol designed by Anthropic enabling LLMs to safely read/write structured context from databases, filesystems, and developer environments using JSON-RPC over stdio or SSE.
    *   **OpenClaw MCP Client**: OpenClaw acts as an MCP client. If an external data layer is required (e.g. searching code repositories, indexing SQLite schema, fetching API specifications), the server is declared in `~/.openclaw/openclaw.json` under `"mcpServers"`.
    *   **Runtime Action**: When OpenClaw starts, it spawns the declared MCP server subprocesses, fetches their tool schemas via JSON-RPC, and dynamically registers these tools into the selected agent's allowed whitelist.

### Layer 6: Security and Execution Guardrails Layer (The Sandbox Protection)
*   **Configuration Ledger**: Bounded inside `AgenticTeam/config/exec-approvals.json`.
*   **Mechanics**:
    *   Protects the host workstation from arbitrary code execution.
    *   When an agent calls `exec`, the OpenClaw control plane checks the command string against the allowlist pattern-matcher inside `exec-approvals.json`.
    *   Direct shell commands (e.g., raw `mkdir`, `cat`, `rm -rf`) are blocked by default.
    *   **Allowed Vectors**: Only approved project-relative shell wrappers under `/home/alik/workspace/clawspace/bin/` are allowed (e.g. `project_read.sh`, `project_write.sh`, `project_exec.sh`, `verify_artifact.sh`).
*   **Shared State Guarding**: Transition helpers like `write_state.sh` enforce `--actor` and `--expect-owner` parameters. If a worker tries to write state when it is not the active owner of `PROJECT_STATE.md`, the write is rejected at the execution layer.

### Layer 7: Boundary Communication & Interface Layer (Mattermost)
*   **Communication Gateway**: A local Mattermost instance (`http://localhost:8065`).
*   **Intake & Initial Trigger**:
    *   Humans or `@neo` post project requests directly to public `#projects` channels.
    *   `new_project.sh` creates the structured workspace, and an initial handoff DM via Mattermost API activates `@smith`.
*   **Milestone Broadcasting**:
    *   Internal execution is silent and fast. But when major phases complete (e.g. Planning, Design, Build, QA), agents call `mm_post.sh` to broadcast success to `#status` or `#alerts` channels.
    *   Allows human operators to monitor pipeline progress without digging into raw Redis or JSONL logs.

### Layer 8: Local Workspace & Script Execution Layer (The Shell Sandbox)
*   **Workspace Bounding**:
    *   Agents are separated into dedicated workspaces under `/home/alik/workspace/clawspace/workspaces/<agent_name>`.
    *   Worker agents maintain a `drafts/` directory where they write drafts before importing them.
*   **Project Workspace**:
    *   All active projects are placed under `/home/alik/workspace/clawspace/projects/active/<project_id>`.
*   **System Wrappers**:
    *   `resolve_project.sh`: Obtains the path to the active project workspace.
    *   `project_read.sh` / `project_write.sh`: Enforces correct relative-path file actions within the resolved project path.
    *   `project_exec.sh`: Runs specific build and test environments (like `pytest` or compiler scripts) strictly inside the project root, keeping agents completely out of standard host binaries.

---

## 9. Detailed Project Workspace Schema

Every project initialized by `@neo` or `new_project.sh` creates a standardized directory layout and tracking schema under `/home/alik/workspace/clawspace/projects/active/<project_id>`. This structured tree ensures that workers write artifacts to deterministic folders, and that managers can audit active states at any instant.

### A. Directory Tree Structure
```
/home/alik/workspace/clawspace/projects/active/<project_id>/
├── PROJECT_STATE.md               # Canonical project state ledger
├── CURRENT_TASK.md                # Active task work order details
├── PROJECT.md                     # Raw initial requirements specification
├── src/                           # Source directory for all production modules
├── tests/                         # Automated unit test modules
└── management/                    # Project control records
    ├── tasks/                     # Task specifications (T001.md, etc.) created by Smith
    ├── architecture/              # Architectural design blueprints created by Architect
    └── validation/                # QA verification reports created by Oracle
```

### B. Canonical State Ledger (`PROJECT_STATE.md`)
The `PROJECT_STATE.md` file serves as the absolute state machine. It is written to exclusively by `@smith` and `@niaobe` using `write_state.sh` to prevent race conditions.

```markdown
# Project State — line-tally-20260520-2309

## Overview
- **schema_version**: 2
- **project_id**: line-tally-20260520-2309
- **title**: Line Tally Feature
- **created**: 2026-05-21T09:20:00Z
- **owner**: niaobe                     # Transitioned from smith after handoff ack

## Status
- **phase**: BUILD                      # PLANNING | DESIGN | BUILD | QA | DONE
- **active_task**: T001                 # Bounded active task identifier
- **task_phase**: IMPLEMENT             # DESIGN | IMPLEMENT | VERIFY | none
- **task_status**: pending              # none | pending | success | failed
- **current_agent**: morpheus            # Active agent executing active_task
- **waiting_for**: morpheus             # Next agent required in path
- **blocked_count**: 0
- **blocked_reason**: none
- **last_completed_task**: none
- **last_task_result**: none
```

### C. Active Work Order Ledger (`CURRENT_TASK.md`)
This file is generated by the active manager to define the exact boundaries of the currently scheduled execution turn.

```markdown
# Current Task — line-tally-20260520-2309

## Task Envelope
- **project_id**: line-tally-20260520-2309
- **task_id**: T001
- **status**: running
- **owner**: morpheus

## Objective
Implement line-tally command line arguments and options parser.

## Inputs
- management/tasks/T001.md
- management/architecture/T001.md

## Deliverables
- src/args.py
- src/parser.py

## Completion Signal
- MORPHEUS posts DONE report via direct session send to NIAOBE.
```

---

## 10. Complete Shell Helper & Sandbox Tooling Directory

To run commands on the local host securely under `exec-approvals.json`, the agents do not write raw Bash syntax. They call a predefined directory of structured shell wrappers located in `/home/alik/workspace/clawspace/bin/`.

### A. Filesystem and Scoping Helpers

#### 1. `resolve_project.sh`
*   **Signature**: `bash resolve_project.sh "<PROJECT_ID>"`
*   **Description**: Locates the project inside the active projects directory and returns its absolute path on stdout. If the project does not exist, it exits with non-zero.
*   **Approval Target**: Whitelisted for all worker agents to allow directory discovery.

#### 2. `project_read.sh`
*   **Signature**: `bash project_read.sh "<PROJECT_ID>" "<relative_path>"`
*   **Description**: Safely opens and outputs the contents of a file inside the resolved project root. Prevents directory traversal attacks (`../` is blocked).
*   **Approval Target**: Whitelisted for all agents.

#### 3. `project_mkdir.sh`
*   **Signature**: `bash project_mkdir.sh "<PROJECT_ID>" "<relative_dir>"`
*   **Description**: Scopes folder creation within the project tree. Bypasses absolute directory creation checks.
*   **Approval Target**: Whitelisted for Architect and Morpheus.

#### 4. `project_write.sh`
*   **Signature**: `bash project_write.sh "<PROJECT_ID>" "<project_relative_path>" --source-file "<local_draft_path>"`
*   **Description**: Writes raw file changes into the project tree securely. Takes a draft file prepared inside the agent's isolated workspace (e.g. `workspaces/morpheus/drafts/`) and deploys it.
*   **Approval Target**: Whitelisted for Architect, Morpheus, and Oracle.

#### 5. `project_exec.sh`
*   **Signature**: `bash project_exec.sh "<PROJECT_ID>" "<actor_name>" <command...>`
*   **Description**: Executes approved validation, compiler, or runner scripts (such as `pytest`, `unittest`, or build wrappers) strictly within the project root. Bypasses standard shell shells.
*   **Approval Target**: Whitelisted for Morpheus and Oracle.

### B. Orchestration & Control Helpers

#### 6. `verify_artifact.sh`
*   **Signature**: `bash verify_artifact.sh "<PROJECT_ID>" "<PHASE>" "<relative_artifact_path>" --action "<action_id>"`
*   **Description**: Automates checks on newly generated files. Validates that files exist, are non-empty, compile cleanly, and match structured formatting before yielding progress. Outputs `OUTCOME_JSON` containing `{"status": "OK"}` or `{"status": "FAILED"}` schemas.
*   **Approval Target**: Whitelisted for all workers (Architect, Morpheus, Oracle).

#### 7. `write_state.sh`
*   **Signature**:
    ```bash
    bash write_state.sh --project-id "<id>" --actor "<agent>" --expect-owner "<owner>" [--set-owner "<new_owner>"] [--phase "<phase>"] [--active-task "<task>"] [--task-phase "<task_phase>"] [--waiting-for "<agent>"]
    ```
*   **Description**: Updates fields in `PROJECT_STATE.md`. It strictly verifies that the `--actor` matches the `--expect-owner`. If Niaobe has taken ownership, any attempt by Smith to write state is rejected.
*   **Approval Target**: Whitelisted for Smith and Niaobe.

#### 8. `handoff.sh`
*   **Signature**: `bash handoff.sh "<PROJECT_ID>" "<FROM>" "<TO>" "<PHASE>" "<TASK_ID>" "<INSTRUCTIONS>"`
*   **Description**: Packages a message envelope, updates state parameters, and enqueues a handoff receipt tracking registry to guarantee queue synchronization.
*   **Approval Target**: Whitelisted for Smith and Niaobe.

#### 9. `ack_handoff.sh`
*   **Signature**: `bash ack_handoff.sh "<PROJECT_ID>" "<FROM>" "<PHASE>" "<TASK_ID>"`
*   **Description**: Executed by the recipient to acknowledge receipt of an active work order, resolving pending receipt states in telemetry logs.
*   **Approval Target**: Whitelisted for Niaobe and worker agents.

---

## 11. Deployment & Sync Pipeline (`sync_live_openclaw.py`)

To ensure development configurations, system prompts, and workspace limits remain uniform across environments, the team uses a centralized Python deployment script: `AgenticTeam/scripts/sync_live_openclaw.py`.

### A. Sync Manifest Configuration
The sync process is completely manifest-driven, reading configurations from `AgenticTeam/config/live_openclaw_sync_manifest.json`:

```json
{
  "version": 1,
  "paths": {
    "agenticteam_root": "/home/alik/workspace/agent_template_new/AgenticTeam",
    "openclaw_root": "/home/alik/.openclaw",
    "workspace_root": "/home/alik/workspace/clawspace/workspaces"
  },
  "agent_dir_managed_files": [
    "AGENT.md",
    "IDENTITY.md",
    "SKILLS.md",
    "SOUL.md"
  ],
  "agents": {
    "smith": {
      "workspace_files": ["AGENTS.md", "HEARTBEAT.md", "IDENTITY.md", "SOUL.md", "TOOLS.md", "USER.md"],
      "agent_dir_files": ["AGENT.md", "IDENTITY.md", "SKILLS.md", "SOUL.md"]
    }
  }
}
```

### B. Integrity & Security Checks
Before deploying any configuration live, the sync script executes three validation gates:
1.  **Forbidden Token Scan**: Scans all prompt markdown files for legacy absolute paths (like `/home/alik/workspace/clawspace/projects/active/`) or outdated tool references (like `read_file` or `write_file`). If detected, the sync exits with a validation error.
2.  **Prompt-to-Helper Alignment Check**: Parses the agent's prompts to extract shell script references (e.g. `/home/alik/workspace/clawspace/bin/write_state.sh`). It cross-checks these references against the `TOOLS.md` whitelist to ensure consistency.
3.  **Exec Guard Validation**: Verifies that every shell script mentioned in the agent prompts is explicitly allowlisted under that agent's list inside `config/exec-approvals.json`. This blocks configuration drift that could trigger local command rejections during active runs.

---

## 12. Cognitive Reporting Templates

To report progress without introducing unstructured chat drift, worker agents are required to output structured markdown blocks when concluding a turn.

### A. DONE Report Template (`DONE_REPORT.md`)
Every successful turn must end with a DONE report injected directly into the direct session message payload:

```markdown
# DONE Report: T001

- **project_id**: line-tally-20260520-2309
- **task_id**: T001
- **phase**: IMPLEMENT
- **status**: success
- **artifacts**:
  - src/args.py
  - src/parser.py
- **summary**: Parser logic successfully written, imported to workspace, and validated via local pytest suite (12 tests passed).
```

### B. BLOCKED Report Template (`BLOCKED_REPORT.md`)
If a dependency is missing, a tool fails, or requirements are logically conflicting, the agent must immediately freeze work and file a BLOCKED report:

```markdown
# BLOCKED Report: T001

- **project_id**: line-tally-20260520-2309
- **task_id**: T001
- **phase**: IMPLEMENT
- **status**: blocked
- **reason**: Required dependency package 'yaml' is missing from host python interpreter environment.
- **evidence**: 'project_exec.sh' python3 args.py failed with ModuleNotFoundError: No module named 'yaml'.
- **needs**: Human administrator to install requirements.txt packages.
```
