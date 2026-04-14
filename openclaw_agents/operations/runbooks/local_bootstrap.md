# Local Bootstrap

Use this runbook to stand up one local project workspace and make it schedulable by the control plane.

## Runtime Boundary

Treat this repository as template-only. Put live runtime state under `/home/alik/workspace/claw_software_workspace`, not under `openclaw_agents/`.

Recommended layout:

- `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/env/`
- `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/db/`
- `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/runtime/`
- `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/zulip_gateway/`
- `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/zuliprc/`
- `/home/alik/workspace/claw_software_workspace/projects/`

Committed env examples:

- [openclaw-runtime-workers.env.example](/home/alik/workspace/agent_template/openclaw_agents/operations/examples/openclaw-runtime-workers.env.example)
- [openclaw-zulip-gateway.env.example](/home/alik/workspace/agent_template/openclaw_agents/operations/examples/openclaw-zulip-gateway.env.example)

## Preconditions

- Run commands from the repository root.
- Use one isolated workspace directory per project.
- Pick a persistent SQLite path for `OPENCLAW_DB_PATH`.
- Fill the workspace documents before marking the project eligible for scheduling.

## 1. Create The Project Workspace

```bash
cp -R openclaw_agents/templates/project_workspace /abs/path/my_project_workspace
```

Replace every placeholder in:

- `/abs/path/my_project_workspace/PROJECT.md`
- `/abs/path/my_project_workspace/management/STATUS.md`
- `/abs/path/my_project_workspace/management/MILESTONES.md`
- `/abs/path/my_project_workspace/management/BACKLOG.md`
- `/abs/path/my_project_workspace/management/DECISIONS.md`
- `/abs/path/my_project_workspace/management/TEST_REPORT.md`

## 2. Initialize The Control-Plane Database

```bash
export OPENCLAW_DB_PATH=/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/db/control_plane.sqlite3
sqlite3 "$OPENCLAW_DB_PATH" < openclaw_agents/database/schema.sql
```

## 3. Seed The Project, Scheduling, And Workspace Records

Edit the placeholders in this snippet before running it.

```bash
python3 - <<'PY'
from openclaw_agents.database.store import ControlPlaneStore, utc_now

store = ControlPlaneStore()
now = utc_now()
project_id = "replace_me"
workspace_ref = "/abs/path/my_project_workspace"
repo_root = "/abs/path/my_project_workspace"
branch_or_worktree_id = "main"
last_checkpoint = "replace_with_commit_or_named_checkpoint"

store.upsert(
    "projects",
    {
        "project_id": project_id,
        "goal": "replace_me",
        "project_status": "NEW",
        "runtime_status": "READY",
        "priority": "MEDIUM",
        "current_phase": "intake",
        "current_owner_agent": "agent_smith",
        "assigned_project_orchestrator": "niobe",
        "assigned_software_orchestrator": "morpheus",
        "next_action_json": {"type": "FRAME_PROJECT"},
        "workspace_ref": workspace_ref,
        "last_snapshot_id": None,
        "last_activity_at": now,
        "updated_at": now,
    },
    conflict_columns=["project_id"],
)

store.upsert(
    "scheduling_records",
    {
        "project_id": project_id,
        "queue_state": "normal_ready",
        "eligible_for_scheduling": True,
        "pause_requested": False,
        "resume_requested": False,
        "preemption_allowed": True,
        "waiting_reason": None,
        "last_scheduled_at": None,
        "times_scheduled": 0,
    },
    conflict_columns=["project_id"],
)

store.upsert(
    "workspace_states",
    {
        "workspace_ref": workspace_ref,
        "project_id": project_id,
        "repo_root": repo_root,
        "branch_or_worktree_id": branch_or_worktree_id,
        "last_clean_commit_or_checkpoint": last_checkpoint,
        "is_consistent": True,
    },
    conflict_columns=["workspace_ref"],
)

print(store.get_project(project_id))
print(store.get_scheduling_record(project_id))
print(store.get_workspace_state(workspace_ref))
PY
```

## 4. Validate Workspace And Scheduling Readiness

