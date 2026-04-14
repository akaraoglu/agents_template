# complete_agentic_software_workflow_with_zulip.md

This document is the **single-file handoff specification** for building the full agentic software-development system.

It consolidates the current workflow, Zulip communication model, and software workspace contract into one implementation-ready spec.

**Use this file as the builder agent's primary input.**
The other documents remain useful as supporting references, but this file is the final integrated view.

---

## How to use this file

- Treat the YAML block under **Authoritative Integrated Spec** as the source of truth.
- Treat the prose sections after the YAML block as implementation guidance and interpretation.
- If a future change conflicts with older supporting docs, this file wins.

---

## Authoritative Integrated Spec

```yaml
spec_version: "1.0.0"
metadata:
  spec_id: "complete_agentic_software_workflow_with_zulip"
  name: "Complete Agentic Software Workflow with Zulip"
  last_updated: "2026-04-02"
  authoritative: true
  owners: ["MASTER"]
  purpose: "Single-file implementation handoff for the full software-development agent system."
  supersedes_as_handoff:
    - "agentic_workflow.md"
    - "zulip_communication_spec.md"
    - "SOFTWARE_WORKSPACE_README.md"

system_goals:
  - "Create a future-proof multi-agent software-delivery system with clear boundaries and minimal authority overlap."
  - "Keep project orchestration separate from software orchestration."
  - "Require tested software delivery before project verification."
  - "Use Zulip for communication and audit without making it the state database."
  - "Allow new specialist agents to be added without rewriting the core workflow."
  - "Keep the first implementation simple enough to build and debug locally."

stack:
  llm_runtime:
    default: "ollama"
    notes:
      - "Use local models by default."
      - "Neo may use an external or stronger model when explicitly configured."
  agent_framework: "openclaw"
  sandbox_runtime: "docker"
  communication_runtime: "zulip"
  communication_gateway_required: true
  authoritative_state_store_required: true
  artifact_store_required: true
  workspace_required: true

core_decisions:
  source_of_truth:
    project_state: "orchestrator_state_store"
    task_state: "orchestrator_state_store"
    artifacts: "artifact_store_and_workspace"
    communication: "zulip_transport_only"
  visible_in_zulip:
    - "master"
    - "neo"
    - "agent_smith"
    - "niaobe"
    - "morpheus"
    - "architect"
    - "oracle"
  internal_only_by_default:
    - "planner"
    - "implementer"
    - "tester"
  required_gateway_pattern: "single_zulip_gateway_service"
  forbidden_gateway_pattern: "each_agent_implements_its_own_zulip_client"

naming:
  canonical_agent_ids:
    master:
      display_name: "MASTER"
      aliases: ["CEO"]
    neo:
      display_name: "Neo"
      aliases: ["CTO"]
    agent_smith:
      display_name: "AgentSmith"
      aliases: ["Agent Smith", "General Manager"]
    niaobe:
      display_name: "Niaobe"
      aliases: ["Niaobe", "Project Manager"]
    architect:
      display_name: "Architect"
      aliases: ["Project Architect", "Code Architect"]
    morpheus:
      display_name: "Morpheus"
      aliases: ["Software Manager", "Software Orchestrator"]
    oracle:
      display_name: "Oracle"
      aliases: ["Project Verifier"]
    planner:
      display_name: "Planner"
      aliases: ["Software Planner"]
    implementer:
      display_name: "Implementer"
      aliases: ["Software Engineer"]
    tester:
      display_name: "Tester"
      aliases: ["Software Tester", "QA Agent"]

principles:
  - "Keep agent roles narrow, explicit, and enforceable."
  - "Only orchestrators decide what runs next inside active loops."
  - "Every task has exactly one current owner and exactly one return target."
  - "Specialists return to the requesting agent, not to a globally assumed manager."
  - "Niaobe owns project flow. Morpheus owns software flow."
  - "Oracle verifies projects. Tester verifies software tasks."
  - "Every code-changing software task must produce or update automated tests and a test execution report."
  - "Zulip carries communication and audit history, but authoritative state must be recoverable without reading Zulip history."
  - "New agents are added by capability registration, not by rewriting orchestration logic."

enums:
  role_types: ["executive", "intake", "orchestrator", "specialist"]
  task_statuses: ["PENDING", "RUNNING", "SUCCESS", "NEEDS_CLARIFICATION", "BLOCKED", "FAILED", "CANCELLED"]
  project_statuses: ["NEW", "ACTIVE", "VERIFICATION_PENDING", "DONE", "BLOCKED", "CANCELLED"]
  priorities: ["LOW", "MEDIUM", "HIGH", "URGENT"]
  task_types:
    - "CLARIFY_GOAL"
    - "FRAME_PROJECT"
    - "APPROVE_PRIORITY"
    - "RESOLVE_ESCALATION"
    - "ORCHESTRATE_PROJECT"
    - "DESIGN_ARCHITECTURE"
    - "REQUEST_ARCHITECTURE_CLARIFICATION"
    - "ORCHESTRATE_SOFTWARE"
    - "PLAN_SOFTWARE_TASK"
    - "IMPLEMENT_SOFTWARE_TASK"
    - "TEST_SOFTWARE_TASK"
    - "VERIFY_PROJECT"
    - "CLOSE_PROJECT"
  artifact_types:
    - "clarification_brief"
    - "project_charter"
    - "project_status_report"
    - "architecture_spec"
    - "software_task_plan"
    - "code_change"
    - "test_execution_report"
    - "software_delivery_package"
    - "verification_report"
    - "escalation_packet"
    - "executive_decision"
    - "project_closure_report"
  verification_results: ["PASS", "FAIL", "INCONCLUSIVE"]
  morpheus_failure_causes:
    - "BAD_PLAN"
    - "IMPLEMENTATION_DEFECT"
    - "TEST_GAP"
    - "ARCHITECTURE_GAP"
    - "REQUIREMENT_GAP"
    - "ENVIRONMENT_FAILURE"
    - "UNKNOWN"

agent_registry:
  master:
    role_type: "executive"
    lifecycle: "singleton"
    purpose: "Final authority for priority, risk, and exceptional scope decisions."
    owns: ["final priority decisions", "risk acceptance", "exception approvals"]
    does_not_own: ["project orchestration", "implementation", "verification execution"]
    accepts_tasks: ["APPROVE_PRIORITY", "RESOLVE_ESCALATION", "CLOSE_PROJECT"]
    allowed_requesters: ["neo", "agent_smith", "niaobe"]
    returns_to: "requesting_agent"

  neo:
    role_type: "executive"
    lifecycle: "singleton"
    purpose: "Clarify goals, expose tradeoffs, and reduce ambiguity."
    owns: ["goal clarification", "tradeoff analysis", "strategic technical direction"]
    does_not_own: ["project routing", "software execution", "project verification"]
    accepts_tasks: ["CLARIFY_GOAL", "RESOLVE_ESCALATION"]
    allowed_requesters: ["master", "agent_smith", "niaobe", "architect", "morpheus"]
    returns_to: "requesting_agent"

  agent_smith:
    role_type: "intake"
    lifecycle: "singleton"
    purpose: "Convert requests into executable project charters and assign project orchestration."
    owns: ["request intake", "project framing", "acceptance criteria definition", "initial priority assignment"]
    does_not_own: ["deep research", "project execution", "software delivery"]
    accepts_tasks: ["FRAME_PROJECT", "RESOLVE_ESCALATION"]
    allowed_requesters: ["master", "neo", "niaobe"]
    returns_to: "requesting_agent"

  niaobe:
    role_type: "orchestrator"
    lifecycle: "singleton"
    purpose: "Project-level orchestrator that decides what happens next until the project is done or blocked."
    owns: ["project execution loop", "next-step routing", "project status", "project-level retry and escalation"]
    does_not_own: ["architecture design", "coding", "software testing", "project verification execution"]
    accepts_tasks: ["ORCHESTRATE_PROJECT", "CLOSE_PROJECT", "RESOLVE_ESCALATION"]
    allowed_requesters: ["agent_smith", "master", "neo"]
    returns_to: "requesting_agent"

  architect:
    role_type: "specialist"
    lifecycle: "singleton_or_pool"
    purpose: "Design architecture, interfaces, and technical boundaries."
    owns: ["architecture design", "component boundaries", "interface contracts"]
    does_not_own: ["project routing", "implementation execution", "project verification"]
    accepts_tasks: ["DESIGN_ARCHITECTURE", "REQUEST_ARCHITECTURE_CLARIFICATION"]
    allowed_requesters: ["master", "neo", "agent_smith", "niaobe", "morpheus"]
    returns_to: "requesting_agent"

  morpheus:
    role_type: "orchestrator"
    lifecycle: "singleton"
    purpose: "Software-delivery orchestrator that runs Planner, Implementer, and Tester until a tested implementation package is ready."
    owns: ["software delivery loop", "software subtask sequencing", "test-required completion of code work", "integration readiness for project verification"]
    does_not_own: ["project-level acceptance", "project verification", "business priority decisions"]
    accepts_tasks: ["ORCHESTRATE_SOFTWARE"]
    allowed_requesters: ["niaobe", "architect", "neo", "master"]
    returns_to: "requesting_agent"

  oracle:
    role_type: "specialist"
    lifecycle: "singleton_or_pool"
    purpose: "Project verifier that checks delivered outputs against the project charter and acceptance criteria."
    owns: ["project-level verification", "verification reports", "evidence-based pass/fail judgments"]
    does_not_own: ["software testing loop", "project routing", "implementation"]
    accepts_tasks: ["VERIFY_PROJECT"]
    allowed_requesters: ["niaobe", "agent_smith", "neo", "master"]
    returns_to: "requesting_agent"

  planner:
    role_type: "specialist"
    lifecycle: "task_scoped_spawned_by_morpheus"
    purpose: "Translate a software goal into an executable plan and explicit test obligations."
    owns: ["software task decomposition", "implementation plan", "test obligation plan"]
    does_not_own: ["writing production code", "final test execution", "project routing"]
    accepts_tasks: ["PLAN_SOFTWARE_TASK"]
    allowed_requesters: ["morpheus"]
    returns_to: "requesting_agent"

  implementer:
    role_type: "specialist"
    lifecycle: "task_scoped_spawned_by_morpheus"
    purpose: "Produce code changes according to the approved software plan."
    owns: ["code changes", "buildability of changed code", "implementation notes"]
    does_not_own: ["test strategy", "project verification", "project routing"]
    accepts_tasks: ["IMPLEMENT_SOFTWARE_TASK"]
    allowed_requesters: ["morpheus"]
    returns_to: "requesting_agent"

  tester:
    role_type: "specialist"
    lifecycle: "task_scoped_spawned_by_morpheus"
    purpose: "Create or update automated tests, run them, and produce reproducible quality evidence."
    owns: ["test code changes", "test execution", "failure classification for Morpheus"]
    does_not_own: ["project verification", "project routing", "business requirement interpretation"]
    accepts_tasks: ["TEST_SOFTWARE_TASK"]
    allowed_requesters: ["morpheus"]
    returns_to: "requesting_agent"

routing:
  default_entry_agent: "agent_smith"
  default_project_orchestrator: "niaobe"
  default_software_orchestrator: "morpheus"
  route_by_task_type:
    CLARIFY_GOAL: "neo"
    FRAME_PROJECT: "agent_smith"
    APPROVE_PRIORITY: "master"
    RESOLVE_ESCALATION: "master"
    ORCHESTRATE_PROJECT: "niaobe"
    DESIGN_ARCHITECTURE: "architect"
    REQUEST_ARCHITECTURE_CLARIFICATION: "architect"
    ORCHESTRATE_SOFTWARE: "morpheus"
    PLAN_SOFTWARE_TASK: "planner"
    IMPLEMENT_SOFTWARE_TASK: "implementer"
    TEST_SOFTWARE_TASK: "tester"
    VERIFY_PROJECT: "oracle"
  requester_agnostic_specialists: ["architect", "oracle"]
  internal_only_specialists:
    planner: "morpheus"
    implementer: "morpheus"
    tester: "morpheus"
  return_rule: "specialists_return_to_requesting_agent"
  extension_rule: "add_by_capability_registration"

global_invariants:
  - "Every task has exactly one current owner."
  - "Every task names exactly one return target."
  - "Only orchestrators choose next-step routing inside live loops."
  - "Niaobe never directly calls Planner, Implementer, or Tester."
  - "Morpheus never closes the project."
  - "Oracle never replaces Tester."
  - "Project closure requires design evidence, implementation evidence, and Oracle verification evidence."
  - "Authoritative project state must be recoverable without reading Zulip history."

required_rules:
  project:
    design_must_happen: true
    implementation_must_happen: true
    oracle_verification_must_happen: true
    closure_requires_all_three: true
  morpheus_software_task:
    planner_must_run: true
    implementer_must_run: true
    tester_must_run: true
    code_change_requires_automated_tests: true
    success_requires_test_execution_report: true

state_machines:
  niobe_project_loop:
    owner: "niaobe"
    purpose: "Adaptive project orchestration"
    states:
      RECEIVED:
        transitions:
          CHARTER_INCOMPLETE: "CLARIFY"
          CHARTER_VALID: "DECIDE_NEXT"
      CLARIFY:
        rule: "Niaobe requests clarification from Neo or AgentSmith. She does not silently invent missing requirements."
        transitions:
          CLARIFIED: "DECIDE_NEXT"
          BLOCKED: "ESCALATE"
      DECIDE_NEXT:
        decision_rules:
          - when: "design_complete == false"
            action: "assign DESIGN_ARCHITECTURE to architect"
            next_state: "WAITING_RESULT"
          - when: "design_complete == true and implementation_complete == false"
            action: "assign ORCHESTRATE_SOFTWARE to morpheus"
            next_state: "WAITING_RESULT"
          - when: "design_complete == true and implementation_complete == true and verification_complete == false"
            action: "assign VERIFY_PROJECT to oracle"
            next_state: "WAITING_RESULT"
          - when: "design_complete == true and implementation_complete == true and verification_complete == true"
            action: "produce project_closure_report"
            next_state: "DONE"
      WAITING_RESULT:
        transitions:
          RESULT_SUCCESS: "REVIEW_RESULT"
          RESULT_NEEDS_CLARIFICATION: "CLARIFY"
          RESULT_BLOCKED: "ESCALATE"
          RESULT_FAILED: "REVIEW_RESULT"
      REVIEW_RESULT:
        decision_rules:
          - when: "artifact_type == architecture_spec"
            action: "set design_complete = true"
            next_state: "DECIDE_NEXT"
          - when: "artifact_type == software_delivery_package"
            action: "set implementation_complete = true"
            next_state: "DECIDE_NEXT"
          - when: "artifact_type == verification_report and result == PASS"
            action: "set verification_complete = true"
            next_state: "DECIDE_NEXT"
          - when: "artifact_type == verification_report and result == FAIL and defect_category == implementation"
            action: "set implementation_complete = false; assign morpheus"
            next_state: "WAITING_RESULT"
          - when: "artifact_type == verification_report and result == FAIL and defect_category == design"
            action: "set design_complete = false; set implementation_complete = false; assign architect"
            next_state: "WAITING_RESULT"
          - when: "artifact_type == verification_report and result == FAIL and defect_category == requirements"
            action: "escalate to agent_smith or neo"
            next_state: "ESCALATE"
          - when: "otherwise"
            action: "decide next best step based on latest evidence"
            next_state: "DECIDE_NEXT"
      ESCALATE:
        rule: "Niaobe must send an explicit escalation packet with a recommended action."
        transitions:
          ESCALATION_RESOLVED: "DECIDE_NEXT"
          ESCALATION_REJECTED: "BLOCKED"
      DONE:
        terminal: true
      BLOCKED:
        terminal: true

  morpheus_software_loop:
    owner: "morpheus"
    purpose: "Software delivery loop over Planner, Implementer, and Tester"
    invariants:
      - "planner_invocations >= 1 before success"
      - "implementer_invocations >= 1 before success"
      - "tester_invocations >= 1 before success"
      - "if code_changed == true then test_execution_report must exist"
    states:
      RECEIVED:
        transitions:
          READY: "PLAN"
          INCOMPLETE: "CLARIFY_OR_ESCALATE"
      PLAN:
        action: "spawn planner with PLAN_SOFTWARE_TASK"
        transitions:
          PLANNER_RETURNED: "REVIEW_PLAN"
      REVIEW_PLAN:
        decision_rules:
          - when: "planner.status == SUCCESS"
            action: "store current_plan"
            next_state: "IMPLEMENT"
          - when: "planner.status in [NEEDS_CLARIFICATION, BLOCKED, FAILED]"
            action: "classify cause"
            next_state: "CLARIFY_OR_ESCALATE"
      IMPLEMENT:
        action: "spawn implementer with IMPLEMENT_SOFTWARE_TASK"
        transitions:
          IMPLEMENTER_RETURNED: "REVIEW_IMPLEMENTATION"
      REVIEW_IMPLEMENTATION:
        decision_rules:
          - when: "implementer.status == SUCCESS"
            action: "store latest_code_change"
            next_state: "TEST"
          - when: "implementer.status in [NEEDS_CLARIFICATION, BLOCKED]"
            action: "classify cause"
            next_state: "CLARIFY_OR_ESCALATE"
          - when: "implementer.status == FAILED"
            action: "retry implementer or return to planner"
            next_state: "DECIDE_RETRY"
      TEST:
        action: "spawn tester with TEST_SOFTWARE_TASK"
        transitions:
          TESTER_RETURNED: "REVIEW_TESTS"
      REVIEW_TESTS:
        decision_rules:
          - when: "tester.status == SUCCESS and tester.result == PASS"
            action: "produce software_delivery_package"
            next_state: "DONE"
          - when: "tester.status == SUCCESS and tester.result == FAIL"
            action: "store latest_test_report"
            next_state: "DECIDE_RETRY"
          - when: "tester.status in [NEEDS_CLARIFICATION, BLOCKED]"
            action: "classify cause"
            next_state: "CLARIFY_OR_ESCALATE"
          - when: "tester.status == FAILED"
            action: "retry tester or escalate"
            next_state: "DECIDE_RETRY"
      DECIDE_RETRY:
        decision_rules:
          - when: "failure_cause == BAD_PLAN"
            action: "spawn planner again"
            next_state: "PLAN"
          - when: "failure_cause == IMPLEMENTATION_DEFECT"
            action: "spawn implementer again"
            next_state: "IMPLEMENT"
          - when: "failure_cause == TEST_GAP"
            action: "spawn tester again"
            next_state: "TEST"
          - when: "failure_cause == ARCHITECTURE_GAP"
            action: "request architect clarification"
            next_state: "WAITING_ARCHITECT"
          - when: "failure_cause in [REQUIREMENT_GAP, ENVIRONMENT_FAILURE, UNKNOWN]"
            action: "return escalation_packet to niaobe"
            next_state: "BLOCKED"
      WAITING_ARCHITECT:
        transitions:
          ARCHITECT_RETURNED: "PLAN"
          ARCHITECT_BLOCKED: "CLARIFY_OR_ESCALATE"
      CLARIFY_OR_ESCALATE:
        decision_rules:
          - when: "issue_type == requirement_gap"
            action: "return escalation_packet to niaobe"
            next_state: "BLOCKED"
          - when: "issue_type == architecture_gap"
            action: "request architect clarification"
            next_state: "WAITING_ARCHITECT"
          - when: "issue_type == environment_issue"
            action: "return escalation_packet to niaobe"
            next_state: "BLOCKED"
          - when: "issue_type == minor_plan_gap"
            action: "retry planner"
            next_state: "PLAN"
      DONE:
        terminal: true
      BLOCKED:
        terminal: true

communication:
  mode: "zulip_transport_plus_gateway"
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
      purpose: "Morpheus-visible software delivery requests and completion reports."
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
      purpose: "Optional mirrored internal Planner, Implementer, and Tester activity."
  topic_conventions:
    project_intake: "project/{project_id}/intake"
    project_main: "project/{project_id}"
    project_decisions: "project/{project_id}/decisions"
    project_design: "project/{project_id}/design"
    software_main: "project/{project_id}/software"
    software_task: "project/{project_id}/software/{task_id}"
    verification_task: "project/{project_id}/verify/{task_id}"
    escalation_task: "project/{project_id}/escalate/{task_id}"
  message_rules:
    - "Every authoritative communication event mirrored to Zulip must include project_id and task_id."
    - "Reply in the same topic unless security or escalation requires a different topic."
    - "Free-form chat without a structured block is non-authoritative."
    - "The gateway must persist task state before or while posting to Zulip."
    - "Every task and result message must include a short human summary followed by a machine-readable YAML block."
  dm_usage:
    allowed_for: ["secrets", "urgent human approvals", "operator intervention"]
    discouraged_for: ["normal project execution", "persistent team coordination"]
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

workspace:
  mount_path: "/workspace"
  source_of_truth:
    - "PROJECT.md"
    - "management/"
    - "project code, tests, and generated delivery artifacts"
  required_structure:
    - "PROJECT.md"
    - "management/"
    - "management/STATUS.md"
    - "management/MILESTONES.md"
    - "management/BACKLOG.md"
    - "management/DECISIONS.md"
    - "management/TEST_REPORT.md"
  recommended_structure:
    - "artifacts/"
    - "artifacts/incoming/"
    - "artifacts/outgoing/"
    - "artifacts/reports/"
    - "tests/"
    - ".agents/ (optional local runtime)"
  morpheus_workspace_rules:
    - "Morpheus reads PROJECT.md, management/, relevant artifacts, and relevant code before starting a software loop."
    - "Morpheus updates workspace documents after successful software delivery."
    - "If Zulip summaries and workspace state disagree, workspace state must be corrected first and Zulip must then be updated through the gateway."
  non_trivial_task_requires:
    - "implementation changes or explicit no-code justification"
    - "test changes or explicit test justification"
    - "updated status documentation"
    - "test report"

persistence:
  required_stores:
    - "orchestrator_state_store"
    - "artifact_store"
    - "zulip_message_mapping_store"
  minimum_entities:
    - "projects"
    - "tasks"
    - "task_attempts"
    - "agent_runs"
    - "artifacts"
    - "decisions"
    - "escalations"
    - "zulip_message_links"

sandbox:
  runtime: "docker"
  defaults:
    network: "off_by_default"
    workspace_mount: "scoped_rw"
    control_mounts: "read_only"
    secrets: "narrow_injection_only"
    execution: "ephemeral_per_run"
  requirements:
    - "resource limits must be configurable"
    - "sandbox must expose reproducible build and test commands"
    - "sandbox must support isolated task attempts"

stop_conditions:
  niaobe:
    max_project_transitions_before_escalation: 20
  morpheus:
    max_retry_cycles_per_software_task: 5
    repeated_same_failure_signature_before_escalation: 2
  all_agents:
    timeout_per_run_required: true
    no_infinite_retry_loops: true

schemas:
  task_envelope:
    required:
      - "task_id"
      - "project_id"
      - "from_agent"
      - "to_agent"
      - "task_type"
      - "title"
      - "goal"
      - "priority"
      - "context"
      - "expected_output"
      - "decision_bounds"
      - "return_to"
  response_envelope:
    required:
      - "task_id"
      - "project_id"
      - "agent"
      - "status"
      - "summary"
      - "artifacts_out"
      - "findings"
      - "next_action"
      - "risks"
      - "trace"
  escalation_packet:
    required:
      - "reason"
      - "owner_agent"
      - "blocking_facts"
      - "options_considered"
      - "recommended_action"
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

default_flow:
  happy_path:
    - "Human or MASTER request -> AgentSmith"
    - "AgentSmith frames project -> Niaobe"
    - "Niaobe requests architecture -> Architect"
    - "Niaobe requests software delivery -> Morpheus"
    - "Morpheus loops Planner -> Implementer -> Tester until a software delivery package is ready"
    - "Niaobe requests project verification -> Oracle"
    - "Niaobe closes or reroutes based on Oracle report"
  allowed_variations:
    - "Neo may clarify before or during execution"
    - "Architect may be recalled after Oracle failure or during Morpheus architecture gaps"
    - "Morpheus may ask Architect for clarification without bypassing Niaobe on project-level decisions"
  prohibited_paths:
    - "Oracle replacing Tester inside the software loop"
    - "Morpheus closing a project"
    - "Niaobe directly calling Planner, Implementer, or Tester"
    - "Any specialist changing project scope without escalation"

human_controls:
  required_commands:
    - "pause_project"
    - "resume_project"
    - "cancel_project"
    - "approve_escalation"
    - "force_verification"
    - "force_rerun"
    - "reprioritize_project"
    - "request_status_snapshot"

observability:
  required_metrics:
    - "project_id"
    - "task_id"
    - "agent_id"
    - "model_used"
    - "duration_ms"
    - "sandbox_id"
    - "result_status"
    - "retry_count"
    - "artifact_paths"
    - "zulip_message_ids"
  logs_required: true
  raw_transcript_retention_required: true

implementation_order:
  phase_1_foundation:
    - "Create agent registry configuration"
    - "Create model routing configuration"
    - "Create schemas for tasks, results, escalations, and Zulip message blocks"
    - "Create authoritative state store"
    - "Create artifact store"
    - "Create Zulip gateway service"
    - "Create sandbox runner contract"
  phase_2_core_execution:
    - "Implement Niaobe state machine"
    - "Implement Morpheus state machine"
    - "Implement Planner prompt and runner"
    - "Implement Implementer prompt and runner"
    - "Implement Tester prompt and runner"
    - "Implement Oracle prompt and runner"
  phase_3_stability:
    - "Add stop conditions and retry budgets"
    - "Add dedupe and queue recovery for Zulip"
    - "Add human override commands"
    - "Add workspace isolation strategy"
  phase_4_quality:
    - "Add evaluation harness"
    - "Add regression suite"
    - "Add dashboards or structured operational reports"
    - "Add runbooks for common failures"

builder_agent_must_generate:
  - "config/agent_registry.yaml"
  - "config/model_map.yaml"
  - "config/routing_rules.yaml"
  - "communication/zulip_gateway_config.yaml"
  - "schemas/task_envelope.schema.json"
  - "schemas/response_envelope.schema.json"
  - "schemas/escalation_packet.schema.json"
  - "schemas/zulip_task_message.schema.json"
  - "schemas/zulip_result_message.schema.json"
  - "orchestrators/niobe_state_machine.yaml"
  - "orchestrators/morpheus_state_machine.yaml"
  - "prompts/master.md"
  - "prompts/neo.md"
  - "prompts/agent_smith.md"
  - "prompts/niaobe.md"
  - "prompts/architect.md"
  - "prompts/morpheus.md"
  - "prompts/oracle.md"
  - "prompts/planner.md"
  - "prompts/implementer.md"
  - "prompts/tester.md"
  - "communication/zulip_gateway.py"
  - "communication/topic_router.py"
  - "communication/message_mapping_store.py"
  - "runtime/docker_sandbox_profiles.yaml"
  - "runtime/artifact_serializers.py"
  - "runtime/artifact_parsers.py"
  - "database/schema.sql"
  - "evaluation/regression_suite.md"

acceptance_criteria_for_builder_agent:
  - "All agents can be instantiated from registry data without handwritten special cases except model overrides."
  - "Niaobe can read an Oracle verification report and choose reroute, retry, escalate, or close."
  - "Morpheus always spawns Planner, Implementer, and Tester individually."
  - "Every Morpheus success path includes a test_execution_report."
  - "Planner, Implementer, and Tester are not directly callable by Niaobe."
  - "Architect and Oracle can return to the requesting agent."
  - "A new specialist agent can be registered without rewriting the project flow contract."
  - "Zulip can be restarted or lose queue state without losing authoritative workflow state."
  - "A software task can be reproduced from workspace state plus orchestrator state."
```

