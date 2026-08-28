# CodexTeam System Overview

## Summary

CodexTeam is a local-first, supervisor-orchestrated, policy-governed agentic
software delivery control plane. It runs self-hosted specialist agents,
constrains their authority, preserves execution provenance, and requires
evidence before accepting their work.

It is closer to an agentic software-development lifecycle and CI/CD governance
system than to an autonomous agent swarm or a general multi-agent framework.

> CodexTeam is a local agentic software-delivery operating system: a
> supervisor-led control plane for self-hosted specialist agents, with
> contract-bound execution, progressive context delivery, capability isolation,
> evidence-gated acceptance, and deterministic delivery controls.

## Agentic Vocabulary

| CodexTeam concept | Modern agentic term |
|---|---|
| Project Lead | Supervisor agent, orchestrator, or control-plane agent |
| Specialized worker role | Policy-bound specialist agent |
| Task handoff | Work-order contract or task capsule |
| Attempt | Accountable execution unit |
| Persistent session | Stateful agent actor |
| RolePolicy | RBAC-like capability envelope |
| AgentSpec | Capability specialization overlay |
| Execution profile | Model and runtime configuration |
| ExecutionSpec | Immutable run manifest or execution lockfile |
| Draft | Candidate work checkpoint |
| Feedback | Supervisor correction loop |
| Finalization | Deterministic result sealing |
| Development Gate | Producer-side quality gate |
| Integration Gate | Independent CI-equivalent quality gate |
| Test Engineer | Independent evaluator agent |
| Reviewer | Critic or judge agent |
| Git Steward | Privileged transaction broker |
| Control root | Agent control plane and artifact plane |
| Source repository | Product execution and data plane |
| `codexteam-context` | Project-scoped context gateway |
| `local-docs` | Offline sparse retrieval-augmented generation |
| Project memory | Source-backed institutional memory |
| Context pack | Context provenance manifest |
| Turn metrics | Agent observability telemetry |
| Skill evaluator | Guidance routing and behavioral conformance harness |
| Milestone retrospective | Post-delivery evidence analyzer |
| Improvement proposal | Automatically recorded, human-gated backlog candidate |
| Improvement disposition | Immutable human planning decision |

## System Shape

CodexTeam uses a hierarchical supervisor pattern:

```text
Operator
  -> authorizes
Project Lead
  -> delegates bounded work contracts
Specialist agents
  -> produce artifacts and evidence
Deterministic gates and finalizers
  -> validate and seal results
Canonical project state
  -> advances only after acceptance
Git Steward executor
  -> creates an explicitly authorized local commit
Milestone retrospective
  -> records no change or Proposed improvements
Human disposition
  -> approves, rejects, or defers planning
```

Workers do not spawn other workers, negotiate ownership, or autonomously alter
the project plan. The Project Lead remains the single reconciliation,
delegation, feedback, and acceptance authority.

The available specialist responsibilities include Architect, Feature Planner,
UX Designer, Developer, Test Engineer, Reviewer, Documenter, and Local Git
Steward. A protocol role defines responsibility. An AgentSpec may narrow that
role for a technical specialization. An execution profile selects the model and
runtime independently of both.

## Self-Hosted Execution Plane

Codex CLI is the active agent runtime, with Ollama providing qualified local
models. Execution is admitted through a curated registry rather than trusting
every installed model or profile automatically.

Before an attempt starts, CodexTeam resolves and records:

- Project, task, attempt, role, and workspace identity
- Canonical handoff and content digest
- RolePolicy and optional AgentSpec
- Model, profile, backend, and reasoning request
- Guidance bundle and digests
- Sandbox and writable-root settings
- MCP server and tool permissions
- Task write scope
- Development or Integration Gate routing

This resolved state becomes an immutable, digest-bound `ExecutionSpec`. Feedback
and finalization reload it rather than accepting new execution selectors. This
provides reproducible workload admission and prevents ordinary correction turns
from silently changing the model, role, permissions, or task contract.

## Persistent Agent Actors

A worker attempt is a durable actor rather than a disposable prompt. It retains:

- Stable task, attempt, role, model, and policy identity
- The exact provider thread
- Pinned role and guidance snapshots
- Workspace baseline and accepted change manifest
- Turn history and operational status
- Evidence references and digests
- An accepted checkpoint and final result reference

The lifecycle is:

```text
draft -> supervisor review -> feedback -> revised draft -> deterministic final
```

