---
name: api-interface-design
description: Design or change contracts across independently evolving components or consumers. Use for public or cross-boundary APIs, commands, events, protocols, file formats, configuration contracts, and integration interfaces; not for private function signatures changed atomically with all callers.
---

# API and Interface Design

## Purpose

Define predictable contracts whose success, failure, compatibility, retries, and
uncertain outcomes can be implemented and operated safely.

## Trigger

Use when producers and consumers can deploy, fail, retry, or evolve independently,
or when an interface is externally documented or persisted.

## Inputs

- Consumer goals, trust boundary, and compatibility commitments
- Existing contract, implementations, call sites, tests, and versioning policy
- Delivery, retry, concurrency, ordering, and partial-failure semantics

## Workflow

1. Inspect actual consumers and existing conventions before defining the contract.
2. Specify operations, inputs, outputs, validation, defaults, limits, ordering,
   identity, and side effects independently of implementation detail.
3. Define a stable error model: categories, machine-readable identity, actionable
   context, retryability, and safe user-facing detail. Keep sensitive internals out.
4. State compatibility rules for omitted, added, unknown, and changed fields or
   operations. Prefer additive evolution; use `migration-deprecation` for staged
   replacement or removal.
5. Define idempotency at the semantic operation boundary where retries can repeat
   side effects. Specify key scope, deduplication lifetime, conflict behavior, and
   response consistency when applicable.
6. Model unknown outcomes explicitly: timeout or disconnect may leave success
   unconfirmed. Provide safe retry, status lookup, reconciliation, or a clear
   non-retryable contract rather than equating transport failure with no effect.
7. Address authorization, resource limits, pagination or streaming, cancellation,
   concurrency, and observability only where the interface requires them.
8. Add contract and consumer-focused tests for success, errors, duplicates,
   compatibility, and partial or unknown outcomes.

## Expected Output

An implementation-ready contract with explicit behavior, errors, compatibility,
idempotency or retry semantics, and verification evidence.

## Validation

- Consumers can distinguish success, known failure, retryable failure, and unknown
  outcome without parsing prose.
- Retry and duplicate behavior cannot silently repeat unsafe side effects.
- Compatibility claims are exercised against representative producers and consumers.

## Cautions

- Do not expose storage layout or incidental implementation details as contract.
- Do not use one generic success or error shape when consumers need distinct action.
- Do not promise exactly-once effects without a mechanism and bounded assumptions.

## Related Guidance

- `.agents/skills/migration-deprecation/SKILL.md`
- `.agents/skills/planning-design/SKILL.md`
- `.agents/skills/security-threat-modeling/SKILL.md`
- `.agents/skills/testing/SKILL.md`
