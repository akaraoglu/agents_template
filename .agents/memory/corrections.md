## 2026-05-05
- Mistake: Human workflow routing drifted into runtime keyword classification, which caused brittle phrase-specific fixes and contradicted the goal that managers reason about intent.
- Correction: Keep runtime out of semantic keyword guessing. Human intake should be `agent_decides`; agents declare `intent` and `visibility`, and runtime validates only the declared action contract.
- Mistake: Neo treated advisory DMs as workflow when the human used negated phrases such as "do not hand off" because the old classifier matched the positive words inside the negation.
- Correction: This phrase-level fix was a stopgap; the durable correction is to remove keyword classification and require agent-declared intent/action payloads.
- Mistake: Some autonomous advisory continuations dropped `conversation_mode` and `context_project_slug`, which let read-only project analysis fall back into workflow routing and project-stream replies.
- Correction: Every queued run-turn continuation must preserve the conversation mode and context project slug.

## 2026-04-20
- Mistake: Looked outside the requested `/home/alik/workspace/zulip` path while investigating possible bridge code.
- Correction: When the user scopes inspection to a specific folder, stay inside that folder unless they explicitly expand the scope.

## 2026-04-21
- Mistake: The first autonomous loop slice allowed `next_state=continue` even when the model produced no file writes or follow-up messages, which let AgentSmith repeat plans instead of making progress.
- Correction: Treat `continue` as valid only when the turn made concrete progress, and keep stale approval rules out of the active prompts when the current policy has removed them.
- Mistake: The runner let a model-generated invalid write path crash the whole process.
- Correction: Normalize only a small set of harmless path prefixes, keep the writable-root guard strict, and downgrade invalid writes into handled run errors instead of process exits.
- Mistake: Fresh human messages on a terminal run were enqueued without reopening the run, so the worker skipped them as `run_not_runnable` and the agents appeared stalled.
- Correction: New intake messages must reopen existing terminal runs into `queued` state so the worker treats them as actionable.
- Mistake: DM follow-up questions could lose the active project context because the resolved project slug was not persisted on the run and reused on later turns.
- Correction: Persist the active `project_slug` on the run and reuse it for follow-up turns when the new message does not name a project explicitly.
- Mistake: Active queued jobs were only recovered when the worker heartbeat itself became stale, which allowed orphaned jobs to sit in `queue/active` while a healthy-but-idle worker never reclaimed them.
- Correction: Recover stale jobs by per-job `claimed_at` age and worker ownership, and immediately requeue leftover active jobs during worker startup so restart/recovery does not strand prior work.
- Mistake: The new delegation smoke test showed that non-target agents with active stream runs could still consume later project-topic messages and emit noisy `I did not continue this request because the current run is ...` replies after the intended handoff chain had already succeeded.
- Correction: Narrow stream follow-up processing after delegation so only the intended recipient or an explicitly waiting owner consumes the follow-up message, and suppress user-visible terminal-state error replies for project-topic messages that arrive after a stream run is already complete.
- Mistake: Stream follow-up eligibility depended on generic `active_run` state, which let unrelated bots in the same project topic consume delegated follow-up messages and turn benign late events into failed run states.
- Correction: Use handoff expectation state (`expected_next_actor`) as the project-topic follow-up gate, and treat unmentioned late stream messages on terminal runs as ignorable rather than user-visible failures.
- Mistake: The stronger Fibonacci workflow test showed that one Neo escalation and one Smith handoff could still create duplicate queued work for the same project-topic run, which reopened AgentSmith after task 1 and left Niaobe with overlapping verification handoffs instead of one clean sequential task chain.
- Correction: Intake and delegation need idempotency by `(bot, run_id, source_message_id)` or equivalent handoff/message key so the runtime does not enqueue multiple actionable jobs for the same project-topic event, especially when a visible stream post and a synthetic delegation target the same recipient/run.
- Mistake: After the stronger SDD prompt expansion, long Neo planning turns started failing because Ollama sometimes returned malformed JSON and the runtime treated that as a hard worker failure.
- Correction: Structured-response parsing must tolerate malformed JSON by extracting a likely JSON candidate and attempting one repair pass before failing the run.
- Mistake: Even after queue dedupe, a delegated stream message could still be processed twice because the delegation path enqueued a synthetic recipient job while normal intake also enqueued the same visible stream message as a fresh turn, and Neo could emit a second Smith escalation while the first one was still pending.
- Correction: Skip normal intake when the message is already the visible message of a pending handoff for that recipient, and suppress same-route duplicate delegations while an equivalent pending handoff is still unresolved.
- Mistake: `StateStore.save()` still uses a plain temp-file replace sequence without guarding against concurrent writers, which allowed the live runner to crash with `FileNotFoundError` on `intake_state.json.tmp` during the final observation run.
- Correction: Intake-state persistence needs a concurrency-safe write path or locking so concurrent save calls cannot remove each other's temp file and crash the runner.
- Mistake: The final stronger-SDD live run showed that the agent prompts can still produce task files that do not fully satisfy the stricter task-file contract even while the project visibly progresses.
- Correction: The runtime needs a stricter enforcement path for task-file shape and current-task path normalization, not just stronger prompt guidance.
- Mistake: In the first live smoke test on the new policy-driven authority model, Neo emitted the correct `start_execution` authority, but AgentSmith still generated only a partial execution takeover and failed to create `CURRENT_TASK.md` before the runtime gate evaluated the package.
- Correction: The authority model is working; the next fix belongs in Smith prompt/output quality so he creates a complete execution package under `start_execution`, not in weakening the runtime readiness check.
- Mistake: The follow-up live smoke run after tightening Smith's prompt did not actually exercise the new packaging behavior because Neo's initial turn timed out at the Ollama layer before reaching the Smith handoff.
- Correction: Treat this as an infrastructure/runtime latency failure, not evidence about Smith behavior. The next live validation should either use a smaller Neo initialization ask or a higher Ollama timeout so the run can reach the Smith phase.
- Mistake: A reduced live smoke request later reached Smith more quickly, but because the request was too minimal, Neo omitted a required base planning artifact (`management/DECISIONS.md`), and Smith was blocked by the readiness gate before the new review-result flow could be exercised.
- Correction: Reduced smoke tests still need to preserve the full required initialization artifact contract, or Neo must be given a stronger minimum-init instruction before the live run can validate later execution and review stages.
- Review-path validation mismatch:
  In the current sequential-task flow, AgentSmith can correctly mark the active task `done` and clear `CURRENT_TASK.md` / `PROJECT_STATE.md` during `review_result`, but the runtime still applies the one-active-task execution validator afterward and blocks the review turn.
  Review/closure validation must allow either zero active tasks when Smith is closing or completing the project, or exactly one active task only when Smith is preparing the next execution handoff.
