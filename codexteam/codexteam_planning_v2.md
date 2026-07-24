# CodexTeam V2 Minimal Development Plan

**Status:** Metrics/WebUI foundation and project command center implemented and accepted; later optimization experiments remain measured work
**Date:** 2026-07-24
**Primary goal:** Make verified project delivery faster, less expensive, and easier to observe without complicating the working CodexTeam workflow.

## 1. Design Rule

V2 must use the minimum code that solves the measured problem.

- No features beyond the approved scope.
- No abstraction for single-use behavior.
- No flexibility or configuration without a current requirement.
- No duplicate source of truth.
- No handling for scenarios that cannot occur in the supported workflow.
- No framework merely to make future expansion possible.
- If a smaller implementation is equally clear and correct, use it.
- Agents remain responsible for judgment; code enforces only existing boundaries and contracts.

The first implementation sequence is:

```text
agree on minimal metrics
  -> read them from existing artifacts
  -> persist only genuinely missing turn measurements
  -> strengthen the existing Fibonacci acceptance tests
  -> capture the V1 baseline
  -> build the small read-only WebUI
  -> verify the UI and E2E values
  -> measure later V2 changes one at a time
```

## 2. Current Team Design Does Not Change

The metrics and WebUI phase must not change:

- Project initialization.
- SDD documents and approval gates.
- Project-specific task design.
- One responsible AI per task.
- Local model selection.
- Persistent task sessions.
- `draft -> feedback -> final` conversations.
- Result validation.
- Independent verification.
- Project Lead state closure.
- Existing project and runtime layout.
- Existing launcher commands.
- Sandbox and workspace boundaries.
- Human-controlled Git push, PR/MR, merge, release, and deployment.

All worker and specialist roles are local by default with an explicitly selected installed local profile. A cloud Project Lead remains recommended for extensive planning, while a local lead remains selectable for bounded projects.

V2 will not use MCP servers. Git, GitHub CLI, project CLIs, and small repository scripts are sufficient.

## 3. Permitted Design Changes

Only these changes are permitted during the metrics and WebUI phase.

### 3.1 Read existing artifacts

The WebUI reads the existing sources of truth directly:

- `PROJECT_STATE.md`
- `CURRENT_TASK.md`
- `TASKS.md`
- `BRIEF.md`
- `session.json`
- Turn `.jsonl`, message, and stderr files
- Final result JSON
- Verification evidence
- Existing E2E reports

No database, event bus, event framework, migration system, import process, or duplicate project-state store is introduced.

### 3.2 Persist only missing turn measurements

First audit whether the existing session and Codex JSONL files already expose the approved metrics.

If measured turn duration or token usage is not durably available, add one backward-compatible `turns` list to the existing `session.json` record. A turn entry may contain only:

```json
{
  "number": 1,
  "phase": "draft",
  "status": "draft_ready",
  "duration_seconds": 42.3,
  "input_tokens": 1200,
  "cached_input_tokens": 800,
  "output_tokens": 240
}
```

Rules:

- Store launcher-measured duration, not an agent estimate.
- Store token fields only when the provider reports them.
- Missing values remain absent. Compact UI surfaces omit them; detailed views may identify evidence as unavailable.
- Do not add a new telemetry file format if existing artifacts are sufficient.
- Do not change prompts, routing, result contracts, or closure behavior.

This is the only planned runtime-record change. If the audit proves it unnecessary, it is not implemented.

### 3.3 Add a small read-only local WebUI

The first UI:

- Binds only to loopback.
- Reads files directly when a page is requested.
- Uses page reload or a refresh button.
- Does not edit project files.
- Does not start, retry, finalize, verify, close, commit, push, or publish work.

### 3.4 Strengthen existing Fibonacci tests

Extend the existing tests and E2E runner. Do not create a second benchmark framework.

## 4. Explicitly Excluded

The first V2 implementation does not include:

