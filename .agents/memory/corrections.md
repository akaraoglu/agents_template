# Corrections Log

Append one-off lessons here when a mistake is discovered, the agent is corrected, or guidance becomes outdated.

## Entry Template
- Date:
- Problem:
- Root cause:
- New rule:
- Where it was recorded:

## Entries

- Date: 2026-04-16
- Problem: The runtime package had drifted into a broken state where `openclaw_agents/agents/__init__.py` imported `.manager`, but the source file was missing from the working tree and only stale bytecode kept earlier runs half-working.
- Root cause: The repo ended up with pycache-backed imports masking the absence of the real runtime source module.
- New rule: Keep `openclaw_agents/agents/manager.py` present as the authoritative source; do not rely on `__pycache__` artifacts to satisfy runtime imports during refactors.
- Where it was recorded: This corrections log and the restored `openclaw_agents/agents/manager.py`.

- Date: 2026-04-16
- Problem: A parallel `py_compile` + `pytest` run hit a transient import-collection failure while the new runtime manager file was being recreated.
- Root cause: I ran compile and test in parallel during an active file-creation window, so pytest briefly saw an incomplete module set.
- New rule: During active runtime file creation/refactors in this repo, serialize compile and test runs instead of running them in parallel.
- Where it was recorded: This corrections log; subsequent validation for Sprint 3-7 was run sequentially.

- Date: 2026-04-16
- Problem: Confirmation parsing incorrectly treated normal DM text containing "now" as a rejection due to substring matching on "no".
- Root cause: Confirmation intent detection used substring checks instead of word-level token matching.
- New rule: Parse approval intents using word tokens/boundaries only; never use raw substring checks for confirmation keywords.
- Where it was recorded: `openclaw_agents/communication/approval_helpers.py`.

- Date: 2026-04-16
- Problem: Initial bring-up exploration looked at deleted repo history and old `/zulip` bridge code before the user clarified that the new bridge must be a clean implementation.
- Root cause: I treated old code paths as implementation references instead of keeping the fresh-start boundary strict enough.
- New rule: For the fresh Zulip bridge, use only the current foundation specs and current `openclaw_agents` interfaces as implementation sources; do not derive code from legacy bridge folders or deleted repo history.
- Where it was recorded: This corrections log and the durable bridge decision in `.agents/memory/decisions.md`.

- Date: 2026-04-16
- Problem: After the boundary refactor, Neo still behaves like a project-centric bootstrap assistant rather than a real free-form agent.
- Root cause: The refactor moved behavior out of the gateway, but the replacement runtime agents in `openclaw_agents/agents/manager.py` still use heuristic placeholder logic instead of a prompt/tool-driven agent runtime.
- New rule: Do not claim Neo or AgentSmith are free agents until the runtime is model-backed and skills/services are invoked as capabilities rather than through hardcoded branches.
- Where it was recorded: This corrections log and the runtime refactor backlog under `openclaw_agents/plans/`.

- Date: 2026-04-16
- Problem: The first Sprint 2 test run failed during collection because the new runtime modules were partially inconsistent with older in-repo class names and interfaces.
- Root cause: The repo already contained in-flight module variants for prompt/model helpers, so the first cut mixed `ModelClient`/`ModelMapService` naming with older `BaseModelClient`/`ModelTarget` imports.
- New rule: When refactoring the runtime in this repo, normalize helper modules first and keep compatibility shims only where tests or injected fakes already depend on them.
- Where it was recorded: This corrections log and the final Sprint 2 runtime modules under `openclaw_agents/agents/`.