- Premature review-result generation:
  In the multi-task sequential flow, the runtime can generate a `review_result` handoff for the manager from an executor acceptance note instead of waiting for a true completion/blocker result.
  This lets the manager promote the next task too early even though the executor only acknowledged the task and had not yet reported the real `DONE` payload.
- Executor/report consistency gap after successful sequential smoke:
  In `protocol_multitask_20260424_131457`, the new terminal-status protocol allowed a clean three-task progression and project closure, but the final artifacts still showed an executor-side mismatch: `T002` and the reports claimed `verify_fib.py` existed even though the file was missing from the project folder.
  Completion for executor-owned tasks still needs stronger executor-side output/report consistency before a `completed` result is emitted.
- Handoff history retention gap in repeated task execution:
  The same successful three-task smoke persisted distinct `review_result` records for T001/T002/T003, but the project-local handoff history retained only T001 and T003 `task_execution` records instead of a complete per-task execution trail.
  Multi-task handoff persistence likely still keys `task_execution` records too coarsely for repeated same-project execution cycles and should preserve one distinct execution record per task instance.
- Missing visible executor mirror in repeated same-topic task execution:
  In `protocol_multitask_20260424_131457`, T002 completion was visible to AgentSmith through the structured handoff/review path, but no Niaobe stream message appeared in Zulip for T002 even though T001 and T003 were mirrored visibly.
  This is not a Zulip delivery failure. It appears when repeated same-topic task executions reuse stream-scoped runtime state too coarsely: the executor result can advance the structured handoff path without forcing a visible mirror, and the persisted handoff records show stale-field overwrites across T002/T003.
  The runtime should ensure each `task_execution` cycle has its own stable persisted record and should auto-mirror terminal executor events into the project topic when the model does not emit a visible reply itself.
- Incomplete handoff identity propagation:
  The follow-up identity-contract smoke runs (`protocol_identity_20260424_154023` and `protocol_identity_20260427_0916`) still show review/progression records bound to the wrong execution attempt: later task completion notes can be persisted under `work_id=task:T001` and the original T001 attempt while T002/T003 executor handoff records stay non-terminal.
  `work_id` and `attempt_id` must be first-class fields in the delegation schema, queue payload, prompt context, response map, and event history. The runtime should stop deriving task identity from visible message prose and should not use "latest active" lookup as a substitute for explicit lineage.
