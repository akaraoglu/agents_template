# OpenClaw Canary Playbook

## Goal
Stabilize the OpenClaw agent team by using one fixed end-to-end canary to expose
real failures, then applying the smallest fix in the correct layer.

## Trigger
Use this playbook for:
- Neo -> Smith -> Niaobe -> worker failures
- empty-stop agent turns
- missing handoff acks or downstream reports
- planning / orchestration / validation regressions in the live team

## Default canaries
- Phase canary runner:
  `bash AgenticTeam/scripts/run_openclaw_phase_canary.sh --phase <neo_project_create|smith_planning|smith_niaobe_handoff|architect_worker_runtime|morpheus_direct_implementation|oracle_verification>`
- Baseline suite runner:
  `bash AgenticTeam/scripts/run_canary_suite.sh`
- Primary end-to-end baseline canary:
  `bash AgenticTeam/scripts/run_e2e_fibonacci_test.sh`
- Canonical E2E report artifact:
  `/home/alik/.copilot/session-state/27757261-2eab-44e0-a711-3a33df12c25c/files/fibonacci-e2e-report.md`

## Why this loop exists
- Prompt tightening alone has repeatedly produced new breakpoints instead of
  durable fixes.
- OpenClaw agents are one-shot and can stop early, so helpers, validators,
  allowlists, and explicit workflow contracts matter more than prose alone.
- A fixed canary gives one stable reproduction surface while the control plane
  is being stabilized.

## Core routine
1. Run the smallest matching phase canary first.
2. Capture the structured canary report and the concrete project/session evidence.
3. Identify the first real boundary where expected behavior diverged.
4. Classify the root cause before editing anything:
   - **prompt_contract**
   - **helper_guard**
   - **allowlist_policy**
   - **runtime_state_machine**
   - **session_staleness**
   - **model_empty_or_malformed**
   - **external_service**
   - **unknown**
5. Make the smallest relevant change in that layer.
6. Rerun the same phase canary.
7. Rerun the fixed Fibonacci E2E canary.
8. Record the durable lesson in the correct repo guidance file.

## Recommended baseline order
1. `neo_project_create`
2. `smith_planning`
3. `smith_niaobe_handoff`
4. `architect_worker_runtime`
5. `morpheus_direct_implementation`
6. `oracle_verification`
7. `run_e2e_fibonacci_test`

## Critique and limits
- The Fibonacci canary is the **baseline canary**, not proof that all workflow
  shapes are healthy.
- Phase canaries are diagnostic-only. They may create throwaway projects and send
  handoffs, but they must not modify prompts, allowlists, or live config.
- One red/green run is not enough evidence for a durable design conclusion.
- Do not jump straight from one failure to "prompt bug" or "design bug" without
  first classifying the failing layer.
- If the same fault survives two fix attempts, stop patching prompt prose and
  escalate it as a structural issue in `decisions.md`.

## Routing rules for write-back
- Durable mechanism or contract change -> `.agents/memory/decisions.md`
- Mistake pattern or bad prior assumption -> `.agents/memory/corrections.md`
- Concrete user request / action history -> `.agents/memory/changelog.md`
- Reusable execution workflow -> `.agents/skills/` or `.agents/playbooks/`
- Tool invocation / environment usage -> `.agents/capabilities/tools.md`

## Immediate design principles
- Use the same canary before and after the fix.
- Prefer tooling, helper scripts, and explicit contracts over more prompt prose.
- Keep fixes small and topic-focused.
- Treat worker silence and empty-stop turns as control-boundary failures, not as
  harmless model quirks.
- When a fix changes prompt or policy contracts, assume fresh OpenClaw sessions
  may be required before trusting the rerun.
