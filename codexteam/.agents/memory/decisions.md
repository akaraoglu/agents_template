# Decisions Memory

## Entries

- CodexTeam is a local specification-driven workflow toolkit, not an application server, controller, board, HTTP API, or MCP service.
- Historical archives are obsolete and are never merged into the current system.
- Generated cold-start projects default to `./projects` beneath `/home/alik/workspace/agent_template/codexteam`.
- Task IDs use canonical uppercase form; the standard sequence is `T001` through `T004`.
- Handoff and result v1 shapes are machine-readable and enforced by Python.
- `qwen36-27b` is the default tool-using profile for implementation, testing, review, and documentation. `gemma4-26b` is optional for bounded secondary review, not default ownership of evidence-producing or editing tasks.
- Worker completion is a claim. Only independent verification and leader-owned closure complete a task.
- Process commands use structured argument arrays; raw shell evaluation is prohibited.
- Each logical attempt owns a private persistent SQLite/session state and exact thread ID. Local profiles use a private Codex home. Authenticated OpenAI profiles reuse the source Codex home so credentials are not copied into project runtime; resume still replays model, provider, catalog, reasoning effort, and verbosity.
- Draft, feedback, and final are conversation phases, not separate attempts. Only intentional capability/ownership transfer, irrecoverable session loss, material scope change, or explicit abandonment creates a new attempt.
- Role defaults are routing hints. Evidence of repeated task-specific capability failure justifies a recorded profile transfer without involving the operator.
- The shared brief is a one-page orientation layer and must be synchronized by the Project Lead after every closure; canonical close-loop state alone cannot update project-specific milestone prose.
- `gpt54-mini` is an installed and verified cloud candidate, not yet the repository default. The 2026-07-16 six-task canary completed with one attempt per task and no capability transfer; operator choice still governs any default-routing change.
- Small coherent projects use a proportional five-role fast lane: Project Lead, one functional Developer, independent Tester, evidence-reusing Reviewer, and evidence-reusing Documenter. The default initialized task set remains T001-T004; T005 is an explicit documenter opt-in for workflows such as the controlled canary.
- The controlled Fibonacci E2E uses medium reasoning, a 300-second per-turn timeout, a 1,800-second reported budget, no automatic retry or profile transfer, and exact same-session recovery after an observable failure. Qwen remains the repository default; `gpt54-mini` is selected explicitly for this canary.
- `/home/alik/workspace/agent_template/codexteam` is the guaranteed cold-start base folder. The root Codex session is the Project Lead, projects are initialized beneath `./projects`, and root `AGENTS.md` is the mandatory low-token phase router.
- A new-project request follows separate approvals for proposal, initialization, planning, and execution. Initializer task files are scaffolding until the Project Lead replaces generic wording with project-specific responsible-AI handoffs and the operator authorizes execution.
- Cold-start context uses progressive disclosure: the first proposal relies on root `AGENTS.md`; `.agents/LEAD_BOOT.md` is read before initialization; detailed project-init, planning, orchestration, verification, recovery, and delivery guidance loads only for its active phase.
- Generated cold-start projects use `./projects` beneath `/home/alik/workspace/agent_template/codexteam`; older `/home/alik/workspace/codexspace/projects` defaults are obsolete for this repository's guaranteed boot flow.
- A clean Fibonacci-class cold-start canary has four independent verdict dimensions: lifecycle, product, evidence integrity, and proportional performance. Canonical delivery alone cannot pass the canary.
- The cold-start performance target is at most 30 minutes, 12 worker turns, one correction round per role, one million uncached lead-input tokens, and 50,000 lead-output tokens when usage is available. Exceeding a target must be reported rather than hidden by eventual delivery.
- Stable lead-authored feedback lives at `<project>/.codexteam/lead-prompt-<task>-<attempt>.md`; the Project Lead reuses the exact path across feedback and finalization.
