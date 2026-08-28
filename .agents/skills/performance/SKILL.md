---
name: performance
description: Diagnose or improve measured resource performance with controlled experiments. Use for explicit latency, throughput, memory, CPU, I/O, startup, size, or scalability goals and suspected regressions; not for speculative micro-optimization.
---

# Performance

## Purpose

Make performance changes from reproducible evidence and retain only improvements
that matter under representative conditions.

## Trigger

Use when there is a stated performance objective, measured regression, or
evidence that a resource constraint materially affects users or operations.

## Inputs

- Metric, workload, target, and affected environment
- Current implementation and suspected limiting resource
- Repository-native benchmark, profiler, or representative test path

## Workflow

1. Define the metric, workload, success threshold, and constraints before editing.
2. Capture a baseline after warmup under controlled, representative conditions;
   record versions, configuration, data shape, and resource limits.
3. Repeat measurements enough to expose run-to-run variance. Compare
   distributions or robust summaries, not a single best result.
4. Profile or instrument to identify the limiting path and form one testable
   hypothesis.
5. Change one material factor at a time and rerun baseline and candidate under
   the same conditions, interleaving runs when drift may matter.
6. Check correctness and tradeoffs in memory, CPU, I/O, startup, size,
   concurrency, and tail behavior as applicable.
7. Keep changes with a meaningful, repeatable benefit. Revert neutral, noisy, or
   regressive experimental changes rather than rationalizing them into the patch.
8. Report method, raw or summarized evidence, variance, limitations, and result.

## Expected Output

A measured improvement or evidence-backed diagnosis, with reproducible conditions
and no neutral experimental residue.

## Validation

- Baseline and candidate use the same workload and controlled conditions.
- Results exceed normal variance and preserve behavior under relevant tests.
- The final diff contains only changes justified by measured benefit or diagnosis.

## Cautions

- Do not infer end-to-end benefit from an unrepresentative microbenchmark.
- Do not hide warmup, outliers, variance, failed runs, or environmental limits.
- Do not trade away correctness, safety, or maintainability without explicit
  requirements and evidence.

## Related Guidance

- `.agents/skills/debugging/SKILL.md`
- `.agents/skills/testing/SKILL.md`
- `.agents/skills/verification/SKILL.md`
- `.agents/skills/code-review/SKILL.md`
