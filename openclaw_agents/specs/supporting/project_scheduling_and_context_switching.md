# project_scheduling_and_context_switching.md

This document defines how the agentic software-development system schedules, pauses, resumes, and switches between multiple projects.

- This spec extends `agentic_workflow.md`, `zulip_communication_spec.md`, and the software workspace contract.
- The YAML block under **Authoritative Spec** is the source of truth.
- This spec is designed for **serial multi-project execution with context switching**, not unrestricted parallel project execution.
- **Niobe** and **Morpheus** are treated as singleton orchestrators unless explicitly upgraded in a future version.
- **Zulip remains transport and audit only**. Scheduling state lives in the authoritative state store.

## Authoritative Spec

```yaml
spec_version: "1.0.0"
metadata:
  spec_id: "project_scheduling_and_context_switching"
  name: "Project Scheduling and Context Switching"
  last_updated: "2026-04-02"
  authoritative: true
  owners: ["MASTER"]
  description: "Scheduling, queueing, pause/resume, and active-project switching rules for the multi-project agentic software workflow."

scope:
  in_scope:
    - "serial multi-project execution"
    - "active-project locks"
    - "pause and resume semantics"
    - "safe switching boundaries"
    - "priority-aware queueing"
    - "workspace isolation rules"
    - "state snapshot requirements"
    - "Niobe and Morpheus scheduling behavior"
  out_of_scope:
    - "fully parallel project orchestration by one singleton orchestrator"
    - "cross-project dependency optimization"
    - "distributed multi-runner load balancing"
    - "market-style agent bidding"

core_decision:
  execution_model: "multiple projects may exist concurrently, but singleton orchestrators handle one active project at a time"
  scheduler_model: "central control-plane scheduler with authoritative state store"
  source_of_truth:
    project_state: "orchestrator_state_store"
    task_state: "orchestrator_state_store"
    scheduling_state: "orchestrator_state_store"
    artifacts: "artifact_store"
    communication: "zulip_transport_only"
  lock_model: "explicit active-project lease per singleton orchestrator"
  workspace_model: "one isolated workspace or git worktree per project context"
  switch_policy: "only switch at persisted safe boundaries"

principles:
  - "A paused project must be resumable without reading Zulip history."
  - "A project switch is a state transition, not a chat habit."
  - "Singleton orchestrators may own many projects over time but only one active project at a time."
  - "Scheduling decisions must be explicit, persisted, and inspectable."
  - "Unsafe mid-run switching is prohibited unless an operator forces interruption and accepts recovery risk."
  - "Workspace isolation is required for reliable switching."
  - "Priority matters, but starvation prevention matters too."
  - "Humans must be able to pause, resume, cancel, and reprioritize projects explicitly."

enums:
  project_runtime_statuses:
    - "NEW"
    - "READY"
    - "ACTIVE"
    - "PAUSE_REQUESTED"
    - "PAUSED"
    - "WAITING_EXTERNAL"
    - "WAITING_VERIFICATION"
    - "BLOCKED"
    - "DONE"
    - "CANCELLED"
  orchestrator_ids:
    - "niobe"
    - "morpheus"
  lease_statuses:
    - "FREE"
    - "HELD"
    - "EXPIRED"
    - "RELEASING"
  switch_reasons:
    - "MANUAL_PRIORITY_CHANGE"
    - "CURRENT_PROJECT_WAITING_EXTERNAL"
    - "CURRENT_PROJECT_BLOCKED"
    - "CURRENT_PROJECT_AT_SAFE_BOUNDARY"
    - "PREEMPTED_BY_URGENT_PROJECT"
    - "OPERATOR_REQUEST"
    - "SYSTEM_RECOVERY"
  safe_boundary_types:
    - "TASK_COMPLETED"
    - "TASK_RESULT_PERSISTED"
    - "ESCALATION_PERSISTED"
    - "ORACLE_REPORT_PERSISTED"
    - "MORPHEUS_DELIVERY_PERSISTED"
    - "PROJECT_STATUS_SNAPSHOT_PERSISTED"
  scheduler_commands:
    - "PAUSE_PROJECT"
    - "RESUME_PROJECT"
    - "SWITCH_PROJECT"
    - "CANCEL_PROJECT"
    - "REPRIORITIZE_PROJECT"
    - "FORCE_INTERRUPT"
    - "STATUS_SNAPSHOT"
  scheduling_priorities:
    - "LOW"
    - "MEDIUM"
    - "HIGH"
    - "URGENT"

entities:
  project_record:
    required_fields:
      - "project_id"
      - "project_status"
      - "priority"
      - "current_phase"
      - "current_owner_agent"
      - "assigned_project_orchestrator"
      - "assigned_software_orchestrator"
      - "next_action"
      - "workspace_ref"
      - "last_snapshot_id"
      - "last_activity_at"
  scheduling_record:
    required_fields:
      - "project_id"
      - "queue_state"
      - "eligible_for_scheduling"
      - "pause_requested"
      - "resume_requested"
      - "preemption_allowed"
      - "waiting_reason"
      - "last_scheduled_at"
      - "times_scheduled"
  orchestrator_lease:
    required_fields:
      - "orchestrator_id"
      - "lease_status"
      - "active_project_id"
      - "lease_owner_run_id"
      - "lease_acquired_at"
      - "lease_expires_at"
  project_snapshot:
    required_fields:
      - "snapshot_id"
      - "project_id"
      - "captured_at"
      - "captured_by"
      - "project_status"
      - "current_phase"
      - "open_tasks"
      - "next_action"
      - "workspace_ref"
      - "artifact_refs"
      - "latest_human_summary"

scheduler:
  owner: "control_plane"
  responsibilities:
    - "choose which project a singleton orchestrator should work on next"
    - "enforce active-project leases"
    - "persist pause, resume, and switch commands"
    - "refuse unsafe switch attempts"
    - "prevent one orchestrator from holding multiple active projects simultaneously"
    - "record fairness and starvation-prevention metadata"
    - "expose inspectable project queue state"
  mode: "priority_queue_with_eligibility_filters"
  default_selection_policy:
    ordered_rules:
      - "exclude DONE and CANCELLED projects"
      - "exclude projects not eligible_for_scheduling"
      - "exclude projects missing required workspace_ref or state snapshot"
      - "prefer URGENT over HIGH over MEDIUM over LOW"
      - "prefer resumed projects that were preempted at safe boundaries"
      - "prefer older waiting projects over newly created ones within the same priority"
      - "prefer projects with explicit human resume request over passive backlog items"
  starvation_prevention:
    enabled: true
    rule: "If a lower-priority eligible project has not been scheduled within the configured fairness window, the scheduler may advance it unless an URGENT project is active."
  fairness_window:
    default_minutes: 240

leasing:
  lease_required_for_execution: true
  singleton_orchestrators:
    niobe:
      max_active_projects: 1
      lease_ttl_minutes: 30
      renew_interval_minutes: 5
    morpheus:
      max_active_projects: 1
      lease_ttl_minutes: 60
      renew_interval_minutes: 10
  rules:
    - "A singleton orchestrator must hold a valid lease before performing active work on a project."
    - "An orchestrator lease must reference exactly one active project_id."
    - "Lease renewal requires that the run is still healthy and state snapshots are still being persisted."
    - "Expired leases return the project to schedulable state after recovery checks."
    - "A new project cannot be assigned until the old lease is released or expired."

pause_resume_switch:
  safe_default: "switch only after a persisted safe boundary"
  pause:
    command: "PAUSE_PROJECT"
    behavior:
      - "mark pause_requested = true"
      - "allow current task to finish if already running"
      - "persist final boundary snapshot"
      - "release active lease"
      - "set project_status = PAUSED"
  resume:
    command: "RESUME_PROJECT"
    behavior:
      - "mark resume_requested = true"
      - "place project back in eligible scheduler queue"
      - "load last_snapshot_id when lease acquired"
      - "continue from next_action, not from a reconstructed chat guess"
  switch:
    command: "SWITCH_PROJECT"
    required_steps:
      - "validate current project at safe boundary or require FORCE_INTERRUPT"
      - "persist project snapshot"
      - "release current lease"
      - "acquire next project lease"
      - "load workspace and state"
      - "emit switch audit event"
  cancel:
    command: "CANCEL_PROJECT"
    behavior:
      - "persist cancellation reason"
      - "release lease if held"
      - "set project_status = CANCELLED"
  force_interrupt:
    command: "FORCE_INTERRUPT"
    warning: "Use only when human operator accepts possible partial work, replay, or rollback needs."
    required_follow_up:
      - "mark project_status = PAUSE_REQUESTED or BLOCKED"
      - "persist interrupted run metadata"
      - "require recovery assessment before resume"

safe_boundaries:
  general_rules:
    - "A safe boundary exists only after state and artifact references are persisted."
    - "Posting a message to Zulip alone is not a safe boundary."
    - "A running sandbox without persisted outputs is not a safe boundary."
  niobe_boundaries:
    - "after charter validation decision is persisted"
    - "after architect result is persisted"
    - "after morpheus delivery package is persisted"
    - "after oracle verification report is persisted"
    - "after escalation packet is persisted"
    - "after project status snapshot is persisted"
  morpheus_boundaries:
    - "after planner output is persisted"
    - "after implementer output is persisted"
    - "after tester report is persisted"
    - "after delivery package is persisted"
    - "after architecture clarification response is persisted"
  prohibited_switch_points:
    - "mid-LLM generation without checkpoint"
    - "mid-command execution inside a sandbox"
    - "mid-git mutation with untracked rollback state"
    - "before test results are recorded when code has already changed"

project_queue_model:
  queue_buckets:
    urgent: "human or system-flagged urgent items"
    active_recovery: "projects resuming from pause or crash"
    normal_ready: "ready projects without active blockers"
    waiting_external: "projects waiting for humans, Oracle, or external inputs"
    blocked: "projects that cannot proceed without escalation or repair"
  eligibility_rules:
    ready_for_niobe:
      - "project_status in [NEW, READY, ACTIVE, PAUSED]"
      - "assigned_project_orchestrator == niobe"
      - "required charter or snapshot data present"
    ready_for_morpheus:
      - "project_status in [ACTIVE, PAUSED, READY]"
      - "software next_action exists"
      - "workspace_ref exists"
      - "architecture inputs available or not required"
  queue_visibility:
    required_views:
      - "all projects by priority"
      - "projects waiting for human input"
      - "projects paused and resumable"
      - "projects currently leased"
      - "projects blocked by environment or infrastructure"

niobe_scheduling:
  role: "project-level singleton scheduler consumer"
  rules:
    - "Niobe may manage many projects over time but holds one active project lease at a time."
    - "Niobe chooses next project actions only for the currently leased project."
    - "Niobe must persist a project status snapshot before releasing a project."
    - "Niobe may request Morpheus work, but Morpheus scheduling is independent once the task is assigned."
    - "Niobe may switch away from a project when it becomes WAITING_EXTERNAL, WAITING_VERIFICATION, PAUSED, BLOCKED, or after a safe project boundary."
  recommended_switch_triggers:
    - "Oracle verification in progress"
    - "Escalation pending human decision"
    - "Morpheus task in progress and Niobe has no immediate local action"
    - "Project explicitly paused"
    - "Higher-priority eligible project arrives"

morpheus_scheduling:
  role: "software-level singleton scheduler consumer"
  rules:
    - "Morpheus may manage many software tasks across many projects over time but holds one active project lease at a time."
    - "Morpheus must complete Planner, Implementer, and Tester steps with persisted boundaries before switching."
    - "Morpheus should not switch projects while an implementation or test run is actively mutating the workspace."
    - "Morpheus must return a persisted delivery package or persisted blocker before releasing a project lease."
  recommended_switch_triggers:
    - "Tester report persisted and next action requires Niobe or Architect"
    - "Environment failure persisted and escalated"
    - "Project paused or preempted at a safe software boundary"
    - "Higher-priority software request becomes eligible and current project is safely parked"

workspace_isolation:
  required: true
  strategy:
    preferred: "dedicated project workspace or git worktree per project"
    acceptable_mvp: "single dedicated workspace directory per project with serialized mutation"
    forbidden: "multiple projects sharing one mutable working directory during switching"
  required_fields:
    - "workspace_ref"
    - "repo_root"
    - "branch_or_worktree_id"
    - "last_clean_commit_or_checkpoint"
  rules:
    - "Before switching away after code mutation, the system must persist artifact refs and record workspace state."
    - "Before resuming a project, the scheduler must verify the referenced workspace exists and is internally consistent."
    - "Recovery actions may include checkout, worktree rebuild, patch reapply, or sandbox rebuild."

snapshot_policy:
  mandatory_snapshots:
    - "after every accepted task result"
    - "after every escalation"
    - "before releasing a lease"
    - "after pause command is completed"
    - "after resume command acquires context"
    - "after Oracle report is recorded"
    - "after Morpheus delivery package is recorded"
  snapshot_contents:
    - "project_status"
    - "current_phase"
    - "current_owner_agent"
    - "next_action"
    - "open_tasks"
    - "latest_artifact_refs"
    - "workspace_ref"
    - "human-readable summary"

human_control_surface:
  supported_commands:
    PAUSE_PROJECT:
      required_args: ["project_id"]
    RESUME_PROJECT:
      required_args: ["project_id"]
    SWITCH_PROJECT:
      required_args: ["from_project_id", "to_project_id", "orchestrator_id"]
    CANCEL_PROJECT:
      required_args: ["project_id", "reason"]
    REPRIORITIZE_PROJECT:
      required_args: ["project_id", "priority"]
    FORCE_INTERRUPT:
      required_args: ["project_id", "orchestrator_id", "reason"]
    STATUS_SNAPSHOT:
      required_args: ["project_id"]
  recommended_access:
    - "MASTER"
    - "authorized operators"
    - "Niobe for project-level pause/escalation actions within policy"
  audit_requirement: "Every command must create an immutable control event record."

zulip_interaction:
  role: "communication and audit"
  rules:
    - "Pause, resume, switch, cancel, and reprioritize events may be mirrored to Zulip for visibility."
    - "Zulip mirror messages must reference project_id and control event id."
    - "The scheduler never derives truth from unread Zulip history."
    - "Project switching should keep conversation in the same project topic unless escalation or secrecy requires otherwise."
  recommended_topics:
    project_status: "project/{project_id}"
    project_switch_audit: "project/{project_id}/decisions"
    escalation: "project/{project_id}/escalate/{task_id}"

failure_and_recovery:
  failure_modes:
    - "lease expired while run still alive"
    - "sandbox crashed mid-task"
    - "workspace inconsistent on resume"
    - "state snapshot missing"
    - "duplicate scheduler assignment"
    - "forced interruption without clean boundary"
  recovery_rules:
    - "No project may resume without a valid last known snapshot or explicit recovery override."
    - "If workspace validation fails, mark project BLOCKED and emit recovery escalation."
    - "If duplicate lease detected, scheduler must freeze the project and require operator review."
    - "If interrupted mid-mutation, the system must run workspace recovery before resuming normal execution."

observability:
  required_metrics:
    - "projects_paused_total"
    - "projects_resumed_total"
    - "project_switches_total"
    - "unsafe_switch_attempts_total"
    - "lease_acquire_failures_total"
    - "lease_expirations_total"
    - "workspace_recovery_events_total"
    - "scheduler_queue_depth"
    - "oldest_waiting_project_age_seconds"
  required_logs:
    - "control commands"
    - "lease acquire and release"
    - "snapshot creation"
    - "switch decisions"
    - "recovery actions"

implementation_targets:
  builder_agent_must_generate:
    - "project scheduler service or module"
    - "active-project lease manager"
    - "pause/resume/switch command handlers"
    - "project snapshot serializer"
    - "workspace validation and recovery hooks"
    - "scheduler queue inspection views"
    - "control-plane audit event schema"
    - "Zulip audit mirroring for control events"
  recommended_repo_layout:
    - "specs/project_scheduling_and_context_switching.md"
    - "scheduler/project_scheduler.py"
    - "scheduler/lease_manager.py"
    - "scheduler/queue_policy.py"
    - "scheduler/control_commands.py"
    - "scheduler/snapshot_store.py"
    - "scheduler/workspace_validator.py"
    - "scheduler/recovery_manager.py"
    - "schemas/control_event.schema.json"
    - "schemas/project_snapshot.schema.json"
    - "schemas/orchestrator_lease.schema.json"
    - "schemas/project_schedule_record.schema.json"
  acceptance_criteria_for_builder_agent:
    - "The system can track many projects while assigning at most one active Niobe lease and one active Morpheus lease at a time."
    - "A project can be paused and resumed without reading Zulip history."
    - "Switching projects requires persisted boundary state unless FORCE_INTERRUPT is explicitly used."
    - "Workspace isolation is enforced per project."
    - "The scheduler can show why a project is not currently eligible to run."
    - "The system can recover from expired leases and restart from snapshots."
```

