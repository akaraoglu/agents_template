PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
  project_id TEXT PRIMARY KEY,
  goal TEXT NOT NULL DEFAULT '',
  project_status TEXT NOT NULL CHECK (
    project_status IN ('NEW', 'ACTIVE', 'VERIFICATION_PENDING', 'DONE', 'BLOCKED', 'CANCELLED')
  ),
  runtime_status TEXT NOT NULL CHECK (
    runtime_status IN (
      'NEW',
      'READY',
      'ACTIVE',
      'PAUSE_REQUESTED',
      'PAUSED',
      'WAITING_EXTERNAL',
      'WAITING_VERIFICATION',
      'BLOCKED',
      'DONE',
      'CANCELLED'
    )
  ),
  priority TEXT NOT NULL CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')),
  current_phase TEXT NOT NULL,
  current_owner_agent TEXT CHECK (
    current_owner_agent IN (
      'master',
      'neo',
      'agent_smith',
      'niobe',
      'architect',
      'morpheus',
      'oracle',
      'planner',
      'implementer',
      'tester'
    )
  ),
  assigned_project_orchestrator TEXT NOT NULL CHECK (assigned_project_orchestrator = 'niobe'),
  assigned_software_orchestrator TEXT NOT NULL CHECK (assigned_software_orchestrator = 'morpheus'),
  next_action_json TEXT NOT NULL DEFAULT '{}',
  workspace_ref TEXT,
  last_snapshot_id TEXT,
  last_activity_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  parent_task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
  from_agent TEXT NOT NULL,
  to_agent TEXT NOT NULL,
  current_owner_agent TEXT NOT NULL,
  return_to TEXT NOT NULL,
  task_type TEXT NOT NULL CHECK (
    task_type IN (
      'CLARIFY_GOAL',
      'FRAME_PROJECT',
      'APPROVE_PRIORITY',
      'RESOLVE_ESCALATION',
      'ORCHESTRATE_PROJECT',
      'DESIGN_ARCHITECTURE',
      'REQUEST_ARCHITECTURE_CLARIFICATION',
      'ORCHESTRATE_SOFTWARE',
      'PLAN_SOFTWARE_TASK',
      'IMPLEMENT_SOFTWARE_TASK',
      'TEST_SOFTWARE_TASK',
      'VERIFY_PROJECT',
      'CLOSE_PROJECT'
    )
  ),
  title TEXT NOT NULL,
  goal TEXT NOT NULL,
  priority TEXT NOT NULL CHECK (priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')),
  status TEXT NOT NULL CHECK (
    status IN ('PENDING', 'RUNNING', 'SUCCESS', 'NEEDS_CLARIFICATION', 'BLOCKED', 'FAILED', 'CANCELLED')
  ),
  context_json TEXT NOT NULL DEFAULT '{}',
  expected_output_json TEXT NOT NULL DEFAULT '{}',
  decision_bounds_json TEXT NOT NULL DEFAULT '{}',
  opened_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  closed_at TEXT
);

