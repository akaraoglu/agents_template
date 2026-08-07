---
name: planning-design
description: Produce an implementation-ready plan or software design grounded in repository evidence. Use for planning requests, ambiguous or multi-part changes, architecture work, and changes to public interfaces, schemas, data, dependencies, or operations.
---

# Planning and Design

## Purpose

Turn a requested outcome into the smallest implementation-ready design that
fits the existing system and exposes material decisions and risks.

## Inputs

- Goal, acceptance criteria, constraints, and non-goals
- Existing architecture, conventions, related implementations, and tests
- Affected users, interfaces, data, and operational environment

## Workflow

1. Confirm the task is planning or design and whether implementation is also
   authorized.
2. Inspect the current system before proposing a new structure.
3. Define current behavior, desired behavior, scope, and explicit non-goals.
4. Identify affected contracts:
   - public APIs and commands
   - persisted schemas and migrations
   - configuration and environment
   - events, protocols, file formats, and integration boundaries
5. Describe the design at the level needed to implement it:
   - responsibilities and dependency direction
   - data and control flow
   - validation, errors, cleanup, and failure modes
   - concurrency, performance, security, privacy, and observability where relevant
6. Reuse existing patterns. Compare alternatives only when the decision has
   material consequences; state the selection criteria and rejected tradeoffs.
7. Divide implementation into coherent, ordered steps with exact affected areas.
8. Map each acceptance criterion and risk to tests or another verification
   method.
9. Identify migration, rollout, rollback, compatibility, and documentation work
   when applicable.
10. Record assumptions and open questions. Ask the user only about unresolved
    choices that would materially alter the result.

## Expected Output

An implementation-ready plan containing:

- goal, scope, and non-goals
- repository evidence and affected interfaces
- selected design and material alternatives
- ordered file or component changes
- verification strategy
- risks, assumptions, and unresolved decisions

For a small change, this may be a short ordered list rather than a separate
design document.

## Validation

- The plan matches existing architecture and repository conventions.
- Every acceptance criterion maps to implementation and verification.
- Compatibility-sensitive changes include migration or explicit breakage policy.
- The plan does not include speculative abstractions or unrelated cleanup.
- Another engineer could implement it without rediscovering key decisions.

## Cautions

- Do not design from the request alone when repository evidence is available.
- Do not use optional parameters or compatibility layers automatically; first
  establish whether compatibility is required.
- Do not confuse an implemented-code explanation with a proposal for future
  architecture.
- Do not block implementation with unnecessary alternatives or approval steps.

## Related Guidance

- `.agents/skills/engineering-workflow/SKILL.md`
- `.agents/skills/implementation/SKILL.md`
- `.agents/skills/verification/SKILL.md`
- `.agents/capabilities/coding-standards.md`