---

## Human-readable interpretation

## 1. The whole shape in one sentence

This is a **two-loop system**:
- **Niaobe** runs the **project loop**.
- **Morpheus** runs the **software loop**.

Everything else exists to either frame work, perform bounded work, or verify results.

## 2. The authority split

### Executive and intake layer
- **MASTER**: final authority for priority, risk, and exceptional overrides.
- **Neo**: clarifies goals, constraints, and tradeoffs.
- **AgentSmith**: turns requests into project charters and hands the project to Niaobe.

### Orchestration layer
- **Niaobe**: decides project-level next steps.
- **Morpheus**: decides software-level next steps.

### Specialist layer
- **Architect**: design and technical boundaries.
- **Oracle**: project-level verification.
- **Planner**: software plan and test obligations.
- **Implementer**: code changes.
- **Tester**: test changes, test runs, and defect signals.

That split is the entire point. It stops agents from drifting into each other's jobs.

## 3. The most important workflow rule

A project is not done because code exists.
A project is done when:
- design happened,
- implementation happened,
- Oracle verified the result.

And software work is not done because code compiles.
Software work is done when:
- Planner ran,
- Implementer ran,
- Tester ran,
- a test execution report exists.

## 4. Why Zulip is not the database

Zulip is for:
- human requests,
- agent handoffs that should be visible,
- approvals,
- escalations,
- audit history.