- Event visibility overload and stale terminal-handoff mutation:
  In `event_protocol_20260427_115214`, event mirroring made the workflow observable but too noisy: duplicate handoff prose plus event messages appeared in Zulip, `delivered` and internal `review_result` states cluttered the project topic, and non-terminal `start_execution` / `review_result` records later emitted false `STALLED` events.
  A stale autonomous Niaobe continuation also ran under an already-completed T002 `task_execution` handoff and overwrote it to `rejected` after seeing manager-owned T003 closure. The runtime must ignore jobs for terminal handoffs, make runtime-created review handoffs terminal when the manager acts, prevent agent-created `review_result` delegations from duplicating runtime review flow, and use a compact Zulip visibility policy while keeping the full JSONL ledger.
- Workflow-contract live-smoke gap:
  In `contract_flow_20260428_1508`, the deterministic contract path worked through T001, including action lineage, workflow versioning, and accepted-task continuation, but AgentSmith cleared `PROJECT_STATE.md` and `CURRENT_TASK.md` to active task `none` before delegating T002.
  Correction: keep the runtime readiness gate strict and improve Smith's task-promotion contract so next-task promotion is atomic across `PROJECT_STATE.md`, `CURRENT_TASK.md`, `BACKLOG.md`, and the task file before any `task_execution` handoff.
- Review-result failure-status bug:
  During the same live smoke, a `review_result` turn that failed while attempting the next delegation was previously recorded as `completed` with an error summary.
  Correction: runtime exception handlers for readiness, tasking, write-policy, and invalid-write failures now force the active handoff event status to `failed` with a structured reason code.
- Recovery invalid-write gap:
  The manual Smith recovery attempt for `contract_flow_20260428_1508` failed because the model produced an invalid write path outside allowed roots.
  Correction: keep the write guard strict, but improve future diagnostics and Smith workflow guidance so recovery turns do not generate ambiguous or truncated invalid-path failures.
- Handoff idempotency and sender-continuation gap:
  In `contract_review_modes_20260428_1641`, Neo emitted a `start_execution` handoff, then continued autonomously and emitted a second `start_execution` handoff for the same project.
  Because the runtime trusted agent-provided/inferred work IDs and only skipped duplicates with matching work IDs, both handoffs executed; Smith then delegated T001 twice and the runtime had to cancel the older Niaobe attempt.
  Correction: runtime must own canonical action/work identity and must normally force a sender to wait after creating a handoff unless the workflow contract explicitly allows sender continuation.
- Runtime-failure terminalization gap:
  In the same live smoke, AgentSmith's `review_result` turn failed after a long malformed-JSON/repair failure, but the corresponding `review_result` handoff remained stuck at `delivered`.
  Correction: any runtime/model/schema failure while processing an active handoff must produce a terminal `failed` handoff event with a structured runtime reason instead of leaving the communication action non-terminal.
- Prompt-tightening limitation:
  Adding more prompt rules and workflow Markdown did not make the handoff protocol deterministic; it increased model burden while leaving core invariants unenforced.
  Correction: prompts should explain intent and decision boundaries, while runtime must enforce idempotency, sender turn closure, canonical identity, and terminal failure reporting.
- Pre-delivery handoff creation regression:
  The first live smoke after adding canonical action-first handoff creation failed because `_apply_delegations` still passed `visible_message_id` before Zulip delivery had assigned it.
  Correction: create the canonical action with `visible_message_id=0`, then update action visibility after the Zulip handoff message is successfully posted.
- Project event projection ordering bug:
  The `deterministic_smoke_20260429_1319` event ledger showed cross-action events grouped by per-action `sequence`, which made the project-local JSONL order misleading even though Zulip message order was correct.
  Correction: project-local `events.jsonl` must preserve append order across actions and update existing event lines in place; per-action sequence is not a global ordering key.
- Accepted-continuation executor behavior gap:
  The deterministic continuation correctly caught Niaobe returning `event_status=accepted` a second time, but the smoke stopped at T001 because the executor prompt/behavior did not understand that the runtime-owned continuation requires work to continue toward terminal `completed`, `failed`, or `rejected`.
  Correction: keep the runtime failure strict, but improve executor guidance or add a more explicit continuation prompt/context so the executor does not treat runtime continuation as a new acceptance opportunity.
