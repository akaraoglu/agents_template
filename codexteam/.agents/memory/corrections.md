# Corrections Memory

## Entries

- Do not infer current functionality from obsolete archives or old application-oriented documents.
- Do not create cold-start projects outside the approved repository project area; from the guaranteed base folder the default root is `./projects`.
- Do not accept lowercase task IDs inside persisted contracts.
- Do not accept a result with only `task_id`, `status`, and `summary`; enforce result contract v1 completely.
- Do not mark tasks complete from worker output alone.
- Do not use `eval`, shell pipelines, or compound shell strings for verification.
- Do not update a missing or malformed task row and report success.
- For commands shaped as `project [leader options] -- verification command`, split the explicit `--` before parsing leader options; an `argparse.REMAINDER` positional can consume valid options that follow `project`.
- Do not put Markdown backticks or `$()`-like text inside a double-quoted inline worker prompt; use `--prompt-file` so the shell cannot execute or alter it.
- Do not start a new attempt for a malformed final result or a turn with no final message when an exact thread ID exists; send contract or recovery feedback through the same session.
- Do not assume default review/documentation routing is always sufficient. After repeated focused failures, record an intentional capability transfer and keep the abandoned attempt result-free.
- Do not accept generic audit prose as evidence. Require expectation-bearing result validation, declared-artifact inspection, exact session facts, and temporal readiness versus delivery distinctions.
- Do not let workers create scratch files, one-off Python document writers, or patch experiments outside their handoff. Inspect the full root after failed editing turns and remove attributed artifacts before delivery.
- Do not let draft evidence occupy `results/<TASK>-<attempt>.json` or `results/<TASK>-verification.txt`; those paths belong to launcher finalization and leader closure. Resume the same session with corrective feedback when this happens.
- Do not update only `TASKS.md` when assigning a task; synchronize the matching `CURRENT_TASK.md` status before the independent reviewer sees it.
- Do not rely on a generic finalization request for result-v1 details. State the allowed file actions and evidence types, require project-relative artifact references, and require a UTC `Z` timestamp.
- Do not append an exact optional filename to an array while relying on `nullglob`; an unmatched literal remains present and can falsely report a nonexistent helper. Use a wildcard pattern for optional helper families and cover the empty match in the runner tests.
- Do not finalize a session merely because its result JSON is schema-valid. Before persistence, verify that declared created and modified paths plus evidence artifact references exist, that deleted paths are absent, and leave failures resumable as `correction_needed` in the same thread.
- Do not give only evidence enums in a final prompt. Include one complete task-specific evidence object with `type`, `artifact_ref`, `summary`, and optional metadata so communication errors are corrected before result persistence.
- Do not assume repository-local `.agents/skills/*.md` files automatically establish a fresh root agent's role. Put the Project Lead identity and phase router in automatically discovered `AGENTS.md`, with exact links to detailed guidance.
- Do not document commands as if Codex starts in the parent `agent_template` directory. From the guaranteed `codexteam` base, use `./scripts/`, `./.agents/scripts/`, `./projects`, and `../env-python` only for toolkit test execution.
- Do not make a cold-start agent list or recursively search `.agents/`. The first proposal uses the compact root bootstrap; detailed guidance loads only when the corresponding phase begins.
- Do not run bare repository-root `pytest` after generated projects exist beneath `./projects`; target the toolkit suite explicitly with `../env-python/bin/python -m pytest -q tests`.
- Do not interpret schema-valid results or canonical `DELIVERED` state as product acceptance. Exercise at least one nontrivial exact output, inspect the delivered manifest, and preserve a failed E2E verdict when either check fails.
- Do not accept evidence by filename. Compare every Reviewer claim with the content of the named artifact; a unit-test log cannot prove extra manual determinism, rendering, range, or stderr checks it does not record.
- Do not create a chain of similar `/tmp` feedback filenames. Use one stable ignored prompt path such as `<project>/.codexteam/lead-prompt-T002-att-001.md`.
- Do not use CLI redirection to leave `run1.txt`, `run2.txt`, or exploratory scripts in a project. Capture repeated outputs in the test framework and audit the final manifest.
- Do not print entire final results or JSONL after concise validation succeeds. Inspect decision fields with `jq` and open only the named artifacts needed for the acceptance decision.
- Do not assume `--trust-parent-sandbox` restores access to host Ollama. Preflight the endpoint from the same execution surface; when parent loopback is isolated, launch at the approved host level without the flag and keep that route stable across draft, feedback, and final. A dry run and a global empty MCP list do not prove worker connectivity or attempt-private configuration.
- Do not assume every worker uses only the same project `AGENTS.md`, or that it receives no durable role instructions. Common project rules and one selected role policy are separate layers, and the exact role policy is pinned for the attempt.
- Do not infer live worker state from a missing final result or global Codex history. Read the selected project's `turn-state.json` through `subagent-status.py`, treat old running observations as stale rather than active, and inspect the matching attempt before recovery.
- Do not treat Developer unit/algorithm and smoke checks as integration acceptance. Require the configured Integration Gate, which includes the Development Gate before broader CI-equivalent checks.
- Do not weaken a Test Engineer assertion, fixture expectation, or golden value merely to make current implementation output pass. Require approved requirement/decision or confirmed test-defect justification and Reviewer inspection of the test diff.
- Do not finalize a Developer while a Test Engineer product defect for the same deliverable remains unresolved. Return it to the same Developer session and rerun both gates after correction.
- Do not let an Architect implement source, change tests, or approve its own design. Accept architecture through the Project Lead and audit conformance through the Reviewer.
- Do not treat role-policy pinning alone as attempt stability. Snapshot and verify every selected skill file so feedback and final turns cannot drift after guidance changes.
- Do not execute gate configuration as shell text or trust a stale gate record. Use structured argument arrays from `management/TEST_GATES.toml` and compare the current verification-path digest.
- Do not initialize a project inside a parent repository and let Git commands fall back to that parent. New projects are exact standalone roots unless `--no-git` is an intentional exception; Git Steward refuses a non-exact root.
- Do not run Git Steward after every model turn, use `git add .` or `git add -A`, include unrelated/runtime/secret-like files, or commit with pre-existing staged changes.
- Do not fabricate Git identity, bypass active hooks silently, amend or rewrite history, or perform push, merge, tag, release, publication, or remote PR actions through Local Git Steward.
- Do not treat a preview as permission to mutate. Git authorization and commit commands require explicit `--apply`, and preview must not create Git objects, advance HEAD, or alter the index.
- Do not trust integration evidence created before the approved commit path set. The deterministic executor re-runs the Integration Gate against the isolated candidate tree before committing code milestones.
- Do not rely on a Stop-only pending transition when one Lead turn can close several
  tasks. Checkpoint the exact rollout at each transition; otherwise later tasks are
  silently charged to the first task and the next task has no usable baseline.
