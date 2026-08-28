---
name: migration-deprecation
description: Plan or implement compatible data, schema, configuration, protocol, or feature retirement. Use when persisted or distributed state changes, consumers migrate over time, or an existing interface is deprecated or removed; not for atomic internal refactors.
---

# Migration and Deprecation

## Purpose

Move live consumers and state safely through compatibility windows, making
retirement depend on evidence rather than elapsed time alone.

## Trigger

Use when old and new producers, consumers, binaries, schemas, or persisted values
can coexist, or when removing behavior that may still be used.

## Inputs

- Current and target contracts, owners, consumers, and persisted state
- Compatibility policy, deployment topology, and observability evidence
- Data volume, availability requirements, and recovery constraints

## Workflow

1. Inventory readers, writers, stored forms, integrations, generated artifacts,
   and deployment ordering. Define compatibility invariants and failure behavior.
2. Establish usage signals for the old path before deprecation; define what
   evidence and observation window authorize contraction or removal.
3. Prefer expand, migrate, contract when state or versions overlap:
   - expand readers or schemas to tolerate old and new forms
   - deploy compatible writers and backfill in bounded, resumable, observable batches
   - verify correctness, coverage, lag, and old-path usage
   - contract only after consumers and state satisfy the removal gate
4. Make backfills idempotent or restart-safe, rate-limited, and explicit about
   malformed, concurrent, partial, and newly arriving data.
5. Define rollout holds, stop conditions, and forward recovery. Add a down
   migration only when reversal is safe, tested, and operationally required;
   destructive or semantically lossy changes generally need forward repair instead.
6. Communicate deprecation scope, replacement, owner, dates or gates, and user
   action through repository-owned channels.
7. Test mixed-version and partial-progress states that can actually occur.

## Expected Output

A gated migration or deprecation path with compatibility invariants, usage
evidence, resumable execution, verification, and realistic recovery.

## Validation

- Old and new versions interoperate for the required deployment window.
- Backfill progress, failures, and correctness are observable and restart-safe.
- Contract or removal is blocked until defined usage and state gates pass.

## Cautions

- Do not remove an old path merely because it was announced, tests pass, or the
  nominal date elapsed; verify actual usage and state first.
- Do not require universal down migrations. A plausible, tested recovery path is
  required, but irreversible transformations may need restore or forward repair.
- Do not combine expansion and destructive contraction into one rollout when
  mixed versions or live data can exist.

## Related Guidance

- `.agents/skills/api-interface-design/SKILL.md`
- `.agents/skills/planning-design/SKILL.md`
- `.agents/skills/observability/SKILL.md`
- `.agents/skills/verification/SKILL.md`