```bash
python3 - <<'PY'
from openclaw_agents.database.store import ControlPlaneStore
from openclaw_agents.scheduler.project_scheduler import ProjectScheduler
from openclaw_agents.scheduler.workspace_validator import WorkspaceValidator

store = ControlPlaneStore()
project_id = "replace_me"

print(WorkspaceValidator(store).validate_project(project_id))
print(ProjectScheduler(store).inspect_queue("niobe"))
PY
```

The workspace must validate cleanly before you resume or schedule the project.

## 5. Gateway Smoke Check

You can validate both the normalization layer and the daemon surface locally.

```bash
python3 - <<'PY'
from openclaw_agents.communication.zulip_gateway import GatewayEvent, ZulipGateway

gateway = ZulipGateway()
event = GatewayEvent(
    message_id="bootstrap-smoke-1",
    sender_name="MASTER",
    sender_type="human",
    stream_name="projects",
    topic_name="project/replace_me",
    content="Please frame and start this project.",
)
result = gateway.handle_inbound_event(event)
print(result.status)
print(result.summary)
print(result.task_id)
PY
```

Optional daemon config check:

```bash
export OPENCLAW_REPO_ROOT=$PWD
export OPENCLAW_GATEWAY_CONFIG=$PWD/openclaw_agents/communication/zulip_gateway_config.yaml
export OPENCLAW_ZULIPRC_DIR=/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/zuliprc
export OPENCLAW_ZULIP_GATEWAY_STATE_DIR=/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/zulip_gateway
python3 -m openclaw_agents.communication.zulip_gateway_service --config "$OPENCLAW_GATEWAY_CONFIG" --check
```

## 6. Runtime Dispatch And Response Callback

If a task already exists in the control-plane store, you can queue it for runtime execution manually:

```bash
python3 -m openclaw_agents.runtime.dispatcher dispatch-task --task-id <task_id>
```

This writes a task packet into the project workspace hidden runtime directory `.agents/runtime/incoming/` when `workspace_ref` exists, or into the gateway state queue when it does not.

With the Phase 2 split, project-local task state, artifacts, task attempts, runs, control events, snapshots, recovery data, and Zulip links live in `project/.agents/project.db`. The shared database remains a scheduler registry for projects, scheduling records, and orchestrator leases.

When an external runner finishes, persist its response envelope back into the state store:

```bash
python3 -m openclaw_agents.runtime.dispatcher record-response --file /abs/path/response.yaml
```

That callback updates:

- `task_attempts`
- `agent_runs`
- `tasks`
- `projects`
- `artifacts`
- `project_snapshots` when a workspace-backed safe boundary exists

## 7. Worker Runner

The worker side consumes queued runtime packets and produces response envelopes.

By default, [worker_config.yaml](/home/alik/workspace/agent_template/openclaw_agents/runtime/worker_config.yaml) is conservative and leaves every agent executor disabled. That prevents the template from auto-completing real work until you intentionally configure a runner.

Process one queued run with the mock executor for local smoke testing:

```bash
python3 -m openclaw_agents.runtime.worker_runner --agent implementer --default-executor mock --once
```

Process one queued run with the built-in deterministic executor for the software loop:

```bash
python3 -m openclaw_agents.runtime.worker_runner --agent morpheus --default-executor builtin --once
```

The built-in executor currently supports `agent_smith`, `niobe`, `architect`, `morpheus`, `oracle`, `planner`, `implementer`, and `tester`. It is useful for control-plane smoke tests because it advances the visible project loop and the nested Morpheus software loop, persists artifacts, and requeues parent tasks automatically after child-task completion.

Run a configured worker continuously:

```bash
python3 -m openclaw_agents.runtime.worker_runner --agent implementer
```

Validate the enabled worker fleet before starting supervised services:

```bash
python3 -m openclaw_agents.runtime.worker_supervisor --config openclaw_agents/runtime/worker_config.yaml --check
```

Run one supervised child process per enabled agent from `worker_config.yaml`:

```bash
python3 -m openclaw_agents.runtime.worker_supervisor --config openclaw_agents/runtime/worker_config.yaml
```

For real execution, update `runtime/worker_config.yaml` so the target agent uses the `subprocess` executor with a command that reads `OPENCLAW_TASK_PACKET` and writes `OPENCLAW_RESPONSE_FILE`.