Zulip is **not** for:
- project state truth,
- task state truth,
- artifact storage,
- routing logic.

That is why the gateway exists. Otherwise every agent becomes a half-broken chat client with a god complex.

## 5. The gateway pattern

Use **one Zulip gateway service**.

The gateway must:
- manage bot identities and subscriptions,
- consume Zulip events,
- map streams and topics to project/task ids,
- validate YAML message blocks,
- persist authoritative state,
- dispatch work to agents,
- post results back to Zulip,
- recover cleanly when Zulip queues expire.

Do **not** give each agent its own Zulip client implementation.

## 6. The workspace contract

The software workspace mounted at `/workspace` is the operational surface for Morpheus and the software team.

Minimum required state:
- `PROJECT.md`
- `management/STATUS.md`
- `management/MILESTONES.md`
- `management/BACKLOG.md`
- `management/DECISIONS.md`
- `management/TEST_REPORT.md`

Recommended additions:
- `artifacts/incoming/`
- `artifacts/outgoing/`
- `artifacts/reports/`
- `tests/`
- optional `.agents/` for local runtime bootstrapping

If Zulip and workspace state disagree, fix the workspace first, then publish the corrected summary through the gateway.

## 7. The clean happy path

1. Human or MASTER makes a request.
2. AgentSmith frames it into a project charter.
3. Niaobe takes ownership of project orchestration.
4. Niaobe gets architecture from Architect.
5. Niaobe assigns software delivery to Morpheus.
6. Morpheus runs Planner -> Implementer -> Tester until the software package is good enough.
7. Niaobe sends the result to Oracle.
8. Oracle returns a verification report.
9. Niaobe closes, reroutes, retries, or escalates.

## 8. The intended MVP boundary

For the first implementation:
- keep **Planner, Implementer, and Tester internal-only**,
- make **Morpheus** the visible software-facing agent,
- support **one working end-to-end project** before building multi-project concurrency,
- use strict schemas everywhere,
- enforce stop conditions from day one.

## 9. The next implementation files

The builder agent should generate the config, schemas, prompts, gateway, state machines, and storage contracts listed in the authoritative YAML above.

That is the actual implementation package. The markdown is just the map humans need so they stop improvising bad abstractions.

---

## Supporting documents

These remain useful supporting references, but this file is the handoff document to build from:
- `agentic_workflow.md`
- `zulip_communication_spec.md`
- `SOFTWARE_WORKSPACE_README.md`

