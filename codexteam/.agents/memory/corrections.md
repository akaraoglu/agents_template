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
