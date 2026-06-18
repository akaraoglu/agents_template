# Skill: project_management

## Purpose

To provide a standardized, repeatable workflow for an Agent acting as 'Leader' in a CodexTeam project, ensuring strict adherence to Spec-Driven Development (SDD) principles and maintaining the single source of truth.

## When to use it

Use this skill whenever an agent is assigned the **Leader** role or is tasked with managing/orchestrating any phase of a `codexteam` project.

## Inputs needed

- `PROJECT.md`: The primary specification and requirement document.
- `BRIEF.md`: High-level overview and scope.
- `TASKS.md`: The master task ledger and progress tracker.
- `IMPLEMENTATION_PLAN.md`: The sequence of execution steps.
- `management/tasks/[ID].md`: Detailed handoff instructions for specific tasks.
- `PROJECT_STATE.md`: The real-time status of the project engine.

## Step-by-step workflow

1.  **Phase 1: Requirements & Skeleton (T001)**
    - Analyze user requests to define precise, testable acceptance criteria in `PROJECT.md`.
    - Set up the project directory structure (`src/`, `tests/`, `management/`).
    - Create the initial task handoff files (`management/tasks/T002.md`, etc.).
    - Initialize state tracking in `PROJECT_STATE.md` and `CURRENT_TASK.md`.

2.  **Phase 2: Task Delegation & Orchestration**
    - For each upcoming task, create a "Handoff Contract" including: **Context**, **Allowed Paths**, **Stop Conditions**, and **Required Outputs**.
    - Update the `TASKS.md` ledger to reflect the new 'planned' tasks.

3.  **Phase 3: Monitoring & State Management**
    - Continuously update `PROJECT_STATE.md` (e.g., changing status from `PLANNING` to `IMPLEMENTATION`).
    - Update `CURRENT_TASK.md` to reflect the active task being worked on or reviewed.
    - Ensure `DECISIONS.md` and `OPEN_QUESTIONS.md` are updated with every significant project change.

4.  **Phase 4: Verification & Gatekeeping (Critical)**
    - **Do not accept work blindly.** When a worker completes a task, manually verify the implementation against the acceptance criteria defined in `PROJECT.md`.
    - Run any necessary smoke checks or tests if provided in the task contract.
    - If verification passes: Update `TASKS.md` to 'completed' and move to the next task.
    - If verification fails: Reject the work, document the reason in `CORRECTIONS.md`, and instruct the worker on how to remediate.

5.  **Phase 5: Delivery & Closure (T004)**
    - Compile all evidence into a final delivery manifest.
    - Finalize `DONE_REPORT.md` summarizing the project outcome.

## Expected output

A completed, verified software artifact accompanied by a full suite of SDD artifacts (`PROJECT.md`, `DECISIONS.md`, `TASKS.md`, etc.) that proves all requirements were met through a transparent, traceable process.

## Common mistakes or failure modes

- **Losing the Source of Truth:** Failing to update `PROJECT_STATE.md` or `TASKS.md`, making project progress invisible to stakeholders.
- **Vague Handoffs:** Creating task files without clear "Stop Conditions" or "Required Outputs," leading to worker error/hallucination.
- **Blind Acceptance:** Passing tasks as 'completed' without verifying the actual implementation against `PROJECT.md`.
- **Scope Creep:** Allowing the project to expand beyond the defined `In-Scope` boundaries in `PROJECT.md` without updating the plan.

## Related files

- `.agents/capabilities/coding_standards.md`
- `.agents/memory/decisions.md`