Ordinary corrections resume the same thread and attempt. Current finalization
does not invoke the model. The launcher revalidates the accepted checkpoint and
constructs the final result deterministically, preventing a final provider turn
from changing accepted work.

## Capability and Role Security

Roles are authority partitions, not only personas:

- Architects own architecture artifacts, not production implementation.
- Developers own production source and focused tests, not integration
  expectations or lifecycle state.
- Test Engineers own integration and regression evidence, not production
  repairs.
- Reviewers identify defects and acceptance gaps but do not repair the work they
  review.
- The Git Steward model is read-only; deterministic host code performs Git
  mutation.

Effective authority is approximately:

```text
RolePolicy
intersection AgentSpec
intersection task write scope
intersection workspace boundary
intersection MCP tool allowlist
```

CodexTeam validates post-execution changes against this authority. Most
fine-grained path restrictions are currently detective rather than preventive:
the broad runtime sandbox limits the workspace, while CodexTeam detects and
rejects out-of-policy changes after a turn. Unauthorized changes are not
automatically accepted or silently reverted.

## Control and Source Separation

The default architecture separates the control plane from product source:

- A control root owns project state, tasks, handoffs, runtime, results, gates,
  discoveries, and project-specific agent guidance.
- A registered source repository owns product code, tests, build configuration,
  and product documentation.
- `REPOSITORIES.json` binds a control project to an exact source root and
  repository identity.
- Bound worker MCP servers receive the selected project and source binding from
  the launcher. Their tool schemas do not let workers choose another project.

This provides project-local governance and memory without a shared global agent
database. Legacy single-root operation exists, but split-root control/source
ownership is the preferred architecture.

## Context Engineering

CodexTeam has a deliberate context orchestration layer:

- Progressive disclosure routes only phase-relevant guidance.
- Canonical handoffs provide objectives, exact context targets, constraints,
  write scope, completion criteria, and stop conditions.
- Role guidance and execution policy are pinned for each attempt.
- Feedback prompts carry correction deltas rather than reconstructing the whole
  assignment.
- Context packs record identities, source digests, tool use, and response sizes
  without duplicating sensitive prompt or MCP content.
- Lead checkpoints support conversation rotation without becoming acceptance
  evidence.
- Compact task capsules have been evaluated as an optional way to reduce broad
  source discovery.

The design prefers exact locators, bounded retrieval, and source provenance over
injecting complete repositories, result histories, or guidance libraries into
every model turn.

## Retrieval and Institutional Memory

### Project Context

`codexteam-context` is a read-only, project-scoped context gateway. It provides
bounded structured access to:

- Active project and task state
- Canonical task handoffs
- Attempt and result summaries
- Gate status and freshness
- Repository search and change summaries
- Canonical project decisions, architecture, open questions, and discoveries
- Token, latency, and tool-cycle hotspots

Responses include source paths, hashes, byte counts, truncation information, and
query statistics. They provide context and provenance, not execution or
acceptance authority.

### Local Documentation RAG

`local-docs` is a narrow offline sparse-RAG system:

- Approved sources are indexed deterministically in SQLite FTS5.
- Retrieval uses BM25 and term coverage.
- Results provide bounded excerpts and exact locators.
- Source versions and content hashes remain visible.
- The MCP runtime opens the index read-only and has no network, shell, indexing,
  or arbitrary-path tool.

There are no application-level vector embeddings or global vector database.
This is intentional: current retrieval prioritizes determinism, inspectable
provenance, project isolation, and low operational complexity.

### Memory Authority

Canonical memory remains in reviewed project files such as `DECISIONS.md`,
`OPEN_QUESTIONS.md`, `ARCHITECTURE.md`, and architecture decision records.
Discovery notes under `discoveries/` are durable advisory research and
must be verified against current source. Runtime transcripts and worker claims
are not promoted automatically into institutional memory.

## Evidence-Gated Delivery

CodexTeam follows a maker-checker assurance model:

```text
Developer work and evidence
  -> Development Gate
Test Engineer evidence
  -> Integration Gate
Reviewer assessment
  -> Project Lead acceptance
Deterministic finalization and closure
```

A worker reporting `completed` does not complete a task. The system distinguishes
between:

- A worker claim
- A structurally valid artifact report or result envelope
- Existing evidence artifacts
- A passing and fresh quality gate
- Independent evaluator or reviewer judgment
- Project Lead acceptance
- Canonical project closure

