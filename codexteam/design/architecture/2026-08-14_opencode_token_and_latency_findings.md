# OpenCode Token and Latency Findings

## Status

Architecture research note derived from the matched Muse Glimmer scheduler
benchmarks and preserved runtime artifacts. No benchmark was rerun for this
document.

## Matched Results

All compared implementations passed the same 26 hidden scheduler cases.

| Metric | Direct OpenCode | Governed launcher | Compact comparison run |
|---|---:|---:|---:|
| Hidden correctness | 26/26 | 26/26 | 26/26 |
| Input tokens | 111,971 | 421,018 | 155,071 |
| Output tokens | 5,236 | 13,283 | 13,234 |
| Model steps | 13 | 22 | 11 |
| Tool calls | 12 | 22 | 11 |
| Wall time | 85.6 s | 222.2 s | 208.6 s |
| Scope clean | No, cache | No, scratch JSON | Yes |

The raw run used a different cache condition, so wall-time comparisons are
directional. Token and tool-count differences still identify concrete current
overhead.

## Primary current Overhead Causes

### Full guidance reads

The current OpenCode prompt tells the worker to read the pinned implementation and
development-testing guidance. Muse immediately read both files. They contributed
about 10.5 KB of early persistent context, including planned-lane, MCP, browser,
and gate material irrelevant to the simple empty-workspace task.

Because OpenCode reprocessed growing uncached history across later model steps,
the cost was much larger than the files' initial size.

### Private runtime exposed as product context

The launcher creates `.codexteam` inside the workspace before the worker starts.
Muse interpreted the logically empty workspace as nonempty and recursively
globbed it. That glob returned about 22 KB of runtime paths, followed by more
directory and management searches.

The prompt should state that `.codexteam/**` is launcher-private and excluded
from product discovery. A bounded product-baseline summary should replace broad
initial discovery.

### Todo tool churn

The current run made six `todowrite` calls. They added six complete model/tool cycles
without contributing product or acceptance evidence. current OpenCode permissions
currently allow them through a wildcard. The compact comparison demonstrated
that `todowrite` can be explicitly denied.

### Gate discovery ambiguity

The generic Developer policy required the configured Development Gate, but the
ad hoc benchmark workspace had none. Muse searched for management files before
falling back to direct tests.

The launcher must explicitly state one of:

- Configured worker gate and exact command.
- Configured host gate that the worker must not run.
- Intentionally absent gate with a handoff-provided fallback.

The model should not discover gate configuration through broad scans.

### Missing task-specific write scope

After an external `/tmp` smoke-file write was denied, Muse created
`test_input.json` in the product root. The broad Developer role allowed it even
though the task requested only three outputs.

Post-turn auditing must intersect role policy with machine-readable handoff
scope. Smoke inputs should use stdin or an approved temporary surface.

## Minimal Performance Changes

### P0: Compact OpenCode execution capsule

Keep guidance pinned for audit and continuation, but do not require full reads
for ordinary tasks. Put only applicable rules into the initial prompt:

- Work only in task scope.
- Read named context targets only.
- Make the smallest complete change.
- Run the routed gate or named fallback.
- Create no scratch or cache files.
- Return the pinned draft contract.

Load complete guidance only for explicit special workflows such as planned lane,
browser work, or unresolved context.

### P0: Deny unnecessary tools and declare baseline

- Deny `todowrite`.
- Mark `.codexteam/**` as private runtime.
- Supply product file count and exact context targets.
- State when the product baseline is empty.
- Preserve one focused expansion when concrete missing context is found.

### P1: Enforce handoff write scope

Compare changed paths against both role policy and task-specific output paths.
An extra root file should produce `correction_needed`, not become accepted work.

### P1: Compact feedback and finalization

Feedback should carry only:

- Failed criterion.
- Exact observation.
- Required correction.
- Accepted work to preserve.

Finalization should use identity, accepted checkpoint, audited file manifest,
and accepted evidence rather than repeat the full handoff and guidance.

## Reasoning Support Findings

current rejects `--reasoning-effort` for OpenCode, but generic session serialization
can still record the role's default `medium`. The preserved current scheduler session
therefore claims an effort that was not applied.

Use separate fields:

```text
requested_reasoning
effective_reasoning_or_variant
support_status = applied | provider_default | unsupported
provider_options
```

Rules:

- Codex retains current reasoning support.
- OpenCode maps only verified model-specific variants or provider options.
- Muse/Ollama currently reports `provider_default`, not fake `medium`.
- Explicit unsupported overrides fail clearly.
- Unsupported role defaults remain compatible but are reported as not applied.
- Requested and effective values are pinned across the attempt.
- Do not assume `low`, `medium`, and `high` mean the same thing across providers.

## Initial Promotion Gates

For the matched scheduler benchmark, require:

- Hidden correctness 26/26 in every run.
- Exactly the approved output files.
- No scratch, cache, or runtime artifacts in product scope.
- Median input tokens at most 220K initially.
- At most 16 model steps and 16 tool calls.
- Warm-model wall time at most 170 seconds.
- No output-token regression beyond the current 13.3K current baseline.
- Persistent draft/feedback/final lifecycle remains intact.

Stretch goals after scope enforcement:

- At most 180K input tokens.
- At most 14 steps and tools.
- At most 150 seconds warm-model wall time.

Use at least three alternating runs per condition with identical loaded/unloaded
model and clean runtime conditions.

## Historical Slugify Overhead Comparison

A 2026-08-13 matched run used OpenCode `1.18.16` and
`ollama/muse-glimmer:30b`. Both conditions began with the same underscore defect,
used one same-session Developer correction, and passed the final evaluator for
`Hello, World!` -> `hello-world\n`.

| Metric | Governed launcher | Compact comparison |
|---|---:|---:|
| Input tokens | 2,203,090 | 506,953 |
| Output tokens | 37,148 | 31,490 |
| Model steps | 130 | 71 |
| Tool calls | 164 | 63 |
| Failed tool calls | 7 | 3 |
| Model-turn time | 1,326.206 s | 525.760 s |

The governed run's Tester timed out twice and its Reviewer created `out.txt` and
`err.txt`; the final product still passed. These measurements support later
optimization work but preserve no discarded lifecycle or routing claim.

## Historical Qwen/Muse Scheduler Comparison

Three alternating fresh runs per model used the same scheduler prompt and 26-case
hidden evaluator. Every run passed. Median input tokens were `408,986` for Qwen
and `171,279` for Muse; median output tokens were `14,305` and `8,692`; median
duration was `232.81` s and `152.01` s. Muse reduced median input by `58.1%` and
duration by `34.7%` for this bounded implementation task. This did not establish
Reviewer superiority or a global default. Evidence remains under
`/tmp/opencode/qwen-muse-scheduler-20260811/`.

## Conclusion

The speed problem does not require replacing the current lifecycle. Most of the 309K-token gap over
direct OpenCode came from avoidable guidance reads, runtime discovery, todo
cycles, gate ambiguity, and broad scope. A compact execution capsule and tool
policy can preserve current governance while approaching direct OpenCode behavior.