## Human-readable summary

### What this update adds

This update adds the missing control-plane behavior for handling **multiple projects over time** without pretending the singleton orchestrators can do several things at once.

It defines:
- how many projects can exist in the system,
- how one project becomes the active project for Niobe or Morpheus,
- how a project is paused,
- how a project is resumed,
- how the system safely switches from one project to another,
- what data must be saved before switching,
- how workspaces stay isolated.

### Core operating model

The system supports:
- many projects existing concurrently in the database,
- one active project for **Niobe** at a time,
- one active project for **Morpheus** at a time,
- explicit switching between projects at safe boundaries,
- persistence-based resume instead of chat-history reconstruction.

This means the system behaves like a disciplined serial executor, not a fake-concurrent chaos engine.

### Why this spec is needed

Without an explicit scheduling and context-switching spec, a multi-project system usually fails in predictable ways:
- one orchestrator gets assigned to two projects by accident,
- a project is "paused" but nothing durable was saved,
- a workspace gets reused for the wrong project,
- human priority changes are not enforceable,
- resuming means rereading Zulip and hoping the messages tell the truth.

This spec fixes that by making switching a first-class state transition.

### Practical rules to keep

1. **Only switch at safe boundaries.**
2. **Always snapshot before release.**
3. **Never share one mutable workspace across projects.**
4. **Keep one active lease per singleton orchestrator.**
5. **Treat pause/resume/switch as control-plane commands, not conversational habits.**

### Recommended first implementation scope

Build only this first:
- central scheduler,
- lease manager,
- pause/resume/switch commands,
- project snapshots,
- per-project workspace isolation,
- queue inspection view.

Do not jump straight to parallel multi-project execution. That is how you earn a great deal of logging and very little progress.

## Suggested integration changes

Add this spec to the main repository alongside:
- `agentic_workflow.md`
- `zulip_communication_spec.md`
- `SOFTWARE_WORKSPACE_README.md`

Then update the consolidated master workflow document to reference this spec as the scheduling layer.