- Do not call a milestone repository fully closed when the milestone commit contains an
  active Git Steward task and final delivery files remain modified afterward. Commit
  the narrowly scoped closure metadata separately.
- Do not equate named filenames with bounded context. When a worker would still read
  several complete upstream artifacts, scan the repository, or print a large dirty
  status, route the question through one bounded `codexteam-context` call. Skip MCP
  only for sufficient exact headings, symbols, short ranges, or a smaller
  authoritative command, and never duplicate a sufficient response with broad shell
  discovery.
- Do not make a worker search the project or personal memory for role skills already
  injected and pinned in its attempt guidance bundle.
- Do not cache local-document index provenance across an atomic index replacement.
  Read the digest and requested content through the same read-only SQLite connection
  so a live MCP process cannot attribute new documents to an old index.
- Do not make a worker guess `codexteam-context` project identity from a workspace path
  or pass an absolute path as `project`. The launcher owns the binding and bound worker
  schemas omit the argument; a failed guessed call must not trigger broad rediscovery.
- Do not pair precise Context Targets with a conflicting instruction to read several
  whole milestone artifacts. State accepted facts in Context and give exact source,
  test, and evidence locators with their intended use.
- Do not expose capsule checkpoint instructions to every Developer. T195 was a Planned
  Lane task but returned `CAPSULE CHECKPOINT`, showing that two conditional protocols
  in the default bundle were ambiguous. Inject the capsule playbook only for its pilot.
- Do not rely on only the outer Integration Gate timeout for live browser subprocesses.
  Close protocol handles in `finally`, give each named smoke an inner deadline, bound
  child-process waits, and keep a negative timeout and port-release canary.