- SQLite or another database.
- General event schemas or normalized event infrastructure.
- SSE, WebSockets, or background filesystem watchers.
- A separate public API.
- A queue or scheduler.
- GPU, CPU, RAM, or energy monitoring.
- A monetary pricing or cost-calculation engine.
- Plugin or integration frameworks.
- WebUI recovery or write actions.
- WebUI task editing.
- Authentication for a loopback-only process.
- Historical import or data migrations.
- Retention configuration.
- Charts when a table communicates the result.
- Remote task-manager, search, or database integrations.
- GitHub automation beyond approved Git/GitHub CLI use in a later measured task.
- Node.js, npm, or a frontend build step.
- React, Vue, Svelte, HTMX, Tailwind, Bootstrap, or another frontend framework.
- FastAPI, Django, an ORM, or a production WSGI deployment layer.
- Playwright for the initial server-rendered UI.

An excluded feature requires a new demonstrated problem and explicit approval.

## 5. Minimal Metrics

The metrics must answer:

1. Is the project moving?
2. Where is execution time being spent?
3. How many model turns and corrections were needed?
4. How much reported cloud and local inference was used?
5. Did product, evidence, management state, and performance pass?
6. Is a candidate V2 run better than the baseline?

### 5.1 Project metrics

- Project status.
- Active task.
- Execution start and last update when observable.
- Execution elapsed time.
- Total, completed, failed, and blocked tasks.
- Total worker turns.
- Total feedback/correction turns.
- Total verification duration when available.
- Final lifecycle, product, evidence, management, and performance verdicts.

For ordinary projects, execution time begins at the earliest worker session timestamp. The controlled E2E runner remains authoritative for full run duration. The UI must label these definitions rather than imply that unrecorded planning time was measured.

### 5.2 Task metrics

- Task ID and objective.
- Responsible AI.
- Selected local model profile.
- Current phase and status.
- Attempt ID.
- Turn count.
- Feedback/correction count.
- Task elapsed time.
- Verification status and duration when available.
- Last recorded error and diagnostic path.

### 5.3 Turn metrics

- Turn number.
- `draft`, `feedback`, or `final` phase.
- Status.
- Measured duration.
- Model and profile.
- Local or cloud provider.
- Input, cached-input, and output tokens when reported.
- Error summary and diagnostic path.

### 5.4 Comparison metrics

- Verified delivery time.
- Worker turns.
- Corrections.
- Failed turns.
- First-draft acceptance.
- First-final validity.
- Reported cloud tokens.
- Reported local tokens.
- Product verdict.
- Evidence-integrity verdict.
- Management-state verdict.
- Performance verdict.

### 5.5 Cost discipline

The first version shows token counts, not estimated currency:

- Cloud input tokens.
- Cloud cached-input tokens.
- Cloud output tokens.
- Local input and output tokens when reported.
- Cloud turns.
- Local turns.

Local inference is not described as free; it has zero direct cloud-token billing but consumes local time and hardware. A monetary calculator is deferred until a provider reports cost directly or the operator explicitly requests a versioned pricing feature.

### 5.6 Quality gates

Report these independently:

| Gate | Pass condition |
|---|---|
| Lifecycle | Tasks used valid ownership, sessions, results, verification, and closure |
| Product | Approved behavioral tests passed |
| Evidence | Review and delivery claims exist in their named evidence |
| Management | Task, project, result, brief, and delivery state agree |
| Manifest | No scratch, temporary, secret, or runtime files remain |
| Performance | Approved time, turn, token, and correction limits pass |

A clean E2E pass requires every applicable gate. `DELIVERED` state alone is insufficient.

## 6. Minimum WebUI

The UI contains two read-only views.

### 6.1 Project list

Use a modern, minimalist command-center layout. Place each project in exactly one group: Needs attention, Active, or Recently completed. Order each group by latest recorded activity.

Project cards show:

- Project name.
- Status.
- Active task.
- Completed/total tasks.
- Execution elapsed time.
- Turns.
- Corrections.
- Last update.

### 6.2 Project detail

Show a compact project header, current assignment, quality-gate strip, and responsible-AI roster. Project tasks use a read-only six-lane Kanban:

```text
Backlog -> In Progress -> In Review -> In Validation -> Blocked -> Done
```

Each lane initially shows its ten newest tasks and exposes the remainder through a native `Show N older…` disclosure. Milestone IDs are grouping metadata; canonical task IDs lead every task title. Expanded Task details show attempts, turns, duration, reported tokens, errors, diagnostics, and verification evidence. Also show:

