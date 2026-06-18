# Public Contracts

CodexTeam public contracts are the stable shapes intended for scripts, future MCP tools, loopback HTTP UI, external operators, and bounded leader orchestration.

## Compatibility Policy

- Adding an optional field is allowed in the same major version.
- Removing a field is a breaking change.
- Renaming a field is a breaking change.
- Changing the meaning of a field is a breaking change.
- Changing required timestamp or ID formats is a breaking change.
- Adding enum values requires consumers to tolerate unknown values or a deliberate version bump.
- Internal state-store records are not public contracts unless named in this document.

## Board Summary Contract

Schema name: `codexteam.board.summary`

Schema version: `1.0`

Required metadata:

- `schema_name`
- `schema_version`
- `generated_at`
- `team_id`
- `snapshot_id`
- `source_state_revision`

Required sections:

- `team`
- `agents`
- `tasks`
- `runs`
- `attempts`
- `worker_results`
- `requested_actions`
- `review_decisions`
- `approvals`
- `workspaces`
- `review_queue`
- `pending_approvals`
- `risks`

`source_state_revision` is derived from audit state and identifies the state revision observed by the read model.

## Board Detail Contracts

Detail schemas use `codexteam.board.detail.<kind>` with version `1.0`.

All detail outputs include:

- `schema_name`
- `schema_version`
- `generated_at`
- `team_id`
- `detail_kind`
- `item_id`
- `source_state_revision`
- `data`

For backward compatibility, fields inside `data` are also exposed at the top level.

## Controller Command Contracts

Controller command contracts use version `1.0`.

Current public command contracts:

- `create_team`
- `approve_plan`
- `create_task`
- `run_worker`
- `approve_review`
- `reject_review`

Adapters must call controller APIs or operator command handlers. They must not mutate state files directly.

## Leader Decision Records

`LeaderDecision` records are public audit evidence for bounded autonomous orchestration.

Required fields include:

- `id`
- `team_id`
- `leader_agent_id`
- `observed_snapshot_id`
- `decision_type`
- `input_facts`
- `chosen_action`
- `reason`
- `risk_level`
- `created_requested_actions`
- `created_tasks`
- `affected_attempts`
- `produced_at`

The leader loop may create tasks, request worker-start approvals, start already-approved attempts, aggregate completed worker evidence, and request approval. It must stop at review and approval gates.

## Read-Only Rule

Board/read-model code may read, project, validate, and format state.

Board/read-model code must not:

- save records
- append audit records
- decide approvals
- decide reviews
- execute workspace actions
- apply change proposals
- cleanup workspaces
- mutate policy

Mutation must flow through controller-owned commands.
