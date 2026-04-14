# zulip_communication_spec.md

This document defines how the agentic system uses Zulip for communication, visibility, and audit.

- The YAML block under **Authoritative Spec** is the source of truth.
- Zulip is the **communication plane and audit trail**.
- Zulip is **not** the workflow engine, artifact store, or source of truth for task state.

## Authoritative Spec

```yaml
spec_version: "1.0.0"
metadata:
  spec_id: "zulip_communication_spec"
  name: "Zulip Communication Spec"
  last_updated: "2026-04-02"
  authoritative: true
  description: "Communication-plane specification for agent and human interaction over Zulip."

core_decision:
  zulip_role:
    - "transport"
    - "human-agent interface"
    - "agent-agent visible coordination"
    - "audit trail"
  zulip_not_used_for:
    - "authoritative task state"
    - "authoritative project state"
    - "artifact storage"
    - "workflow routing logic"
  authoritative_backends:
    task_state: "orchestrator_state_store"
    project_state: "orchestrator_state_store"
    artifacts: "artifact_store"

architecture:
  components:
    zulip_server:
      purpose: "Message transport and user-visible conversation surface."
    zulip_gateway:
      purpose: "Single integration service between Zulip and the agent runtime."
    orchestrator_state_store:
      purpose: "Authoritative state for tasks, projects, routing, and retries."
    artifact_store:
      purpose: "Store structured artifacts and generated outputs."
    agent_runtime:
      purpose: "Runs OpenClaw agents with Ollama models inside Docker sandboxes."
  required_pattern: "single_gateway_service"
  forbidden_pattern: "each_agent_implements_its_own_zulip_client"

visible_agents:
  default:
    - "master"
    - "neo"
    - "agent_smith"
    - "niaobe"
    - "morpheus"
    - "architect"
    - "oracle"
  internal_only_default:
    - "planner"
    - "implementer"
    - "tester"
  optional_future_visibility:
    planner: "may_mirror_to_private_software_internal_stream"
    implementer: "may_mirror_to_private_software_internal_stream"
    tester: "may_mirror_to_private_software_internal_stream"

bot_model:
  type: "generic_bots"
  rationale:
    - "long-lived identities behave like normal Zulip users"
    - "supports subscriptions, channel posting, and topic continuity"
    - "simpler than mixing agent logic with outgoing webhook assumptions"
  owner_policy:
    - "Bots must be owned by restricted service accounts, not broad admin accounts."
    - "API keys must be stored in secrets storage, not in repo files."

streams:
  executive:
    name: "exec"
    privacy: "private"
    purpose: "Executive intake, approvals, and strategic escalations."
  projects:
    name: "projects"
    privacy: "private"
    purpose: "Project-level orchestration, design requests, and high-level status."
  software:
    name: "software"
    privacy: "private"
    purpose: "Morpheus-visible software delivery messages and completion reports."
  verification:
    name: "verification"
    privacy: "private"
    purpose: "Oracle reports and project verification exchanges."
  escalations:
    name: "escalations"
    privacy: "private"
    purpose: "Explicit blockers, risk packets, and approval requests."
  software_internal:
    name: "software-internal"
    privacy: "private"
    optional: true
    purpose: "Optional mirrored internal Planner/Implementer/Tester activity."

topic_conventions:
  project_intake: "project/{project_id}/intake"
  project_main: "project/{project_id}"
  project_decisions: "project/{project_id}/decisions"
  project_design: "project/{project_id}/design"
  software_main: "project/{project_id}/software"
  software_task: "project/{project_id}/software/{task_id}"
  verification_task: "project/{project_id}/verify/{task_id}"
  escalation_task: "project/{project_id}/escalate/{task_id}"

subscription_policy:
  master:
    streams: ["exec", "projects", "verification", "escalations"]
  neo:
    streams: ["exec", "projects", "verification", "escalations"]
  agent_smith:
    streams: ["exec", "projects", "escalations"]
  niaobe:
    streams: ["projects", "software", "verification", "escalations"]
  morpheus:
    streams: ["projects", "software", "escalations"]
  architect:
    streams: ["projects", "software"]
  oracle:
    streams: ["verification", "projects", "escalations"]
  planner:
    streams: []
  implementer:
    streams: []
  tester:
    streams: []

message_rules:
  core:
    - "Every authoritative communication event mirrored to Zulip must include project_id and task_id."
    - "Reply in the same topic unless security or escalation requires a different topic."
    - "Free-form chat without a structured block is non-authoritative."
    - "The gateway must persist task state before or while posting to Zulip."
    - "Every task and result message must include a short human summary followed by a machine-readable block."
  dm_usage:
    allowed_for:
      - "secrets"
      - "urgent human approvals"
      - "operator intervention"
    discouraged_for:
      - "normal project execution"
      - "persistent team coordination"

message_taxonomy:
  kinds:
    - "task_assignment"
    - "task_result"
    - "status_update"
    - "escalation"
    - "approval_request"
    - "approval_result"
    - "human_note"

schemas:
  zulip_task_message:
    required:
      - "kind"
      - "project_id"
      - "task_id"
      - "from_agent"
      - "to_agent"
      - "task_type"
      - "goal"
      - "return_to"
  zulip_result_message:
    required:
      - "kind"
      - "project_id"
      - "task_id"
      - "agent"
      - "status"
      - "summary"
      - "artifacts_out"
      - "next_action"
  zulip_escalation_message:
    required:
      - "kind"
      - "project_id"
      - "task_id"
      - "from_agent"
      - "to_agent"
      - "reason"
      - "blocking_facts"
      - "recommended_action"

gateway:
  responsibilities:
    - "manage Zulip credentials and subscriptions"
    - "receive Zulip events"
    - "normalize messages into internal task envelopes"
    - "dispatch work to the correct agent runtime"
    - "post agent responses back to the correct stream and topic"
    - "persist message-to-task mappings"
    - "deduplicate repeated events"
    - "rebuild event queues when Zulip queue ids expire"
    - "enforce formatting and schema checks before outbound posts"
  internal_interfaces:
    inbound_from_zulip: "event_consumer"
    outbound_to_zulip: "message_publisher"
    task_dispatch: "orchestrator_api"
    artifact_lookup: "artifact_store_api"
    state_lookup: "state_store_api"
  persistence_requirements:
    - "zulip_message_id_to_task_id mapping"
    - "project_id_to_default_topics mapping"
    - "dedupe keys for event processing"
    - "last_processed_event_cursor"

processing_rules:
  incoming_human_command:
    - "validate stream and topic"
    - "extract or assign project_id"
    - "create or update task in state store"
    - "dispatch to appropriate agent"
    - "post acknowledgement or result"
  incoming_agent_message:
    - "validate schema block"
    - "check task ownership and return target"
    - "persist response envelope"
    - "mirror to the correct topic"
  topic_rule:
    default: "stay_in_same_topic"
    exceptions:
      - "escalation moves to escalation topic"
      - "secrets move to DM"
      - "verification may move to verification stream topic"

message_format:
  required_shape:
    - "brief human summary"
    - "machine-readable fenced YAML block"
  authoritative_when:
    - "contains a valid schema block"
    - "references a known or newly-created task_id"
    - "accepted by gateway validation"
  non_authoritative_when:
    - "pure discussion"
    - "missing task_id"
    - "malformed schema block"

examples:
  task_assignment: |
    Morpheus -> Planner: Break the billing API task into executable steps and include test obligations.

    ```yaml
    kind: task_assignment
    project_id: P-104
    task_id: T-220
    from_agent: Morpheus
    to_agent: Planner
    task_type: PLAN_SOFTWARE_TASK
    goal: Implement billing API v1 with tests
    return_to: Morpheus
    reply_stream: software
    reply_topic: project/P-104/software/T-220
    ```
  task_result: |
    Tester: Tests now pass after one implementation retry.

    ```yaml
    kind: task_result
    project_id: P-104
    task_id: T-220
    agent: Tester
    status: SUCCESS
    summary: Relevant automated tests pass
    artifacts_out:
      - tests.patch
      - test_report.md
    next_action:
      type: RETURN_TO_REQUESTER
      target_agent: Morpheus
      reason: Software test obligations satisfied
    ```
  escalation: |
    Niaobe -> AgentSmith: Requirements are contradictory and cannot be verified as written.

    ```yaml
    kind: escalation
    project_id: P-104
    task_id: T-240
    from_agent: Niaobe
    to_agent: AgentSmith
    reason: CONFLICTING_REQUIREMENTS
    blocking_facts:
      - API spec and acceptance criteria disagree on auth mode
    recommended_action: Clarify charter and issue a corrected version
    ```

canonical_flows:
  project_kickoff:
    - "Human or MASTER posts in exec or projects"
    - "Gateway converts message to FRAME_PROJECT for AgentSmith"
    - "AgentSmith replies in project intake topic with project charter"
    - "AgentSmith assigns Niaobe"
  design_request:
    - "Niaobe posts task for Architect in project design topic"
    - "Architect replies in same topic with design artifact summary and schema block"
  software_delivery:
    - "Niaobe assigns ORCHESTRATE_SOFTWARE to Morpheus"
    - "Morpheus may keep Planner/Implementer/Tester internal or mirror to software-internal"
    - "Morpheus posts completion summary to software stream"
  project_verification:
    - "Niaobe assigns VERIFY_PROJECT to Oracle"
    - "Oracle posts report in verification stream"
    - "Niaobe reads report and decides next action"
  escalation:
    - "Any orchestrator posts escalation packet in escalations stream or DM when sensitive"
    - "Gateway links escalation message to the owning task and project"

security:
  rules:
    - "Use restricted service owners for bot accounts."
    - "Store API keys outside the repository."
    - "Subscribe bots before work begins in private channels with protected history."
    - "Keep private streams private; do not rely on topic names for access control."
    - "Redact secrets from mirrored messages when the artifact store already contains the full secret-bearing object."
  incident_response:
    leaked_bot_key:
      - "rotate the bot API key"
      - "invalidate cached credentials"
      - "review recent bot actions"
      - "reissue secrets to the gateway"

operability:
  retries:
    outbound_post_retry_policy: "exponential_backoff"
    inbound_dedupe_required: true
  queue_management:
    rule: "gateway must recreate Zulip event queues when expired and resume from authoritative task state"
  observability:
    required_metrics:
      - "messages_received"
      - "messages_posted"
      - "schema_validation_failures"
      - "duplicate_events_dropped"
      - "queue_recreations"
      - "task_dispatch_failures"
      - "topic_mismatch_warnings"

implementation_targets:
  builder_agent_must_generate:
    - "zulip gateway service"
    - "bot account bootstrap scripts"
    - "stream and topic helpers"
    - "schema validators for Zulip message blocks"
    - "message id to task id mapping store"
    - "event consumer with dedupe and queue recreation"
    - "message publisher with topic routing"
    - "optional software-internal mirroring support"
  recommended_repo_layout:
    - "specs/zulip_communication_spec.md"
    - "communication/zulip_gateway.py"
    - "communication/zulip_gateway_config.yaml"
    - "communication/topic_router.py"
    - "communication/message_schemas.py"
    - "communication/subscription_bootstrap.py"
    - "communication/event_dedupe_store.py"
    - "communication/message_mapping_store.py"
```

