---
name: observability
description: Design or review structured telemetry for an operational question. Use when adding or changing logs, metrics, traces, alerts, correlation, or diagnostic signals; do not invoke merely because production code is being edited.
---

# Observability

## Purpose

Produce minimal, structured telemetry that answers defined operational questions
without uncontrolled cost, cardinality, or sensitive-data exposure.

## Trigger

Use when the task changes telemetry or when a material runtime failure cannot be
detected, diagnosed, or distinguished with existing signals.

## Inputs

- Operational question, users of the signal, and required response
- Existing telemetry conventions, data policy, and retention or cost constraints
- Relevant request, job, dependency, and failure boundaries

## Workflow

1. Phrase each need as a question and decision, such as detecting failure,
   locating a bottleneck, or distinguishing outcomes.
2. Inspect existing signals and reuse established names, context propagation,
   severity, dimensions, and ownership.
3. Select the least telemetry that answers the question: structured event,
   bounded metric, trace relationship, or alert derived from a durable signal.
4. Define field semantics and stable units. Use correlation identifiers where
   useful, but keep secrets and sensitive payloads out of telemetry.
5. Bound metric dimensions and indexed fields to known finite sets. Put unbounded
   identifiers in controlled diagnostic context, not metric labels.
6. Define expected success, failure, cancellation, retry, and partial or unknown
   outcomes; avoid duplicate counting across retries or layers.
7. Validate emitted shape and volume, then document the question, owner, and
   interpretation when the repository has an operational documentation pattern.

## Expected Output

Question-linked structured telemetry with explicit semantics, bounded
cardinality, privacy controls, and practical validation.

## Validation

- A consumer can answer the stated question from the signal.
- Field values, labels, and dimensions have bounded or intentionally controlled
  cardinality and acceptable volume.
- Tests or local inspection cover key outcomes without relying on production data.

## Cautions

- Do not log entire requests, responses, tokens, or sensitive identifiers for
  convenience.
- Do not add a dashboard or alert without a defined decision and accountable
  response.
- Do not use free-form message text as the only machine-consumed contract.

## Related Guidance

- `.agents/skills/planning-design/SKILL.md`
- `.agents/skills/implementation/SKILL.md`
- `.agents/skills/verification/SKILL.md`
- `.agents/capabilities/coding-standards.md`