Development and Integration Gates use structured argument arrays, bounded
output, sanitized environments, process-group cleanup, and workspace and
configuration digests. Integration includes Development first. Passing records
can be copied into task- and attempt-addressed accepted evidence.

## Deterministic Finalization

Workers produce a small artifact report containing a summary, evidence paths,
and limitations. After acceptance, deterministic launcher code:

- Revalidates attempt and execution identity
- Confirms the accepted checkpoint is the latest draft
- Verifies report, evidence, and changed-file digests
- Confirms the accepted change manifest
- Checks routed gate freshness
- Constructs and writes the final result exactly once

This creates a provider-independent completion protocol. The result is still an
attempt record, not independent product acceptance or authority to advance
canonical task state.

## Git Governance

Git mutation is isolated behind a two-phase local transaction:

```text
Read-only Git Steward agent creates a commit plan
  -> Project Lead authorizes exact paths, branch, and HEAD
Deterministic executor constructs the candidate tree
  -> Integration Gate verifies that tree in isolation
Executor stages only authorized paths
  -> staged and committed trees are compared with the candidate
One local commit is created
```

Normal agents do not receive authority to push, merge, tag, publish, release, or
open remote pull requests. Those operations remain outside the current Git
Steward contract.

## Agent Observability

CodexTeam records bounded local telemetry for worker and Lead activity,
including:

- Prompt and guidance bytes
- Input, cached-input, and output tokens
- Turn duration and termination reason
- Tool, command, failure, and edit counts
- Repeated commands and command-output volume
- MCP calls, latency, returned bytes, and source digests
- Workspace and evidence provenance
- Lead and worker usage attribution

This is an agent observability layer rather than financial accounting. It does
not yet calculate currency cost or represent every token that may be visible in
provider-side system instructions, tool schemas, or persistent history.

## Evaluation and Self-Improvement

CodexTeam now has two complementary evaluation loops. They use local models only
for bounded advisory judgment; deterministic code retains authority over
qualification, persistence, and state changes.

### Skill Evaluation

The skill evaluator tests whether the guidance system remains coherent before a
guidance change is promoted:

- Structural checks validate root skill frontmatter, required sections,
  references, role skill ordering, project guidance projection, and AgentSpec
  guidance containment.
- Fixed positive and negative cases test skill routing and selected CodexTeam
  authority decisions.
- Candidate route and decision identifiers are supplied without revealing which
  are required or forbidden.
- Every case in the selected catalog must pass.
- Manual evaluation uses one schema-constrained request to a curated local
  Ollama profile.
- The evaluator refuses cloud profiles and has no filesystem, shell, MCP,
  lifecycle, project-state, or retry capability.

This evaluator answers: **does a proposed instruction or skill change cause the
agent to select and follow the intended workflow without broadening authority?**
It does not evaluate a completed project milestone or approve a guidance change.

### Milestone Retrospective

After each verified milestone commit, the Project Lead runs a project-local
retrospective. The analyzer binds:

- Completed task results to matching runtime attempts and roles
- Accepted per-task Integration Gate snapshots
- The terminal ordered task's accepted workspace digest
- The exact milestone commit, tree, trailers, and verification artifact
- Split-root repository and runtime provenance
- Worker turns, feedback loops, replacement attempts, timeouts, Run Guard
  interruptions, failed tools or commands, MCP fallbacks, and repeated command
  fingerprints
- Lead and worker usage summaries without raw prompts or process output

The committed tree is independently reconstructed from Git blobs using the same
verification-path semantics as the Integration Gate. This prevents a correctly
labelled commit from being associated with unrelated verification evidence.

Every analysis invocation returns one explicit outcome:

- `NO_CHANGE`: evidence is sufficient and no deterministic signal qualifies.
- `PROPOSALS_RECORDED`: one or more deterministic signals qualify.
- `BLOCKED_INSUFFICIENT_EVIDENCE`: identity, evidence, advisory, locking, or
  publication validation prevents a safe conclusion.

Only the first two become persisted retrospective dispositions. A blocked result
is normally non-mutating and must be corrected and rerun. If artifact publication
succeeds before backlog insertion is interrupted, the result truthfully reports
the partial state and the same boundary can recover it.

### Improvement Qualification

Deterministic rules decide whether evidence qualifies. Examples include:

