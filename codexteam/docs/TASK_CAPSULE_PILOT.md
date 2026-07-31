# Task Capsule Pilot

## Decision

Task capsules remain an opt-in experiment for medium Developer tasks. The
two-task read-only pilot justifies a live-task pilot, but not a source-context
MCP, universal capsule generation, or reduced Integration Gate coverage.

## Contract

A capsule is a 2–4 KB, human-readable starting map attached to a canonical
handoff. It contains:

- Repository path, HEAD, and hashes for named source/test files
- Behavior, non-goals, and stop conditions
- Exact symbols or line anchors and dependency direction
- Related tests with reasons
- Verification commands that have not yet run
- Uncertainties and one focused expansion allowance

The worker verifies all hashes in one command. A stale hash, missing consumer,
or conflicting contract invalidates the affected capsule claim. The capsule is
not task authority, implementation evidence, or a substitute for repository
inspection when a concrete gap appears.

For a live pilot, the Lead:

1. Creates the canonical task ID and binds Lead metrics to it.
2. Uses at most three tool calls to prepare the capsule from accepted evidence
   and named files.
3. Writes `.codexteam/runtime/task-capsules/Txxx.md`.
4. Adds `TASK CAPSULE PILOT`, the exact capsule path, and capsule SHA-256 to the
   canonical handoff before spawning the Developer.

The Developer verifies the capsule digest and all named source/test hashes.
Combined cost uses the existing project-local `lead-metrics.json` task entry
plus the Developer attempt's turn metrics; no additional metrics script or
schema is required.

The Lead tracker checkpoints the current rollout when the canonical task
changes, including multiple closures in one Lead turn. A missing Lead entry,
explicit binding reset, or entry spanning more than one task invalidates the
combined-cost comparison. Preserve the raw evidence and report the pilot as
inconclusive rather than substituting a zero or cumulative session total.

The pilot checkpoint triggers before 12 tool calls, after three failures,
before a second broad scan, or before a repeated command without relevant file
changes. It records known state, the unresolved gap, the next bounded action,
and the stop condition. It does not terminate healthy work or waive testing.

## Read-Only Replay

The 2026-07-30 pilot replayed dependency mapping for two completed Git GUI
Developer tasks using GPT-5.6 Luna. MCP servers were disabled, source files
were unchanged, task order was reversed, and all turns had identical read-only
and checkpoint constraints. Capsule sizes were 2,977 and 3,479 bytes.

| Metric | Baseline | Capsule | Change |
|---|---:|---:|---:|
| Tool calls | 18 | 13 | -28% |
| Failed calls | 0 | 0 | unchanged |
| Input tokens | 726,423 | 332,124 | -54% |
| Uncached input | 123,799 | 83,292 | -33% |
| Output tokens | 10,576 | 9,707 | -8% |
| Command-output bytes | 351,191 | 107,637 | -69% |
| Approximate wall time | 221.0 s | 207.1 s | -6% |

Both capsule maps retained the required behavior, implementation seams,
dependency boundaries, related tests, verification commands, uncertainties,
and stop conditions. One capsule surfaced an imprecise CSS line anchor and used
its allowed focused expansion rather than hiding the gap.

## Next Gate

Use capsules on two medium live Developer tasks only. Keep the normal planned
lane, same-session correction, Development Gate, Test Engineer Integration
Gate, and Reviewer flow. Continue only if live tasks show at least 25% fewer
Developer tool calls and at least 20% lower combined Lead-plus-Developer input
or tool work without more correction turns, missed dependencies, or integration
defects.

Do not build the proposed source-context MCP yet. The capsule-only result
already passed the tool-call threshold, while latency improved only modestly.
Implement source tools later only when live capsule gaps identify repeated,
specific queries that existing bounded inspection cannot answer efficiently.