CREATE TABLE IF NOT EXISTS task_attempts (
  attempt_id TEXT PRIMARY KEY,
  task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL,
  attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
  status TEXT NOT NULL CHECK (
    status IN ('PENDING', 'RUNNING', 'SUCCESS', 'NEEDS_CLARIFICATION', 'BLOCKED', 'FAILED', 'CANCELLED')
  ),
  failure_cause TEXT CHECK (
    failure_cause IN (
      'BAD_PLAN',
      'IMPLEMENTATION_DEFECT',
      'TEST_GAP',
      'ARCHITECTURE_GAP',
      'REQUIREMENT_GAP',
      'ENVIRONMENT_FAILURE',
      'UNKNOWN'
    )
  ),
  sandbox_id TEXT,
  workspace_ref TEXT,
  input_artifact_refs_json TEXT NOT NULL DEFAULT '[]',
  output_artifact_refs_json TEXT NOT NULL DEFAULT '[]',
  summary TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_runs (
  run_id TEXT PRIMARY KEY,
  task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  agent_id TEXT NOT NULL,
  model_profile TEXT NOT NULL,
  model_used TEXT,
  runtime_backend TEXT NOT NULL,
  sandbox_id TEXT,
  session_id TEXT,
  result_status TEXT CHECK (
    result_status IN ('PENDING', 'RUNNING', 'SUCCESS', 'NEEDS_CLARIFICATION', 'BLOCKED', 'FAILED', 'CANCELLED')
  ),
  raw_transcript_ref TEXT,
  log_ref TEXT,
  started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ended_at TEXT,
  duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
  produced_by_agent TEXT,
  artifact_type TEXT NOT NULL CHECK (
    artifact_type IN (
      'clarification_brief',
      'project_charter',
      'project_status_report',
      'architecture_spec',
      'software_task_plan',
      'code_change',
      'test_execution_report',
      'software_delivery_package',
      'verification_report',
      'escalation_packet',
      'executive_decision',
      'project_closure_report'
    )
  ),
  store_backend TEXT NOT NULL CHECK (
    store_backend IN ('artifact_store', 'workspace', 'inline_json', 'external_ref')
  ),
  ref TEXT NOT NULL,
  content_hash TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS decisions (
  decision_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
  decided_by TEXT NOT NULL,
  decision_type TEXT NOT NULL,
  summary TEXT NOT NULL,
  rationale TEXT NOT NULL,
  constraints_json TEXT NOT NULL DEFAULT '{}',
  next_owner TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS escalations (
  escalation_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
  owner_agent TEXT NOT NULL,
  reason TEXT NOT NULL,
  blocking_facts_json TEXT NOT NULL DEFAULT '[]',
  options_considered_json TEXT NOT NULL DEFAULT '[]',
  recommended_action_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL CHECK (status IN ('OPEN', 'RESOLVED', 'REJECTED')) DEFAULT 'OPEN',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  resolved_at TEXT,
  resolution_summary TEXT
);

CREATE TABLE IF NOT EXISTS zulip_message_links (
  link_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  task_id TEXT REFERENCES tasks(task_id) ON DELETE SET NULL,
  control_event_id TEXT,
  zulip_message_id TEXT NOT NULL UNIQUE,
  stream_name TEXT NOT NULL,
  topic_name TEXT NOT NULL,
  direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
  message_kind TEXT NOT NULL,
  linked_entity_type TEXT NOT NULL CHECK (
    linked_entity_type IN ('task', 'artifact', 'control_event', 'snapshot', 'decision', 'escalation')
  ),
  linked_entity_id TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scheduling_records (
  project_id TEXT PRIMARY KEY REFERENCES projects(project_id) ON DELETE CASCADE,
  queue_state TEXT NOT NULL CHECK (
    queue_state IN ('urgent', 'active_recovery', 'normal_ready', 'waiting_external', 'blocked')
  ),
  eligible_for_scheduling INTEGER NOT NULL CHECK (eligible_for_scheduling IN (0, 1)),
  pause_requested INTEGER NOT NULL CHECK (pause_requested IN (0, 1)) DEFAULT 0,
  resume_requested INTEGER NOT NULL CHECK (resume_requested IN (0, 1)) DEFAULT 0,
  preemption_allowed INTEGER NOT NULL CHECK (preemption_allowed IN (0, 1)) DEFAULT 0,
  waiting_reason TEXT,
  last_scheduled_at TEXT,
  times_scheduled INTEGER NOT NULL DEFAULT 0 CHECK (times_scheduled >= 0),
  fairness_deadline_at TEXT,
  last_switch_reason TEXT CHECK (
    last_switch_reason IN (
      'MANUAL_PRIORITY_CHANGE',
      'CURRENT_PROJECT_WAITING_EXTERNAL',
      'CURRENT_PROJECT_BLOCKED',
      'CURRENT_PROJECT_AT_SAFE_BOUNDARY',
      'PREEMPTED_BY_URGENT_PROJECT',
      'OPERATOR_REQUEST',
      'SYSTEM_RECOVERY'
    )
  ),
  current_safe_boundary_type TEXT CHECK (
    current_safe_boundary_type IN (
      'TASK_COMPLETED',
      'TASK_RESULT_PERSISTED',
      'ESCALATION_PERSISTED',
      'ORACLE_REPORT_PERSISTED',
      'MORPHEUS_DELIVERY_PERSISTED',
      'PROJECT_STATUS_SNAPSHOT_PERSISTED'
    )
  )
);

CREATE TABLE IF NOT EXISTS orchestrator_leases (
  orchestrator_id TEXT PRIMARY KEY CHECK (orchestrator_id IN ('niobe', 'morpheus')),
  lease_status TEXT NOT NULL CHECK (lease_status IN ('FREE', 'HELD', 'EXPIRED', 'RELEASING')),
  active_project_id TEXT REFERENCES projects(project_id) ON DELETE SET NULL,
  lease_owner_run_id TEXT REFERENCES agent_runs(run_id) ON DELETE SET NULL,
  lease_acquired_at TEXT,
  lease_expires_at TEXT,
  released_at TEXT,
  release_reason TEXT,
  renew_count INTEGER NOT NULL DEFAULT 0 CHECK (renew_count >= 0)
);

CREATE TABLE IF NOT EXISTS project_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  captured_by TEXT NOT NULL,
  project_status TEXT NOT NULL CHECK (
    project_status IN (
      'NEW',
      'READY',
      'ACTIVE',
      'PAUSE_REQUESTED',
      'PAUSED',
      'WAITING_EXTERNAL',
      'WAITING_VERIFICATION',
      'BLOCKED',
      'DONE',
      'CANCELLED'
    )
  ),
  current_phase TEXT NOT NULL,
  current_owner_agent TEXT,
  open_tasks_json TEXT NOT NULL DEFAULT '[]',
  next_action_json TEXT NOT NULL DEFAULT '{}',
  workspace_ref TEXT NOT NULL,
  artifact_refs_json TEXT NOT NULL DEFAULT '[]',
  latest_human_summary TEXT NOT NULL,
  safe_boundary_type TEXT CHECK (
    safe_boundary_type IN (
      'TASK_COMPLETED',
      'TASK_RESULT_PERSISTED',
      'ESCALATION_PERSISTED',
      'ORACLE_REPORT_PERSISTED',
      'MORPHEUS_DELIVERY_PERSISTED',
      'PROJECT_STATUS_SNAPSHOT_PERSISTED'
    )
  ),
  created_from_control_event_id TEXT,
  created_from_run_id TEXT
);

CREATE TABLE IF NOT EXISTS control_events (
  event_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  orchestrator_id TEXT CHECK (orchestrator_id IN ('niobe', 'morpheus')),
  command TEXT NOT NULL CHECK (
    command IN (
      'PAUSE_PROJECT',
      'RESUME_PROJECT',
      'SWITCH_PROJECT',
      'CANCEL_PROJECT',
      'REPRIORITIZE_PROJECT',
      'FORCE_INTERRUPT',
      'STATUS_SNAPSHOT'
    )
  ),
  requested_by TEXT NOT NULL,
  requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  args_json TEXT NOT NULL DEFAULT '{}',
  reason TEXT,
  status TEXT NOT NULL CHECK (status IN ('REQUESTED', 'APPLIED', 'REJECTED', 'FAILED')),
  result_summary TEXT,
  mirrored_to_zulip INTEGER NOT NULL CHECK (mirrored_to_zulip IN (0, 1)) DEFAULT 0,
  mirrored_message_id TEXT
);

CREATE TABLE IF NOT EXISTS workspace_states (
  workspace_ref TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  repo_root TEXT NOT NULL,
  branch_or_worktree_id TEXT NOT NULL,
  last_clean_commit_or_checkpoint TEXT NOT NULL,
  is_consistent INTEGER NOT NULL CHECK (is_consistent IN (0, 1)) DEFAULT 1,
  last_validated_at TEXT,
  last_validation_summary TEXT
);

CREATE TABLE IF NOT EXISTS recovery_events (
  recovery_id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
  orchestrator_id TEXT CHECK (orchestrator_id IN ('niobe', 'morpheus')),
  workspace_ref TEXT REFERENCES workspace_states(workspace_ref) ON DELETE SET NULL,
  failure_mode TEXT NOT NULL,
  action_taken TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('OPEN', 'RUNNING', 'COMPLETED', 'FAILED')),
  details_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_project_status
  ON tasks(project_id, status);

CREATE INDEX IF NOT EXISTS idx_tasks_owner
  ON tasks(current_owner_agent, status);

CREATE INDEX IF NOT EXISTS idx_task_attempts_task
  ON task_attempts(task_id, attempt_number);

CREATE INDEX IF NOT EXISTS idx_agent_runs_project_agent
  ON agent_runs(project_id, agent_id, started_at);

CREATE INDEX IF NOT EXISTS idx_artifacts_project_task
  ON artifacts(project_id, task_id, artifact_type);

CREATE INDEX IF NOT EXISTS idx_scheduling_queue
  ON scheduling_records(queue_state, eligible_for_scheduling, last_scheduled_at);

CREATE INDEX IF NOT EXISTS idx_snapshots_project_captured
  ON project_snapshots(project_id, captured_at);

CREATE INDEX IF NOT EXISTS idx_control_events_project_requested
  ON control_events(project_id, requested_at);

CREATE VIEW IF NOT EXISTS scheduler_queue_view AS
SELECT
  p.project_id,
  p.project_status,
  p.runtime_status,
  p.priority,
  p.current_phase,
  p.current_owner_agent,
  p.workspace_ref,
  s.queue_state,
  s.eligible_for_scheduling,
  s.pause_requested,
  s.resume_requested,
  s.waiting_reason,
  s.last_scheduled_at,
  s.times_scheduled
FROM projects AS p
JOIN scheduling_records AS s
  ON s.project_id = p.project_id;