- Current or last error.
- Exact diagnostic path.
- Reported cloud/local token totals.
- Lifecycle, product, evidence, management, manifest, and performance verdicts.

### 6.3 WebUI acceptance

The WebUI is ready when:

- It derives state from existing project/runtime artifacts.
- It renders an active, delivered, failed, and incomplete fixture.
- Missing compact metrics and all-missing verdict groups are omitted instead of rendered as empty or `unknown` tiles.
- Every task shows its responsible AI and selected model profile.
- Projects and tasks are ordered by latest recorded activity.
- Kanban cards, Current Focus, Task details, Agent activity, and portfolio focus use `M#` as grouping metadata and `T### — objective` as the task title.
- Each Kanban lane shows ten newest tasks before an inline older-task disclosure.
- Task phases, attempts, and recorded turns can be inspected without leaving project context.
- The top-right theme menu defaults to System Default and offers persistent Light and Dark choices.
- Diagnostic paths are visible without reconstructing IDs.
- Quality verdicts remain independent.
- Reload shows updated state.
- It binds only to loopback.
- It cannot mutate project or Git state.

## 7. Fibonacci E2E Changes

Improve the existing product tests and canary only.

### 7.1 Product acceptance

Add or confirm:

1. Correct Fibonacci values across the approved range.
2. Explicit `n=0` and `n=1` behavior.
3. Versioned exact output for one nontrivial tree such as `n=4` or `n=5`.
4. Mandatory assertion for the previously missed right-subtree indentation.
5. Deterministic repeated output captured inside the test harness.
6. Help text states the actual accepted range.
7. Missing, negative, non-integer, and out-of-range input behavior.
8. Correct stdout, stderr, and exit codes.
9. No scratch output, exploratory helper, incomplete source, secret, or runtime file in delivery.

### 7.2 Team E2E

The existing canary continues to verify:

- Cold-start lead discovery.
- Separate initialization/planning and execution approval.
- Exact generated-path continuity.
- Project-specific tasks.
- One responsible AI and selected local profile per worker task.
- Persistent `draft -> feedback -> final` sessions.
- Independent verification and state closure.
- Evidence claims supported by named artifacts.
- Clean final manifest.
- Minimal metrics visible in the WebUI.

### 7.3 Existing recovery tests

Retain and extend existing deterministic failure tests only where the current defect requires it, including timeout, invalid result, failed verification, and same-session correction. Do not build a second live failure matrix.

### 7.4 Comparison rule

Compare baseline and candidate runs under the same model, reasoning effort, fixture, timeout, budget, and comparable warm/cold condition. Change one V2 behavior at a time. Repeat a costly live run only when variance makes the result ambiguous.

The initial Fibonacci performance ceiling remains:

- At most 30 minutes.
- At most 12 worker turns.
- At most one correction round per role.
- No operator intervention after `GO` except a genuine showstopper.
- At most one million uncached lead-input tokens when reported.
- At most 50,000 lead-output tokens when reported.

Exceeding a ceiling is a performance failure even if delivery eventually succeeds.

## 8. Development Tasks

Every task has one responsible AI. Worker and specialist tasks use a selected local profile.

### M001 — Approve the minimum contract

**Responsible AI:** `metrics-lead-01`, leader role.
**Outcome:** Approve the metric list, field definitions, WebUI views, Fibonacci additions, exclusions, and settled stack in this document.
**Done when:** No unresolved design decision blocks artifact inspection or implementation planning.
**Dependency:** None.

### M002 — Map existing artifacts

**Responsible AI:** `metrics-developer-01`, local developer role.
**Outcome:** Map every approved metric to an existing file and field; identify only metrics that are genuinely missing.
**Required output:** A concise field map and samples from successful and failed sessions.
**Verification:** Another agent can reproduce each mapped value from the named artifact.
**Dependency:** M001.

### M003 — Persist missing turn measurements