- Executor non-terminal loop gap:
  In `manager_status_smoke_20260429_1514`, the runtime successfully allowed agent-authored Zulip status messages and Smith posted status before the next handoff, but Niaobe accepted T002 and then consumed the run-loop budget with file writes/continuations without returning terminal `completed`, `failed`, or `rejected`.
  The queue became idle while the T002 `task_execution` handoff remained `accepted`.
  Correction: the executor/runtime contract still needs a deterministic terminal-outcome requirement when run-loop budget is exhausted for an accepted task execution, preferably by feeding back "return terminal status now or explicitly fail/escalate" before leaving the handoff non-terminal.
- Archived-project queue contamination:
  During the Oracle/subteam smoke, older archived smoke projects (`executor_subteam_smoke_20260430_1731` and `executor_subteam_smoke_20260430_1806`) still generated queue jobs after the clean smoke closed.
  Correction: before live smoke runs, old incomplete projects should be terminalized or their queue jobs moved to manual hold; the runtime should eventually avoid recreating work from archived project topics.
- Manager terminal-state consistency gap:
  In `executor_subteam_smoke_20260430_1838`, AgentSmith closed the project in the handoff event and updated most lifecycle files, but left `RESULT.md` saying Smith closure was pending and kept `PROJECT_STATE.md` as `Status: ACTIVE` while `Stage: completed`.
  Correction: Smith's prompt now requires project closure to set `PROJECT_STATE.md` to `Status: CLOSED`, `Stage: completed`, `Active Task ID: none`, `Next Step: none`, and to remove Smith closure from `RESULT.md` pending work.
- Bare project-name DM context bug:
  Neo failed to answer a human DM asking for files in `image_enhancement` because the runtime did not treat a known bare project slug as project context, reused stale `executor_subteam_smoke` DM run state, and then rejected the agent's redundant `project_slug` tool argument.
  Correction: project resolution now matches existing project slugs without requiring the `project:` prefix, private conversations are keyed by the resolved project, and project path tools accept a matching `project_slug` while rejecting mismatches.
- Markdown-only project context bug:
  After project routing was fixed, Neo still answered a file-list question incorrectly because resolved project context only included selected Markdown management files and hid code/config files unless the model chose a tool.
  Correction: resolved project context now includes a bounded file inventory excluding runtime/internal folders, and direct reply history is stored under the same resolved project-scoped DM key as the request.
- Project context versus workflow ownership bug:
  Bare project references in human DMs made Neo use project-local workflow run state even when the human only asked a read-only advisory question.
  Correction: human DMs now classify as `chat`, `project_advisory`, or `workflow`; advisory turns may use project context but keep workflow `project_slug` empty, stay in generic DM scope, use read-only tools only, and block writes/delegations/project-visible messages unless workflow authorization is explicit.
- Over-classified human request bug:
  The chat/project_advisory/workflow split over-corrected the previous issue by making runtime labels decide whether Neo or Smith could write planning/report artifacts or use full project tools.
  Correction: runtime no longer treats the human request label as authorization semantics; concrete payloads are validated directly, original reply surface is preserved through continuations, and planning/report writes are allowed when role/path policy permits them.
- Malformed model output smoke failure:
  The first Fibonacci smoke failed silently after Neo's first LLM turn returned empty or unrecoverable malformed JSON; the worker marked the run failed without a visible conversation response.
  Correction: empty model output now bypasses wasteful JSON repair, malformed structured output becomes a visible failed turn with no side effects applied, and Neo/Smith guidance asks large artifact work to be chunked across continuations.
- Manager review-result visibility gap:
  The successful Fibonacci smoke closed project files but initially lacked a final visible Smith closure summary because direct replies were suppressed for every active handoff terminal event.
  Correction: direct replies remain suppressed for executor task terminal events, but manager `review_result` summaries are allowed so Smith can visibly report review/closure status.
- Control-plane anchor bug:
  The `.current_project.json` approach let agents write control-plane state for themselves and other agents, which caused malformed paths (`/projects/D/...`), conflicting truth sources, and stalled handoffs.
  Correction: remove writable agent anchor files, move handoff identity to `project_id`, and treat registry lookup plus validated envelopes as the project-resolution path.
- Writable-subagent contract bug:
  Morpheus subagents were instructed to write project files and tests even though spawned leaf sessions did not reliably expose the necessary write tools, causing planner failure before `TASKS.md` existed.
  Correction: BUILD ownership stays in the main Morpheus session; spawned subagents are advisory only unless runtime-grounded writable spawn support is added later.
