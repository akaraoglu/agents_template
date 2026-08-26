# Architecture Design Skill

## Purpose

Turn approved requirements into a minimal, reviewable code and project architecture that guides implementation and verification.

## When To Use

Use for a nontrivial new project or a change to module boundaries, public APIs, persistence, deployment, security boundaries, concurrency, or major dependencies.

## Inputs Needed

- Approved requirements, constraints, non-goals, and acceptance criteria
- Existing architecture and relevant source when the project already exists
- Runtime, deployment, security, compatibility, and operational constraints
- Active Architect handoff and accepted decisions

## Workflow

1. Review the handoff's Prior Discoveries. If the Lead reports no search, return
   the context gap rather than repeating broad source discovery.
2. Map requirements and quality attributes to concrete architectural concerns.
3. Verify relevant prior findings against the current system before proposing an architecture change.
4. Define system boundaries, components, responsibilities, and allowed dependency direction.
5. Specify public contracts, data flow, trust boundaries, failure behavior, and observability.
6. Define the repository layout and ownership of source, configuration, tests, fixtures, and documentation.
7. Map unit, smoke, and integration coverage to the proposed boundaries.
8. Record material alternatives and create an ADR only when the decision has lasting consequences.
9. Identify migration, compatibility, rollout, and reversal requirements.
10. Return the design for independent Project Lead approval; do not implement it.

## Commands To Run

Use read-only repository inspection and existing project validation commands. Run documentation or diagram validation only when the project already defines it.

When `local-docs` is available and the design depends on an indexed installed
library or CodexTeam contract, start with one narrow `search_docs` call and a
limit of at most five. Do not guess source IDs; omit the filter when the exact
indexed ID is unknown, and call `list_doc_sources` only when an exact source or
version filter is required. Use `read_doc` only for the winning locator. Treat
an unavailable or insufficient result as a reason for one focused repository
or upstream-documentation fallback, not a repeated broad search.

## Expected Output

- A current `ARCHITECTURE.md` with an exact repository map
- Focused supporting documents under `docs/architecture/` only when size requires them
- Material ADR proposals under `docs/decisions/`
- Architecture evidence that traces decisions to approved requirements

## Validation

- Every component and dependency exists to satisfy an approved requirement or quality attribute.
- Public contracts, failure behavior, security boundaries, and test seams are explicit.
- The design fits the approved runtime and dependency constraints.
- The Developer can implement without inventing missing structural decisions.
- The Architect has not changed source, tests, or canonical lifecycle state.

## Common Mistakes Or Failure Modes

- Designing from an assumed greenfield state without inspecting existing code
- Adding speculative layers, frameworks, or extension points
- Listing directories without defining responsibilities and dependency direction
- Ignoring migration, compatibility, failure, security, or test architecture
- Writing implementation code or approving the Architect's own proposal

## Related Files

- `ARCHITECTURE.md`
- `docs/architecture/`
- `docs/decisions/`
- `PROJECT.md`
- `IMPLEMENTATION_PLAN.md`
- Active Architect handoff under `management/tasks/`