**Responsible AI:** `metrics-developer-01`, same local owner as M002.
**Outcome:** If M002 proves duration or usage is missing, add only the minimal backward-compatible `session.json` turn fields. If nothing is missing, close this task with no code change.
**Verification:** Existing session behavior and tests remain unchanged; new values equal launcher/provider evidence.
**Dependency:** M002.

### M004 — Verify metric extraction

**Responsible AI:** `metrics-tester-01`, local tester role.
**Outcome:** Verify successful, failed, feedback, final, and missing-token cases.
**Verification:** Durations, counts, tokens, status, and missing-value behavior match fixture artifacts.
**Dependency:** M002 and M003 when M003 changes code.

### M005 — Strengthen Fibonacci acceptance

**Responsible AI:** `fibonacci-tester-01`, local tester role.
**Outcome:** Add the missing golden, right-subtree, help, boundary, stream, determinism, and manifest checks to the existing tests and runner.
**Verification:** The known indentation defect is detected and the corrected fixture passes.
**Dependency:** M001.

### M006 — Capture the V1 baseline

**Responsible AI:** `baseline-analyst-01`, local tester role.
**Outcome:** Run the unchanged workflow with verified metric extraction and strengthened Fibonacci acceptance.
**Required output:** One preserved baseline project/report with quality verdicts and minimal metrics.
**Verification:** Metrics are reproducible from named artifacts and no V2 behavior optimization is present.
**Dependency:** M004 and M005.

### M007 — Build the minimum WebUI

**Responsible AI:** `webui-developer-01`, local developer role.
**Outcome:** Implement the grouped project command center, read-only six-lane Kanban, expandable execution details, Agent activity, task/milestone identity hierarchy, themes, and responsive layouts with Flask, Jinja templates, plain CSS, and direct artifact reads.
**Allowed files:** `src/codexteam_tools/webui.py`, its package-local templates/static files, `scripts/run-webui.py`, `requirements-webui.txt`, and focused WebUI tests.
**Verification:** It renders the M006 baseline and approved failure fixtures, binds to loopback, and exposes no mutation action.
**Dependency:** M006.

### M008 — Verify the WebUI

**Responsible AI:** `webui-tester-01`, local tester role.
**Outcome:** Verify both views, grouping and activity ordering, ten-card lane disclosure, task/milestone identity, expandable execution detail, missing-value omission, verdict separation, themes, responsive behavior, reload behavior, loopback binding, and the read-only boundary.
**Verification:** Focused pytest and Flask test-client checks pass. The small theme selector is checked in Chromium; Playwright is not required.
**Dependency:** M007.

### M009 — Run integrated E2E

**Responsible AI:** `e2e-tester-01`, local tester role.
**Outcome:** Run the strengthened Fibonacci canary and confirm that its artifacts and WebUI values agree.
**Verification:** Lifecycle, product, evidence, management, manifest, and performance verdicts are independently reported.
**Dependency:** M008.

### M010 — Accept the foundation

**Responsible AI:** `project-lead-01`, leader role.
**Outcome:** Review M009 evidence and approve or reject the metrics/WebUI foundation before any other V2 behavior change.
**Verification:** The accepted implementation matches this minimal scope and contains no excluded architecture.
**Dependency:** M009.

## 9. Delivery Gates

1. No WebUI code before M004 validates the available metrics.
2. No baseline before the Fibonacci product acceptance catches the known defect.
3. No other V2 behavior change before M006 preserves the V1 baseline.
4. No V2 optimization experiment before M010 accepts the WebUI foundation.
5. No remote Git publication by an agent.

## 10. Later V2 Experiments

After M010, test one change at a time against the preserved baseline:

- Medium versus high routine reasoning.
- Smaller role-specific context.
- Better project-specific task contracts.
- Better evidence reuse.
- Fewer result-contract corrections.
- Less repeated Project Lead inspection.
- Same-session recovery improvements.
- Proportional role selection for small projects.
- Local Git Steward and read-oriented GitHub CLI workflow.

For each experiment:

```text
one problem
  -> one small change
  -> focused tests
  -> comparable Fibonacci E2E
  -> inspect WebUI and E2E reports
  -> keep or revert
```

Keep a change only when required quality gates continue to pass and a target metric improves without an unacceptable regression.

## 11. Settled Decisions

