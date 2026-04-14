# Software Workspace Template

This file is a reusable starting README for a software project workspace used by the current agentic system.

In the current model:

* **Niobe** owns project-level orchestration.
* **Morpheus** owns software delivery orchestration.
* **Planner -> Implementer -> Tester** is Morpheus's internal software loop.
* **Oracle** verifies the project at the project level after Niobe requests verification.
* **Zulip is transport and audit**, not the source of truth.

Inside the Docker sandbox, this project workspace is mounted at `/workspace`.

## Purpose

This workspace exists to:

* hold the software team's working context,
* store project-level software documents and delivery artifacts,
* let Morpheus and the internal software team run locally and repeatably,
* provide stable inputs and outputs for the Zulip gateway and the higher-level project workflow.

## Recommended Variables

Replace these values for each project:

* `YOUR_PROJECT_WORKSPACE`: host path to the software project root
* `YOUR_PROJECT_ID`: project identifier used across Zulip, the gateway, and internal state
* `YOUR_SOFTWARE_STREAM_NAME`: Zulip stream used for software requests and delivery summaries
* `YOUR_SOFTWARE_MANAGER_BOT_NAME`: visible Zulip software manager bot name

Recommended defaults for the current template:

* `YOUR_SOFTWARE_STREAM_NAME`: `software`
* `YOUR_SOFTWARE_MANAGER_BOT_NAME`: `Morpheus`

## Ownership Model

Use this workspace with the following ownership boundaries:

* **Niobe** may assign software work into this workspace, but does not manage individual implementation attempts.
* **Morpheus** owns sequencing, retries, and handoff between Planner, Implementer, and Tester.
* **Planner, Implementer, and Tester** are internal software agents by default and should not post directly to Zulip unless you intentionally expose them.
* **Oracle** consumes the resulting delivery package through the project workflow and does not replace the software test loop.

## Source of Truth

For software execution, the source of truth is:

* `PROJECT.md`
* `management/`
* project code, tests, and generated delivery artifacts in this workspace

Zulip should be treated as:

* request transport,
* human and agent communication,
* audit trail,
* approval and escalation surface

If Zulip messages and workspace files disagree, Morpheus should update the workspace first and then send a corrected summary back through the gateway.

## Expected Structure

The mounted project workspace should contain at minimum:

* `PROJECT.md`
* `management/`
* the software repository or repositories being changed

Recommended files inside `management/`:

* `STATUS.md`
* `MILESTONES.md`
* `BACKLOG.md`
* `DECISIONS.md`
* `TEST_REPORT.md`

Optional but recommended:

* `artifacts/`
* `artifacts/outgoing/`
* `artifacts/reports/`

If the project also carries its own local OpenClaw runtime, it may additionally contain:

* `.agents/project.db`
* `.agents/runtime/incoming/`
* `.agents/runtime/runtime_responses/`
* `.agents/openclaw/workspace/`
* `.agents/openclaw/agents/`

### Example Layout

```text
/workspace
├── PROJECT.md
├── management/
│   ├── STATUS.md
│   ├── MILESTONES.md
│   ├── BACKLOG.md
│   ├── DECISIONS.md
│   └── TEST_REPORT.md
├── artifacts/
│   ├── outgoing/
│   └── reports/
├── src/...
├── tests/...
└── .agents/
    ├── project.db
    ├── runtime/
    │   ├── incoming/
    │   └── runtime_responses/
    └── openclaw/
        ├── workspace/
        └── agents/
```

## Required Document Semantics

### `PROJECT.md`

`PROJECT.md` should define the current software mission clearly enough for Morpheus and the internal team to operate without guessing. It should include:

* project summary,
* scope and non-goals,
* constraints,
* architecture notes or links,
* implementation commands,
* test commands,
* acceptance criteria,
* deployment or runtime notes if relevant.

### `management/STATUS.md`

Track:

* current delivery status,
* current active task,
* known blockers,
* latest completed software cycle,
* next recommended step.

### `management/BACKLOG.md`

Track:

* queued software tasks,
* task priority,
* dependency notes,
* whether a task is ready for planning or blocked.

### `management/MILESTONES.md`

Track:

* milestone targets,
* milestone completion state,
* what remains before each milestone is done.

### `management/DECISIONS.md`

Track:

* major software decisions,
* rationale,
* assumptions,
* reversibility,
* follow-up actions.

### `management/TEST_REPORT.md`

Track:

* latest test execution summary,
* failing and passing suites,
* gaps in automated coverage,
* tester verdict,
* evidence needed for Oracle or Niobe.

## Morpheus Software Loop

For every software task, Morpheus should use this loop unless a smaller direct action is explicitly justified:

1. Read `PROJECT.md`, `management/`, recent artifacts, and the relevant code.
2. Spawn **Planner** to produce or refine an implementation plan and test intent.
3. Spawn **Implementer** to make the code changes and add or update tests.
4. Spawn **Tester** to validate the result against the plan and acceptance criteria.
5. If Tester fails:

   * rerun Implementer with the defect report, or
   * rerun Planner first if the plan or task framing is wrong.
6. When Tester passes, Morpheus updates the workspace documents and produces a delivery summary.
7. Morpheus returns the delivery package to the requester, usually Niobe.

### Required Delivery Rule

Every non-trivial software task should result in:

* implementation changes,
* test changes or explicit test justification,
* updated status documentation,
* a test report.

Do not treat software work as complete if code changed but validation evidence is missing.

## First Local Steps

1. Bootstrap the project documents from `project_template/` if the project does not already have them.
2. Update `PROJECT.md` with the real project summary, constraints, commands, architecture notes, and acceptance criteria.
3. Update `management/STATUS.md`, `management/MILESTONES.md`, `management/BACKLOG.md`, `management/DECISIONS.md`, and `management/TEST_REPORT.md` to reflect the real state.
4. If the project carries its own local runtime, render the local OpenClaw config:

```bash
bash .agents/scripts/setup_local_team.sh
```

5. Validate Morpheus locally if needed:

```bash
bash .agents/run_manager.sh "Read PROJECT.md and management/, identify the next best software task, then plan execution."
```

6. Validate the internal software loop locally if needed:

```bash
bash .agents/run_team.sh "Implement the requested change, add or update tests, validate the result, and update management docs."
```

7. Once the Zulip gateway is configured, let the gateway invoke Morpheus using the software request topic for this project.

## Zulip Integration Notes

Recommended defaults:

* stream: `software`
* topic pattern: `<PROJECT_ID> impl` or `<PROJECT_ID> software`

Recommended behavior:

* the gateway posts the request into Zulip,
* Morpheus consumes the request through the gateway,
* internal Planner, Implementer, and Tester runs stay internal unless explicitly mirrored,
* Morpheus posts back a summary and references the updated artifacts,
* Niobe decides what happens next at the project level.

Do not rely on Zulip topic history as the only execution state.

## Artifact Expectations

Recommended inputs in `artifacts/incoming/`:

* architecture notes,
* requirement extracts,
* upstream task packets,
* verification feedback,
* defect reports.

Recommended outputs in `artifacts/outgoing/` or `artifacts/reports/`:

* implementation summaries,
* patch notes,
* dependency notes,
* test summaries,
* handoff packets for Niobe or Oracle.

## Notes

* Treat this workspace as the software team's operational surface.
* Keep project-specific code and files in this workspace, not in the template.
* Keep `.agents/` inside the project only when the project needs its own local runtime. In a shared multi-project setup, `.agents/` stays in the shared control workspace.
* Do not commit generated `.agents/openclaw.json`, runtime state, secrets, or transient logs if this workspace becomes its own repository.
* Keep bot-facing summaries short, but keep file-based state explicit and durable.