- Invalid or missing modern execution or delegation identity
- Scope or authority violations carrying an explicit structured marker
- Multiple attempts for one task
- Two or more feedback rounds for one attempt
- Timeouts or Run Guard interruptions
- Recurring failed tool activity or MCP fallback loops
- Repeated command fingerprints across turns
- Explicit evidence-integrity or unsupported-acceptance findings

An isolated ordinary mistake, preference-only feedback, or unmeasured efficiency
difference does not automatically qualify. `NO_CHANGE` is a valid and expected
outcome.

### Backlog and Human Authority

Every qualified signal produces one collision-resistant improvement proposal.
Applied retrospective analysis automatically appends it to the project backlog
with:

- `Status: Proposed`
- Evidence, impact, confidence, expected gain, validation, and rollback
- No task creation
- No implementation authority
- No human disposition

An optional tool-free local advisory model may summarize qualified signals or
recommend a smaller response class. It cannot add a signal, suppress a signal,
approve a proposal, create a task, or authorize execution.

Only an explicit human `decide --human-approved --apply` operation may transition
a proposal to `Approved`, `Rejected`, or `Deferred`. The immutable disposition
binds the exact proposal content by SHA-256. `Approved` means approved for normal
planning only; implementation still requires the existing task, assignment,
execution, verification, review, and authorization process.

The improvement response is scaled to impact:

| Evidence | Smallest candidate response |
|---|---|
| Existing rule was misunderstood | Instruction clarification |
| Reusable judgment or trigger is missing | Skill update |
| Handoffs repeatedly omit required context | Template update |
| Evidence cannot represent a required fact | Contract update |
| Repeated manual action is deterministic and error-prone | Tool update |
| Authority, isolation, gate, or runtime mechanism failed | System update |

### Improvement Lifecycle

CodexTeam's improvement lifecycle is:

```text
observe -> qualify -> propose -> human disposition -> plan -> implement
        -> independently verify -> accept or reject -> measure recurrence
```

Existing attempts retain their pinned guidance. A retrospective never rewrites a
healthy active attempt, and accepted improvements do not apply retroactively.

## Deliberate Non-Goals

CodexTeam is not currently:

- An autonomous or peer-to-peer agent swarm
- A generic graph execution framework
- A distributed worker scheduler or queue service
- A multi-user agent cloud
- A hostile-workload container or virtual-machine sandbox
- A vector-memory platform
- An automatic task splitter, retry engine, or model-switching controller
- A writable remote Git or deployment controller

The system deliberately favors explicit supervision, bounded delegation,
persistent ownership, and reviewable evidence over emergent multi-agent
behavior.

## Maturity

The most developed capabilities are:

- Persistent draft-feedback sessions
- Immutable execution identity and pinned guidance
- Role and capability partitioning
- Curated self-hosted model admission
- Split control/source ownership
- Bounded context and documentation retrieval
- Source-backed project memory
- Evidence provenance and gate freshness
- Provider-free finalization
- Deterministic local Git transactions
- Process supervision, timeout handling, and cleanup
- Structural and behavioral skill evaluation
- Evidence-bound milestone retrospectives
- Automatic Proposed backlog capture with human-gated disposition

The principal platform-level limitations are:

1. Some published JSON schemas and documents have drifted from current runtime
   contracts, particularly split-root records.
2. Proposal approval, plan acceptance, architecture acceptance, and operator
   `GO` remain procedural rather than durable machine-enforced authorization
   records.
3. Task transitions and dependencies are not enforced as a formal scheduler or
   state machine.
4. Fine-grained worker write restrictions are mostly detected after execution.
5. Split-root change auditing can miss Git-ignored files.
6. The Git Steward executor does not yet support the preferred split-root
   topology.
7. Canonical closure updates several files individually rather than through one
   project-wide transaction.
8. External MCP identities and advertised tool catalogs are not fully attested
   by the launcher.
9. Local SHA-256 provenance provides drift and tamper evidence but not digital
   signatures, trusted identities, or append-only attestations.

## Architectural Position

CodexTeam should be understood as a specification-driven agentic engineering
control plane with strong local execution and assurance mechanisms. Its primary
differentiators are accountable ownership, persistent correction sessions,
capability attenuation, source-backed context, evidence freshness, and
deterministic acceptance boundaries. Its next stage of maturity is not adding
more agents or more memory; it is strengthening machine-enforced workflow
authorization, preventive containment, split-root lifecycle completeness, and
contract coherence.