- Existing artifacts remain authoritative.
- No database is introduced.
- No general event or telemetry framework is introduced.
- Only missing turn measurements may be added to `session.json`.
- Missing compact metrics are omitted; detailed views identify unavailable evidence without fabricating values.
- The first WebUI is loopback-only and read-only.
- The UI has only an activity-sorted project dashboard and project detail view.
- Page reload or a refresh button is sufficient.
- Token counts are shown; monetary cost estimation is deferred.
- Existing Fibonacci tests and runner are extended, not replaced.
- The metrics/WebUI phase does not redesign team operation.
- No MCP server is used.
- Python 3.12, Flask, Jinja, plain HTML/CSS, and pytest are the WebUI stack.
- JavaScript is limited to the theme selector and browser-local preference; no frontend framework is used.
- Other V2 changes wait for the accepted baseline and UI.

## 12. Settled Software Stack

### 12.1 Runtime

Use the existing environment:

| Component | Selected version |
|---|---|
| Python | 3.12.3 |
| Flask | 3.1.3 |
| Jinja | 3.1.6 |
| Werkzeug | 3.1.8, installed through Flask |
| pytest | 8.4.2 |

Declare only Flask as a WebUI runtime dependency. Jinja and Werkzeug remain Flask dependencies. Do not add a package manager; use a one-line `requirements-webui.txt` containing `Flask==3.1.3`.

### 12.2 Server

- One Flask application.
- Flask's built-in server.
- Bind exactly to `127.0.0.1:5000`.
- Debug mode and the reloader disabled.
- GET routes only.
- No separate API.
- No production deployment server because this is a local operator tool.

Routes:

```text
GET /                                      project list
GET /projects/<project-id>                 project detail
```

Project IDs must use the repository's existing identifier and path-containment checks. Standard Flask responses are sufficient for an unknown project; do not build a custom error subsystem.

### 12.3 Rendering

- Server-rendered Jinja templates.
- Jinja autoescaping enabled.
- Plain semantic HTML, CSS Grid, and native expandable details.
- One plain CSS file.
- Normal links.
- Page reload or a Refresh link.
- One small plain JavaScript file for System Default, Light, and Dark theme selection.

Templates:

```text
base.html
projects.html
project.html
```

### 12.4 Data access

Read `./projects` directly on every request. Use two small internal operations:

```text
list projects
load one project
```

Keep them as functions until actual repeated complexity proves another structure necessary. Do not introduce service layers, repositories, adapters, caches, data-transfer objects, or generic parsers.

### 12.5 Source layout

```text
src/codexteam_tools/webui.py
src/codexteam_tools/templates/webui/
  base.html
  projects.html
  project.html
src/codexteam_tools/static/webui.css
scripts/run-webui.py
tests/test_webui.py
requirements-webui.txt
```

`scripts/run-webui.py` is a thin entrypoint. Keep artifact reading, metric calculation, and the two routes in `webui.py` initially. Split the file only if the actual implementation becomes clearly smaller or easier to understand after the split.

### 12.6 Run command

```bash
../env-python/bin/python scripts/run-webui.py
```

### 12.7 Tests

Use pytest and Flask's test client:

- Metric extraction against temporary project fixtures.
- Route status and rendered-content checks.
- GET-only and read-only checks.
- Loopback binding at the entrypoint boundary.
- Latest-activity ordering for projects and tasks.
- Task, attempt, and turn rendering.
- Missing-value omission and neutral unavailable-state display.

Do not add Playwright unless a later approved feature introduces browser behavior that Flask's test client cannot verify.

## 13. Implementation Evidence

The approved minimal foundation is implemented without changing project initialization, routing, ownership, result contracts, closure, or recovery policy.