For prompt-aware external execution, use the `prompt_subprocess` executor instead. If you do not provide an explicit command, the worker now falls back to the built-in [ollama_prompt_runner.py](/home/alik/workspace/agent_template/openclaw_agents/runtime/ollama_prompt_runner.py), which reads the execution context and calls the local Ollama HTTP API at `127.0.0.1:11434` using the model configured by `OPENCLAW_MODEL_HINT`.

For real code-changing software execution, use the `openclaw_workspace` executor for `implementer` and `tester`. That backend:

- provisions a dedicated OpenClaw agent per project workspace and role
- binds that agent to a hidden OpenClaw workspace under `project/.agents/openclaw/workspace`
- exposes the visible project tree through that hidden workspace so code changes still land in the real project
- runs the task through `openclaw agent --json`
- requires the agent to return one structured JSON result
- derives changed files from workspace state before and after the run

Minimal software-loop config:

```yaml
agents:
  implementer:
    executor: openclaw_workspace
    thinking: medium
  tester:
    executor: openclaw_workspace
    thinking: minimal
```

The host running the workers must have a usable OpenClaw install and writable `~/.openclaw` state, because `openclaw_workspace` provisions per-workspace agents on first use.

The committed model map pins all local Ollama profiles to `gemma4:31b` in [model_map.yaml](/home/alik/workspace/agent_template/openclaw_agents/config/model_map.yaml). That means a minimal real-execution config only needs:

```yaml
agents:
  architect:
    executor: prompt_subprocess
```

If you want a different backend, keep `executor: prompt_subprocess` and set an explicit `command`.

If you need to bypass the HTTP API and use the Ollama CLI instead, set `OPENCLAW_OLLAMA_TRANSPORT=cli` for that worker process.

The prompt-aware path writes a structured JSON context file and exports:

- `OPENCLAW_EXECUTION_CONTEXT`
- `OPENCLAW_PROMPT_PATH`
- `OPENCLAW_MODEL_PROFILE`
- `OPENCLAW_MODEL_RUNTIME`
- `OPENCLAW_MODEL_HINT`
- the existing `OPENCLAW_TASK_PACKET`, `OPENCLAW_RESPONSE_FILE`, `OPENCLAW_TASK_ID`, `OPENCLAW_PROJECT_ID`, `OPENCLAW_AGENT_ID`, `OPENCLAW_WORKSPACE_REF`, and `OPENCLAW_RUN_ID`

The subprocess must still return a valid response envelope, either by writing `OPENCLAW_RESPONSE_FILE` or by printing YAML or JSON to stdout.

## 8. Worker Services

The committed worker service units are:

- [openclaw-worker-supervisor.service](/home/alik/workspace/agent_template/openclaw_agents/operations/systemd/openclaw-worker-supervisor.service) for the default fleet pattern
- [openclaw-worker@.service](/home/alik/workspace/agent_template/openclaw_agents/operations/systemd/openclaw-worker@.service) for pinning one role to one long-running process

The live env file should live under `/home/alik/workspace/claw_software_workspace/.agents/state/openclaw_agents/env/openclaw-runtime-workers.env`.

The committed example is [openclaw-runtime-workers.env.example](/home/alik/workspace/agent_template/openclaw_agents/operations/examples/openclaw-runtime-workers.env.example).

That env file should define at least:

- `OPENCLAW_REPO_ROOT`
- `OPENCLAW_WORKER_CONFIG`
- `OPENCLAW_DB_PATH`

Optional but usually useful:

- `OPENCLAW_RUNTIME_STATE_DIR`
- `OLLAMA_HOST`
- `OPENCLAW_OLLAMA_TRANSPORT`
- `PATH` including the `openclaw` CLI when using `openclaw_workspace`

Recommended pattern:

1. Enable executors for the visible or internal roles you actually want in [worker_config.yaml](/home/alik/workspace/agent_template/openclaw_agents/runtime/worker_config.yaml).
2. Run `python3 -m openclaw_agents.runtime.worker_supervisor --config "$OPENCLAW_WORKER_CONFIG" --check`.
3. Start `openclaw-worker-supervisor.service`.

Use `openclaw-worker@architect.service` only when you intentionally want a dedicated single-agent worker outside the shared supervisor pattern.

## 9. Run The Automated Tests

The committed regression tests use the Python standard library test runner so they do not require `pytest` to be installed:

```bash
python3 -m unittest discover -s tests -v
```
