# Cold-Start Team Canary — 2026-07-17

## Verdict

**Failed as a clean end-to-end acceptance run.** The lifecycle reached canonical `DELIVERED` state with five responsible-AI roles, but the independent audit found a product-format defect, unsupported review claims, scratch files, and disproportionate turn/token cost.

Project: `projects/fibonacci-tree-cli-lead-canary-20260717-110304`

## What Worked

- A fresh root session discovered the Project Lead role and preserved the proposal, initialization, planning, and execution gates.
- The exact initializer project path flowed through handoffs.
- T001 through T005 had named responsible AIs and persistent sessions.
- The nested-worker read-only and `bwrap` failures were diagnosed; a local worker with `--trust-parent-sandbox` completed inside the existing parent boundary.
- Ordinary corrections remained in the same task attempt, and final results passed contract validation before closure.

## What Failed

- The renderer uses `|   ` below a completed right branch where the approved convention requires spaces. The seven-test suite did not assert a nontrivial right subtree, so the defect survived delivery.
- The Reviewer said `results/T003-verification.txt` proved exact rendering, determinism, input range, and error handling. That artifact contains only the seven-test unittest run; the stronger observations were in a different tester note and were not independently checked by the Reviewer.
- `run1.txt`, `run2.txt`, and the incomplete exploratory `test_tree.py` remained in the delivered project.
- The lead mistyped one temporary feedback filename. Recovery was immediate, but the path-continuity rule did not cover lead-authored prompt files.
- Tester and Documenter finalization repeatedly missed result-v1 object keys or enum values despite focused feedback.
- Persisted sessions recorded 24 worker turns (including the preserved T002 sandbox diagnostic), and project execution ran for about 49 minutes from initialization to delivery. The clean-path target is 12 turns and 30 minutes.
- The root turn reported 25,636,272 input tokens (24,902,912 cached) and 92,344 output tokens. This is disproportionate for the product and exceeds the E2E performance target.

## Guidance Changes

- Lead prompts now use one stable ignored `.codexteam/lead-prompt-<task>-<attempt>.md` path rather than a series of similar `/tmp` filenames.
- Finalization presents complete `file_changes` and `evidence` object shapes, including valid key names and enums.
- Leads use concise `jq` inspection and avoid reopening full result/event output tails after validation.
- Tester guidance forbids persistent repeated-output scratch files and prefers capture-capable tests for determinism.
- Reviewer guidance requires claim-by-claim comparison with artifact contents; artifact existence and schema validity are not evidence of unrecorded checks.
- Delivery requires an acceptance-level exact-output check and final manifest audit.
- E2E-006 now reports lifecycle, product, evidence-integrity, and performance results separately.

## Model Observation

`gpt54-mini` was effective as the root Project Lead but overly verbose in this run. `gemma4-26b` could execute local worker tasks after the sandbox correction, but its result-contract accuracy and editing behavior required repeated feedback. The canary does not justify making Gemma the default evidence-producing worker. A cloud root with compact phase-boundary communication plus a task-capable local nested worker remains the supported cold-start arrangement; host-level orchestration is preferred when authenticated cloud workers are required.