| Task | Result |
|---|---|
| M001–M002 | Minimum contract approved; existing artifacts mapped. JSONL remains authoritative for reported tokens. |
| M003–M004 | `session.json` now records only missing per-turn phase, status, and launcher-measured duration. Existing launcher behavior remains compatible. |
| M005 | The existing Fibonacci runner now uses one repository-owned acceptance harness for range, golden, indentation, determinism, help, streams/statuses, and manifest checks. |
| M006 | Preserved V1 baseline `fibonacci-tree-cli-e2e-20260717-091635-3498537` correctly reports the known help failure. |
| M007–M008 | The two-view Flask/Jinja WebUI, loopback binding, direct artifact reads, mutually exclusive project grouping, six-lane Kanban, ten-card disclosure, task/milestone hierarchy, Agent activity, execution drill-down, themes, responsive behavior, escaping, reload behavior, missing-value omission, and read-only boundary are verified. |
| M009 | Recovered Gemma candidate `fibonacci-tree-cli-v2-gemma-20260722` passes lifecycle, product, evidence, management, and manifest gates but fails performance at 15 turns. Qwen candidate `fibonacci-tree-cli-v2-20260722-1125` timed out during T002 before implementation. |
| M010 | The measurement/WebUI foundation is accepted because it exposes these failures accurately. No later V2 optimization is accepted or implemented by this phase. |

Validation evidence:

- Repository suite: 185 tests passed after the final command-center redesign.
- Focused WebUI suite: 45 tests passed after the final milestone/task hierarchy correction.
- Loopback smoke test: HTTP 200 from `127.0.0.1:5000` with the preserved baseline visible.
- Recovered Gemma product and manifest: PASS.
- Recovered Gemma elapsed time: 802 seconds; 15 turns; 3 feedback turns; 2 rejected final turns; 2,077,125 reported local tokens.
- The per-role correction ceiling passed: T002, T003, and T004 each used one feedback round. The shell canary has no model-driven Project Lead session, so the lead-input/output token ceilings are not applicable; worker-token totals are reported separately and are not compared to lead ceilings.

The next V2 experiment should target result-envelope reliability and smaller local-worker context. Those changes remain outside this accepted foundation and must be measured one at a time against the preserved baseline.

## 14. V2.1 Result Finalization Experiment

The first post-foundation experiment targeted result-envelope correction cost without changing task ownership, session persistence, verification, or closure.

Minimal changes:

- OpenAI-backed final turns receive the existing `result-v1` output schema.
- Local final turns receive a compact contract instead of a large example or an unsupported schema claim.
- The launcher supplies only deterministic bookkeeping: a missing or blank result ID, an omitted empty follow-up list for completed work, process output, and string normalization for message-bearing error, warning, or limitation objects.
- The E2E report accepts optional Codex-reported Project Lead duration and token totals so the existing lead ceilings can be evaluated when that surface exposes them.
- Worker processes disable Python bytecode writes, and the Fibonacci development contract requires capture-based checks instead of printing large successful trees.

Deterministic verification passed with 190 repository tests.

### Qwen canary outcome

The fresh `qwen36-27b` candidate `fibonacci-tree-cli-v21-qwen-20260724-111544` proved that T001 now drafts, finalizes, validates, and closes on its first pass. T002 still timed out at 300 seconds, so the candidate correctly failed its performance gate and remained preserved.

The T002 evidence separates this failure from the earlier infrastructure and transcript-volume problems:

- The worker started normally and used the selected Qwen profile.
- It performed 21 command calls and 22 reasoning events; it was not waiting on MCP, Ollama startup, or filesystem access.
- Command output fell from 145,932 bytes in the earlier Qwen candidate to 15,719 bytes.
- No `__pycache__` directory or `.pyc` file was created.
- The worker repeatedly rewrote and rechecked the Unicode renderer, never reached the test/README work, and produced no draft message before timeout.

### Decision and next target

Keep the finalization changes: they remove avoidable local-envelope corrections while preserving semantic validation.

Do not increase the timeout. The next isolated experiment is project-specific task sizing for local models:

1. Split the current all-in-one T002 into one bounded core model/rendering task and one bounded CLI/tests/README task.
2. Keep independent integration, evidence review, and delivery review.
3. Keep one responsible AI and one persistent attempt per task.
4. Keep the same Qwen profile, reasoning effort, 300-second turn limit, 1,800-second run budget, product fixture, and quality gates.
5. Accept the split only if the full canary passes within the existing 12-turn ceiling and improves verified delivery time without weakening evidence.

This is a task-design experiment, not a new scheduler, recovery mechanism, or agent-control layer.
