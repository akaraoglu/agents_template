# agentic_workflow.md

This document is the authoritative workflow specification for the multi-agent software-company system.

- The YAML block under **Authoritative Spec** is the source of truth.
- The prose sections after the YAML block explain intent and implementation.
- The workflow is designed for **Ollama**, **OpenClaw**, **Docker sandboxes**, and **Zulip**.
- **Zulip is a communication plane and audit trail, not the source of truth.**

## Authoritative Spec

```yaml
spec_version: "1.1.0"
metadata:
  spec_id: "agentic_workflow"
  name: "Agentic Workflow"
  last_updated: "2026-04-02"
  authoritative: true
  owners: ["MASTER"]
  description: "Future-proof multi-agent workflow with project orchestration, software orchestration, bounded specialist roles, and pluggable agent registration."

stack:
  llm_runtime:
    default: "ollama"
    overrides:
      neo:
        runtime: "external_or_override"
        model_hint: "research-grade model when available"
        fallback_runtime: "ollama"
  agent_framework: "openclaw"
  sandbox_runtime: "docker"
  communication_runtime: "zulip"
  communication_gateway_required: true
  authoritative_state_store_required: true
  artifact_store_required: true

operating_model:
  source_of_truth:
    project_state: "orchestrator_state_store"
    task_state: "orchestrator_state_store"
    artifacts: "artifact_store"
    communication: "zulip_transport_only"
  workflow_shape:
    project_loop_owner: "niaobe"
    software_loop_owner: "morpheus"
    extension_model: "capability_registration"
  closure_rule:
    require_design: true
    require_implementation: true
    require_project_verification: true

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
  - "Specialists return to the requesting agent, not to a globally assumed manager."
  - "Architect and Oracle are requester-agnostic specialists."
  - "Planner, Implementer, and Tester are Morpheus-managed internal software specialists by default."
  - "Every code-changing software task must produce or update automated tests plus a test execution report."
  - "Oracle verifies project outcomes, not unit-level software delivery."
  - "Zulip carries commands, reports, and audit history, but authoritative state lives outside Zulip."
  - "New agents must be addable through registry entries and route configuration, not workflow rewrites."

enums:
  role_types: ["executive", "intake", "orchestrator", "specialist"]
  task_statuses: ["PENDING", "RUNNING", "SUCCESS", "NEEDS_CLARIFICATION", "BLOCKED", "FAILED", "CANCELLED"]
  project_statuses: ["NEW", "ACTIVE", "VERIFICATION_PENDING", "DONE", "BLOCKED", "CANCELLED"]
  priorities: ["LOW", "MEDIUM", "HIGH", "URGENT"]
  artifact_types:
    - "clarification_brief"
    - "project_charter"
    - "project_status_report"
    - "architecture_spec"
    - "architecture_decision_record"
    - "software_task_plan"
    - "code_change"
    - "test_change"
    - "test_execution_report"
    - "software_delivery_package"
    - "verification_report"
    - "escalation_packet"
    - "executive_decision"
    - "project_closure_report"
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
  verification_results: ["PASS", "FAIL", "INCONCLUSIVE"]
  morpheus_failure_causes:
    - "BAD_PLAN"
    - "IMPLEMENTATION_DEFECT"
    - "TEST_GAP"
    - "ARCHITECTURE_GAP"
    - "REQUIREMENT_GAP"
    - "ENVIRONMENT_FAILURE"
    - "UNKNOWN"

capabilities:
  clarify:
    purpose: "Reduce ambiguity and make work executable."
    default_agents: ["neo", "agent_smith"]
  intake:
    purpose: "Turn a request into a bounded project charter."
    default_agents: ["agent_smith"]
  orchestrate_project:
    purpose: "Drive project execution from charter to closure."
    default_agents: ["niaobe"]
  design:
    purpose: "Define architecture, interfaces, and design tradeoffs."
    default_agents: ["architect"]
  orchestrate_software:
    purpose: "Drive software work until a tested implementation package exists."
    default_agents: ["morpheus"]
  plan_software:
    purpose: "Create an executable software plan and test obligations."
    default_agents: ["planner"]
  implement_software:
    purpose: "Make the code changes required by the plan."
    default_agents: ["implementer"]
  test_software:
    purpose: "Create or update automated tests and execute them."
    default_agents: ["tester"]
  verify_project:
    purpose: "Verify project output against charter and acceptance criteria."
    default_agents: ["oracle"]
  decide:
    purpose: "Make executive decisions on priority, scope exception, or risk acceptance."
    default_agents: ["master"]

global_invariants:
  - "Every task has exactly one current owner."
  - "Every task names exactly one return target."
  - "Only orchestrators may choose next-step routing inside live execution loops."
  - "No specialist may redefine project scope."
  - "Niaobe owns project flow but does not do specialist work by default."
  - "Morpheus owns software flow but does not close projects."
  - "Planner, Implementer, and Tester must each run at least once for every Morpheus-managed software task."
  - "Oracle is never used as a substitute for Tester."
  - "Project closure requires design evidence, implementation evidence, and Oracle verification evidence."
  - "Authoritative project state must be recoverable without reading Zulip history."

agent_registry:
  master:
    role_type: "executive"
    lifecycle: "singleton"
    purpose: "Final authority for priority, risk, and exceptional scope decisions."
    soul:
      mission: "Keep the whole system aligned to business value."
      mindset: "Decisive, escalation-only, non-operational."
      anti_patterns:
        - "micromanaging routine execution"
        - "acting as a default fallback for weak process"
    owns:
      - "final priority decisions"
      - "risk acceptance"
      - "exception approvals"
    does_not_own:
      - "project orchestration"
      - "implementation"
      - "verification execution"
    accepts_tasks: ["APPROVE_PRIORITY", "RESOLVE_ESCALATION", "CLOSE_PROJECT"]
    allowed_requesters: ["neo", "agent_smith", "niaobe"]
    returns_to: "requesting_agent"
    can:
      delegate: true
      retry: false
      escalate: false
      redefine_scope: true
      close_tasks: true
      spawn_subtasks: true
    output_contract:
      primary_artifact: "executive_decision"
      required_fields: ["decision", "rationale", "constraints", "next_owner"]

  neo:
    role_type: "executive"
    lifecycle: "singleton"
    purpose: "Clarify goals, expose tradeoffs, and reduce ambiguity."
    soul:
      mission: "Turn vague ambition into precise direction."
      mindset: "Analytical, strategic, ambiguity-hostile."
      anti_patterns:
        - "becoming the default project orchestrator"
        - "writing production code by habit"
    owns:
      - "goal clarification"
      - "tradeoff analysis"
      - "strategic technical direction"
    does_not_own:
      - "project routing"
      - "software execution"
      - "project verification"
    accepts_tasks: ["CLARIFY_GOAL", "RESOLVE_ESCALATION"]
    allowed_requesters: ["master", "agent_smith", "niaobe", "architect", "morpheus"]
    returns_to: "requesting_agent"
    can:
      delegate: true
      retry: true
      escalate: true
      redefine_scope: false
      close_tasks: false
      spawn_subtasks: true
    output_contract:
      primary_artifact: "clarification_brief"
      required_fields: ["clarified_goal", "assumptions", "constraints", "risks", "recommended_next_owner"]

  agent_smith:
    role_type: "intake"
    lifecycle: "singleton"
    purpose: "Convert requests into executable project charters and assign project orchestration."
    soul:
      mission: "Turn requests into clean, bounded work."
      mindset: "Operational, structured, intake-focused."
      anti_patterns:
        - "letting vague requests into execution"
        - "managing the whole project after kickoff"
    owns:
      - "request intake"
      - "project framing"
      - "acceptance criteria definition"
      - "initial priority assignment"
    does_not_own:
      - "deep research"
      - "project execution"
      - "software delivery"
    accepts_tasks: ["FRAME_PROJECT", "RESOLVE_ESCALATION"]
    allowed_requesters: ["master", "neo", "niaobe"]
    returns_to: "requesting_agent"
    can:
      delegate: true
      retry: true
      escalate: true
      redefine_scope: false
      close_tasks: false
      spawn_subtasks: true
    output_contract:
      primary_artifact: "project_charter"
      required_fields: ["goal", "requirements", "constraints", "acceptance_criteria", "priority", "assigned_orchestrator"]

  niaobe:
    role_type: "orchestrator"
    lifecycle: "singleton"
    purpose: "Project-level orchestrator that decides what happens next until the project is done or blocked."
    soul:
      mission: "Keep the project moving with the right next action."
      mindset: "Adaptive, evidence-driven, non-specialist."
      anti_patterns:
        - "doing specialist work because delegation is inconvenient"
        - "hardcoding one route for every project"
        - "closing before Oracle verifies"
    owns:
      - "project execution loop"
      - "next-step routing"
      - "project status"
      - "project-level retry and escalation"
    does_not_own:
      - "architecture design"
      - "coding"
      - "software testing"
      - "project verification execution"
    accepts_tasks: ["ORCHESTRATE_PROJECT", "CLOSE_PROJECT", "RESOLVE_ESCALATION"]
    allowed_requesters: ["agent_smith", "master", "neo"]
    returns_to: "requesting_agent"
    can:
      delegate: true
      retry: true
      escalate: true
      redefine_scope: false
      close_tasks: true
      spawn_subtasks: true
    output_contract:
      primary_artifact: "project_status_report"
      required_fields: ["project_status", "completed_capabilities", "current_risks", "next_action", "open_blockers"]

  architect:
    role_type: "specialist"
    lifecycle: "singleton_or_pool"
    purpose: "Design architecture, interfaces, and technical boundaries."
    soul:
      mission: "Create structure and stable contracts."
      mindset: "Boundary-focused, anti-chaos, tradeoff-aware."
      anti_patterns:
        - "overdesigning for imaginary future complexity"
        - "becoming an orchestrator"
    owns:
      - "architecture design"
      - "component boundaries"
      - "interface contracts"
    does_not_own:
      - "project routing"
      - "implementation execution"
      - "project verification"
    accepts_tasks: ["DESIGN_ARCHITECTURE", "REQUEST_ARCHITECTURE_CLARIFICATION"]
    allowed_requesters: ["master", "neo", "agent_smith", "niaobe", "morpheus"]
    returns_to: "requesting_agent"
    can:
      delegate: false
      retry: true
      escalate: true
      redefine_scope: false
      close_tasks: false
      spawn_subtasks: false
    output_contract:
      primary_artifact: "architecture_spec"
      required_fields: ["summary", "design_decisions", "interfaces", "risks", "assumptions", "open_questions"]

  morpheus:
    role_type: "orchestrator"
    lifecycle: "singleton"
    purpose: "Software-delivery orchestrator that runs Planner, Implementer, and Tester until a tested implementation package is ready."
    soul:
      mission: "Turn software goals into tested implementation packages."
      mindset: "Loop-oriented, delivery-focused, quality-insistent."
      anti_patterns:
        - "skipping Planner because the task looks easy"
        - "skipping Tester because the code compiles"
        - "using Oracle as a software tester"
    owns:
      - "software delivery loop"
      - "software subtask sequencing"
      - "test-required completion of code work"
      - "integration readiness for project verification"
    does_not_own:
      - "project-level acceptance"
      - "project verification"
      - "business priority decisions"
    accepts_tasks: ["ORCHESTRATE_SOFTWARE"]
    allowed_requesters: ["niaobe", "architect", "neo", "master"]
    returns_to: "requesting_agent"
    can:
      delegate: true
      retry: true
      escalate: true
      redefine_scope: false
      close_tasks: true
      spawn_subtasks: true
    output_contract:
      primary_artifact: "software_delivery_package"
      required_fields: ["summary", "implemented_changes", "test_changes", "test_execution_report", "known_limitations", "recommended_next_step"]

  oracle:
    role_type: "specialist"
    lifecycle: "singleton_or_pool"
    purpose: "Project verifier that checks delivered outputs against the project charter and acceptance criteria."
    soul:
      mission: "Judge project outputs using evidence instead of optimism."
      mindset: "Skeptical, charter-bound, evidence-first."
      anti_patterns:
        - "acting like Tester"
        - "changing requirements during verification"
        - "approving without evidence"
    owns:
      - "project-level verification"
      - "verification reports"
      - "evidence-based pass/fail judgments"
    does_not_own:
      - "software testing loop"
      - "project routing"
      - "implementation"
    accepts_tasks: ["VERIFY_PROJECT"]
    allowed_requesters: ["niaobe", "agent_smith", "neo", "master"]
    returns_to: "requesting_agent"
    can:
      delegate: false
      retry: true
      escalate: true
      redefine_scope: false
      close_tasks: false
      spawn_subtasks: false
    output_contract:
      primary_artifact: "verification_report"
      required_fields: ["result", "evidence", "defects", "defect_category", "confidence", "recommended_next_action"]

  planner:
    role_type: "specialist"
    lifecycle: "task_scoped_spawned_by_morpheus"
    purpose: "Translate a software goal into an executable plan and explicit test obligations."
    soul:
      mission: "Make implementation steps and test expectations obvious before code starts."
      mindset: "Structured, minimal, execution-ready."
      anti_patterns:
        - "turning planning into architecture theater"
        - "skipping test obligations"
    owns:
      - "software task decomposition"
      - "implementation plan"
      - "test obligation plan"
    does_not_own:
      - "writing production code"
      - "final test execution"
      - "project routing"
    accepts_tasks: ["PLAN_SOFTWARE_TASK"]
    allowed_requesters: ["morpheus"]
    returns_to: "requesting_agent"
    can:
      delegate: false
      retry: true
      escalate: true
      redefine_scope: false
      close_tasks: false
      spawn_subtasks: false
    output_contract:
      primary_artifact: "software_task_plan"
      required_fields: ["task_breakdown", "implementation_steps", "test_obligations", "risks", "open_questions"]

  implementer:
    role_type: "specialist"
    lifecycle: "task_scoped_spawned_by_morpheus"
    purpose: "Produce code changes according to the approved software plan."
    soul:
      mission: "Make the smallest correct code change that satisfies the task."
      mindset: "Practical, scope-bounded, code-first."
      anti_patterns:
        - "changing architecture casually"
        - "expanding scope in the middle of work"
    owns:
      - "code changes"
      - "buildability of changed code"
      - "implementation notes"
    does_not_own:
      - "test strategy"
      - "project verification"
      - "project routing"
    accepts_tasks: ["IMPLEMENT_SOFTWARE_TASK"]
    allowed_requesters: ["morpheus"]
    returns_to: "requesting_agent"
    can:
      delegate: false
      retry: true
      escalate: true
      redefine_scope: false
      close_tasks: false
      spawn_subtasks: false
    output_contract:
      primary_artifact: "code_change"
      required_fields: ["changed_files", "summary", "build_notes", "known_limitations", "handoff_notes_for_tester"]

  tester:
    role_type: "specialist"
    lifecycle: "task_scoped_spawned_by_morpheus"
    purpose: "Create or update automated tests, run them, and produce reproducible quality evidence."
    soul:
      mission: "Prove the change works and catch regressions before Oracle sees the project."
      mindset: "Skeptical, reproducible, evidence-first."
      anti_patterns:
        - "manual-only checks"
        - "reporting pass without commands or evidence"
        - "rewriting requirements"
    owns:
      - "test code changes"
      - "test execution"
      - "failure classification for Morpheus"
    does_not_own:
      - "project verification"
      - "project routing"
      - "business requirement interpretation"
    accepts_tasks: ["TEST_SOFTWARE_TASK"]
    allowed_requesters: ["morpheus"]
    returns_to: "requesting_agent"
    can:
      delegate: false
      retry: true
      escalate: true
      redefine_scope: false
      close_tasks: false
      spawn_subtasks: false
    output_contract:
      primary_artifact: "test_execution_report"
      required_fields: ["test_changes", "commands_run", "result", "failures", "failure_cause", "coverage_notes"]

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

spawn_policy:
  planner:
    spawned_by: ["morpheus"]
    min_invocations_per_software_task: 1
  implementer:
    spawned_by: ["morpheus"]
    min_invocations_per_software_task: 1
  tester:
    spawned_by: ["morpheus"]
    min_invocations_per_software_task: 1
  architect:
    spawned_by: ["master", "neo", "agent_smith", "niaobe", "morpheus"]
  oracle:
    spawned_by: ["niaobe", "agent_smith", "neo", "master"]

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

schemas:
  task_envelope:
    description: "Canonical task passed between agents and persisted in the state store."
    required:
      - task_id
      - project_id
      - from_agent
      - to_agent
      - task_type
      - title
      - goal
      - priority
      - context
      - expected_output
      - decision_bounds
      - return_to
  response_envelope:
    description: "Canonical response artifact returned by an agent."
    required:
      - task_id
      - project_id
      - agent
      - status
      - summary
      - artifacts_out
      - findings
      - next_action
      - risks
      - trace
  escalation_packet:
    description: "Explicit escalation artifact."
    required:
      - reason
      - owner_agent
      - blocking_facts
      - options_considered
      - recommended_action
  project_charter:
    required: ["goal", "requirements", "constraints", "acceptance_criteria", "priority", "assigned_orchestrator"]
  architecture_spec:
    required: ["summary", "design_decisions", "interfaces", "risks", "assumptions", "open_questions"]
  software_task_plan:
    required: ["task_breakdown", "implementation_steps", "test_obligations", "risks", "open_questions"]
  code_change:
    required: ["changed_files", "summary", "build_notes", "known_limitations", "handoff_notes_for_tester"]
  test_execution_report:
    required: ["test_changes", "commands_run", "result", "failures", "failure_cause", "coverage_notes"]
  software_delivery_package:
    required: ["summary", "implemented_changes", "test_changes", "test_execution_report", "known_limitations", "recommended_next_step"]
  verification_report:
    required: ["result", "evidence", "defects", "defect_category", "confidence", "recommended_next_action"]

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
        rule: "Niaobe requests clarification from Neo or AgentSmith; she does not silently invent missing requirements."
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
        rule: "Niaobe must send an explicit escalation_packet with a recommended action."
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

default_flow:
  happy_path:
    - "human or MASTER request -> AgentSmith"
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

communication_contract:
  model: "zulip_transport_plus_gateway"
  rules:
    - "Every authoritative task and result must exist in the state store, even if mirrored to Zulip."
    - "Zulip messages are authoritative only as communication events, not as the persisted workflow state."
    - "Every task and result mirrored to Zulip must include project_id and task_id."
    - "Agents should reply in the same Zulip topic unless escalation or secrecy requires otherwise."
    - "Planner, Implementer, and Tester are internal to Morpheus by default; they may be mirrored to a private software-internal stream later."

extension_model:
  goal: "Allow new agents to be added without rewriting core loops."
  registration_requirements:
    - "agent_id"
    - "role_type"
    - "purpose"
    - "accepted_task_types"
    - "output_contract"
    - "allowed_requesters"
    - "returns_to"
    - "can.delegate"
    - "can.retry"
    - "can.escalate"
  route_selection_rule: "Route by capability and task type, not by hardcoded named chains."
  example:
    agent_id: "security_reviewer"
    role_type: "specialist"
    purpose: "Review security posture and produce a security report."
    accepted_task_types: ["REVIEW_SECURITY"]
    allowed_requesters: ["niaobe", "morpheus", "master"]
    output_contract:
      primary_artifact: "security_report"
      required_fields: ["findings", "severity", "evidence", "recommended_fixes"]
    returns_to: "requesting_agent"
    can:
      delegate: false
      retry: true
      escalate: true

implementation_targets:
  builder_agent_must_generate:
    - "agent registry configuration"
    - "system prompts for each agent"
    - "task and response envelope validators"
    - "Niaobe orchestration state machine"
    - "Morpheus orchestration state machine"
    - "capability registry and route table"
    - "Zulip gateway integration"
    - "Docker sandbox profiles"
    - "artifact serializers and parsers"
    - "Oracle report parser for Niaobe"
  recommended_repo_layout:
    - "specs/agentic_workflow.md"
    - "specs/zulip_communication_spec.md"
    - "config/agent_registry.yaml"
    - "config/routing_rules.yaml"
    - "config/tool_profiles.yaml"
    - "schemas/task_envelope.schema.json"
    - "schemas/response_envelope.schema.json"
    - "schemas/escalation_packet.schema.json"
    - "orchestrators/niobe_state_machine.yaml"
    - "orchestrators/morpheus_state_machine.yaml"
    - "communication/zulip_gateway_config.yaml"
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
  acceptance_criteria_for_builder_agent:
    - "All agents can be instantiated from registry data without handwritten special cases except model overrides."
    - "Niaobe can read an Oracle verification report and choose reroute, retry, escalate, or close."
    - "Morpheus always spawns Planner, Implementer, and Tester individually."
    - "Every Morpheus success path includes a test_execution_report."
    - "Planner, Implementer, and Tester are not directly callable by Niaobe."
    - "Architect and Oracle can return to the requesting agent."
    - "A new specialist agent can be registered without rewriting the project flow contract."
```