## Human-readable guidance

### What Zulip is for

Use Zulip for:

- human requests
- agent handoffs that should be visible
- approvals and escalations
- audit history
- status reporting

Do **not** use Zulip as:

- the task database
- the project state database
- the artifact store
- the routing engine

### Recommended operating shape

Start with these visible agents in Zulip:

- MASTER
- Neo
- AgentSmith
- Niaobe
- Morpheus
- Architect
- Oracle

Keep these internal at first:

- Planner
- Implementer
- Tester

That keeps your chat surface readable while Morpheus still runs a strict internal software loop.

### Message style

Every serious agent message should contain:

1. a short human summary
2. a fenced YAML block with the machine-readable payload

That way humans can read it and the gateway can parse it.

### Why a single gateway is the right move

Without a gateway, every bot ends up reimplementing:

- Zulip auth
- event handling
- queue recovery
- topic routing
- message validation
- deduplication
- task mapping

That is a ridiculous amount of repeated plumbing just to make robots talk in a chat app.

## Recommended larger changes

1. Keep **Planner, Implementer, and Tester** off Zulip until you need deeper transparency.
2. Add a **private software-internal stream** only when debugging Morpheus loops becomes necessary.
3. Add **redaction support** before posting artifacts or logs that might include secrets.
4. Build the gateway so it can **reconstruct state from the database**, not from reading chat history back.
