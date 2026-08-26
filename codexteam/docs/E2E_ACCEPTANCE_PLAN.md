# End-to-End Acceptance Plan

## E2E-000: Cold-Start Project Lead Discovery

Start a fresh Codex session with `/home/alik/workspace/agent_template/codexteam` as its working directory and provide only a short request such as “create a new project.” Prove that the agent:

- identifies itself as the root Project Lead from `AGENTS.md`;
- discovers `.agents/LEAD_BOOT.md`, reads it before initialization, and avoids broad guidance discovery;
- reuses supplied facts and asks only for material missing decisions;
- proposes the project description and management plan before initialization;
- previews control-only initialization beneath
  `/home/alik/workspace/codexspace/projects` with the repository-root command;
- treats initialized task files as scaffolding rather than approved execution;
- waits for separate planning and execution approval; and
- knows that approved worker work uses persistent draft → feedback → final sessions with independent closure.

This scenario fails if the operator must explain the CodexTeam role, script locations, project root, approval gates, or worker-session protocol.

## E2E-001: Project Initialization

Preview and create a disposable project. Prove the complete file set exists, all template tokens are rendered, and the project is contained beneath the configured root.

## E2E-002: Structured Worker Result

Run a fake Codex executable that returns a valid result. Prove the final matching JSON is selected, process output is recorded, and a schema-valid result is persisted.

## E2E-003: Failure Handling

Exercise malformed output, wrong task/attempt, process failure, and timeout. Each case must persist a valid failure/partial result and return a nonzero exit code.

## E2E-004: Task Closure

Close a completed result with an independent verification command. Prove the task ledger and state documents advance only after the command passes.

## E2E-005: Delivery

Complete the final task in a disposable project. Prove `DELIVERY.md`, `DONE_REPORT.md`, `RESULT.md`, and `PROJECT_STATE.md` agree.

## E2E-006: Cold Start Through Team Delivery

Run this combined acceptance scenario with a fresh Codex session whose working directory is exactly `/home/alik/workspace/agent_template/codexteam`. Give the agent only a small product request; do not inject the CodexTeam protocol into the prompt.

1. **Proposal:** the lead identifies its role, proposes the aim, scope, description, acceptance criteria, and management phases, and creates no project files before approval.
2. **Initialization and planning:** after approval, the lead initializes a control-only project under `/home/alik/workspace/codexspace/projects`, registers product source separately, preserves the exact project ID and absolute `Created:` path returned by the initializer, replaces generic scaffolding with project-specific milestones, architecture, implementation plan, and responsible-AI handoffs, and waits for a separate execution approval.
3. **Team execution:** after `GO` or an equivalent end-to-end authorization, the lead delegates implementation, testing, review, and documentation to the named responsible AIs. “Handle it yourself” means autonomous orchestration, not solo implementation; only an explicit “do not spawn agents” instruction selects solo work.
   Before a local worker launch, the lead checks the Ollama endpoint from the same execution surface. A reachable nested route may use `--trust-parent-sandbox`; if the parent sandbox cannot reach host Ollama, the approved host-level route omits the flag and retains the normal worker sandbox. A successful dry run alone is not connectivity evidence, and MCP is not required.
4. **Conversation and recovery:** worker changes use persistent draft → feedback → final sessions. Corrections resume the same responsible AI, attempt, and exact stored thread unless ownership intentionally changes or the session is irrecoverable.
5. **Evidence and closure:** planned files are written with the editing interface, while the launcher and closure commands capture worker and verification evidence. The lead does not manufacture evidence with shell redirection, `tee`, heredocs, or command substitution.
6. **Delivery:** every planned task has a responsible AI, independent verification succeeds, task and management state agree, and delivery artifacts describe the product that actually passed acceptance.
7. **Acceptance audit:** compare at least one nontrivial exact output with the approved convention or golden artifact, inspect the final project manifest, and fail the canary for scratch files, incomplete experiments, or reviewer claims not present in their named evidence.
8. **Proportional performance:** for a Fibonacci-class project, target no more than 30 minutes, 12 worker turns, one correction round per role, one lead update per state change or 60-second wait, one million uncached lead-input tokens, and 50,000 lead-output tokens when usage is reported. Exceeding a target is a performance failure even when canonical delivery eventually closes.

The run report records the fresh lead thread, exact project path, worker roles and session paths, feedback or retry events, verification commands, final state, elapsed time, and token usage when available. A path typo, manually reconstructed generated ID, unrequested solo implementation, redundant nested sandbox failure, or operator explanation of the orchestration protocol fails this scenario.

Schema-valid results and `DELIVERED` state do not override an acceptance-audit failure. The report must separate lifecycle success, product success, evidence integrity, and performance so a partial improvement cannot be presented as a clean E2E pass.

## Live Canary

After all deterministic scenarios pass, run one explicitly approved local-model sentinel. Verify the requested artifact directly; do not rely on the worker status alone.

## Release Blockers

- Any write outside the project root
- Any shell evaluation
- Invalid output accepted as completed
- Missing evidence accepted for completion
- Task state advanced after failed verification
- Documentation referencing nonexistent commands or old system components
- A fresh root agent cannot discover the Project Lead role and new-project lifecycle from `AGENTS.md`
- A lead reconstructs a generated project path instead of reusing initializer output
- An end-to-end authorization is treated as permission to bypass responsible-AI delegation
- A reviewer attributes exact-output, determinism, range, or error-stream checks to an artifact that does not contain those observations
- Scratch run outputs or incomplete experimental source remain in a delivered project
- A small clean-path canary exceeds its proportional time, turn, or token target without being reported as a performance failure