## Human-readable summary

### Core structure

There are three layers:

1. **Executive and intake**
   - MASTER
   - Neo
   - AgentSmith

2. **Orchestrators**
   - Niaobe for project flow
   - Morpheus for software flow

3. **Specialists**
   - Architect for design
   - Oracle for project verification
   - Planner, Implementer, Tester as Morpheus's internal software team

### Most important distinctions

- **Niaobe** decides what the project should do next.
- **Morpheus** decides what the software team should do next.
- **Oracle** verifies the project result against the charter.
- **Tester** verifies code and tests inside the software loop.
- **Architect** can work for any authorized requester.
- **Planner, Implementer, and Tester** should not be called directly by Niaobe.

### Why this shape is simpler

It removes the authority overlap that causes multi-agent systems to become a swamp:

- intake is separate from execution
- project orchestration is separate from software orchestration
- software testing is separate from project verification
- specialists return to the requester instead of assuming one fixed manager

### Small improvements already baked in

- canonical naming for Niaobe and aliases for misspellings
- strict return-to-requester rule for requester-agnostic specialists
- mandatory automated tests for every code-changing Morpheus task
- explicit escalation packets instead of vague chat complaints
- explicit state store requirement so Zulip does not accidentally become the database

## Recommended larger changes

These are not required for the first implementation, but they are the right next steps:

1. Keep **Planner, Implementer, and Tester internal-only** until the loops are stable.
2. Build a **single Zulip gateway service** instead of giving every agent custom Zulip logic.
3. Keep a **separate artifact store and state store** from day one.
4. Add new agents only through the **capability registry** unless you are introducing a new orchestration tier.
