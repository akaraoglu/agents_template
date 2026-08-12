# CodexTeam 2.0 Draft

## Status

Implemented experimental foundation. CodexTeam v1 remains unchanged and is the
default while v2 is evaluated in parallel. Deterministic and fake canaries pass;
live Muse Glimmer acceptance remains pending. Focused metadata, direct API, and
minimal OpenCode qualification passed all required checks. The first
post-qualification adaptive canary reached the Verification candidate after
successful Discovery, revision, Architecture, UX, Developer, and Test writer
turns, then failed closed because the generated schema exposed evidence types
that StageRunner correctly rejects for Verification. The schema is now
stage-specific. A later benchmark reached Assurance with accepted verification
before Ollama `0.32.8` hit its Muse function-call boundary parser defect; the
host is now upgraded to `0.32.9`, which contains the exact upstream fix. No
automatic live retry was made. Post-upgrade qualification passed all nine
checks, but the next fresh adaptive canary failed closed when Muse returned
malformed JSON from the read-only Architecture candidate despite the exact
stage-specific schema. Qwen is retained only as an inactive historical baseline
after output reliability failures in preserved canary runs.

Foundation v2 now routes all seven active AgentSpecs exclusively through
OpenCode `1.18.16` and `ollama/muse-glimmer:30b`. Muse Glimmer was selected for
the next evaluation because the local model supports completion, tools,
thinking, vision, and a 131072-token context. The OpenCode canary uses a
product-only working directory, private runtime/config, user-systemd descendant
cleanup, readonly candidate turns, StageRunner post-turn audit, and kernel
verification. Codex definitions remain present but are inactive and have no
live v2 CLI entry.

## Objective

Build a contract-first software-development agent-team framework whose first
proof is one adaptive, serial pipeline:

```text
Discovery Analyst
  -> optional Architect
  -> optional UX Designer
  -> Developer
  -> Test Engineer
  -> Assurance Auditor
  -> Acceptance Reviewer
  -> deterministic candidate seal
  -> Project Lead closure
```

The framework must be strict about facts that can be enforced mechanically and
adaptive about uncertainty that requires engineering judgment.

## Design Principles

1. Fail closed for identity, permissions, path containment, immutable pins,
   evidence integrity, independence, destructive actions, and state corruption.
2. Return ambiguity, missing context, environment failures, malformed model
   output, and unexpected behavior to the Project Lead for recovery.
3. Escalate scope, hard-budget, privilege, paid-service, destructive, release,
   deployment, and remote-Git decisions to the operator.
4. Keep active attempts immutable. Pipeline revisions affect only future stages
   or explicitly created successor attempts.
5. Treat agent output as an untrusted claim. The launcher owns process facts,
   workspace changes, evidence freshness, and candidate identity.
6. Keep v2 inspectable: JSON records, append-only events, deterministic views,
   no database or daemon in the first release.
7. Add complexity only after a measured canary exposes a concrete need.

## Core Composition

```text
Responsibility
+ AgentSpec
+ capabilities
+ permission policy
+ guidance bundle
+ model profile
+ backend definition
+ assignment scope
= immutable RoleInstance
```

Capabilities describe knowledge and required operations. They never grant
authority. Effective permission is the intersection of the responsibility
ceiling, project policy, AgentSpec policy, assignment scope, operator grants,
and backend enforcement.

## Initial Responsibilities

- `project_lead`: scope, assignments, decisions, and lifecycle closure
- `analyst`: discovery, requirements, repository analysis, and research
- `designer`: architecture and UX design
- `implementer`: production changes and producer-owned tests
- `verifier`: independent integration and acceptance evidence
- `assurance_auditor`: specialist risk assurance without remediation
- `reviewer`: acceptance-criteria and evidence review

## Initial AgentSpecs

- `ct2.analysis.discovery`
- `ct2.design.architecture`
- `ct2.design.ux`
- `ct2.implementation.developer`
- `ct2.verification.test-engineer`
- `ct2.assurance.auditor`
- `ct2.review.acceptance`

The single Assurance Auditor supports these assignment domains:

- `security_privacy`
- `data_database`
- `accessibility`
- `performance_reliability`

Acceptance Reviewer remains a separate independent responsibility.

## Adaptive Compiled Pipeline

The system recommends an initial named pipeline. The Project Lead approves the
compiled plan before execution. Agents may request future changes through typed
mailbox messages. An accepted change creates an immutable pipeline revision.

Discovery may request Architect, UX Designer, or both. When both are required,
Architect precedes UX. The Lead may approve these additions autonomously when
they remain inside approved product scope, permissions, providers, and hard
budgets and do not weaken verification.

Operator approval is required for material product-scope or acceptance changes,
breaking API or migration decisions, hard-budget increases, new paid or external
services, new credentials or privileges, destructive operations, reduced
assurance, publication, deployment, or remote Git actions.

## Typed Orchestrator Mailbox

Agents communicate only through the Lead/orchestrator:

```text
Agent -> Lead/orchestrator -> Agent
```

Direct worker messaging and worker spawning are rejected. Messages are durable,
typed, digest-addressed, correlated, idempotent, and processed at least once
with effectively-once state effects.

Initial message types:

- `question`, `response`, `context_gap`, `blocker`, `conflict`
- `pipeline_change_request`, `work_item_proposal`
- `candidate_ready`, `verification_defect`, `assurance_finding`
- `lead_decision`, `acknowledgement`, `cancellation`

No lifecycle action is inferred from prose. Agent text and attachments are
untrusted data. Only typed, authorized Lead decisions may trigger control
actions.

## Candidate Processing

Workers author semantic claims only: outcome, criterion dispositions, findings,
limitations, evidence references, and requested disposition.

The launcher owns:

- RoleInstance, backend, model, session, and attempt identity
- exit status, duration, command arguments, and output artifacts
- baseline and final workspace manifests
- exact ChangeSet and forbidden-write audit
- evidence digests and freshness
- timestamps and candidate identity

Malformed semantic output remains correction-needed in the same attempt. It
does not silently succeed or automatically create a replacement attempt.

## Verification And Assurance

Verification consists of immutable plans, launcher-observed runs, and
criterion-level independent receipts. Any relevant source, test, configuration,
or guidance change invalidates affected evidence.

Assurance Auditor is read-only and returns a disposition for every selected
domain. Acceptance Reviewer receives the current pipeline revision, cumulative
ChangeSet, fresh verification receipts, assurance report, approved requirements,
and unresolved limitations. It returns `ACCEPT`, `RETURN`, or `BLOCK`.

## Policy Exceptions

The Lead may issue a scoped `PolicyException` only for a soft policy check. It
must contain the exact rule, scope, reason, evidence, compensating verification,
expiry, and approving Lead decision.

Exceptions cannot waive identity, permissions, path containment, evidence
integrity, independence, destructive-action authorization, secret protection,
or state-integrity rules.

## Validation Outcomes

- `reject`: hard security or integrity violation
- `correction_needed`: recoverable agent-output problem
- `lead_review`: ambiguity, environment failure, or unexpected behavior
- `operator_required`: scope, budget, privilege, destructive, or external boundary
- `warning`: visible non-blocking concern

## Candidate Seal

A candidate is sealed only when all required stages succeeded, the workspace
matches the derived ChangeSet, no forbidden or unattributed changes exist,
verification receipts are fresh and accepted, required assurance passed, and
Acceptance Reviewer returned `ACCEPT`.

The SHA-256 seal covers canonical contract versions, WorkItem, PipelineRevision,
ordered RoleInstances, ContextPacks, StageCandidates, base/final workspace
manifests, ChangeSet, verification receipts, assurance report, and acceptance
decision. Volatile display metadata is excluded. Repeating a seal operation with
identical inputs is idempotent.

## Storage

```text
<project>/.codexteam/v2/
  project.json
  catalog-lock.json
  records/
  mailbox/
  events/
  state/project-state.json
  runtime/
  evidence/
  seals/
  views/
```

Canonical state uses immutable JSON records and append-only JSONL events.
Project state and Markdown documents are reproducible projections.

## Implementation Order

1. Freeze and verify v1 without modifying it.
2. Implement canonical IDs, serialization, digests, references, and strict v2
   contract models.
3. Implement the catalog, permission intersection, AgentSpec resolver, guidance
   composition, and immutable RoleInstances.
4. Implement adaptive pipeline compilation, typed mailbox records, Lead
   decisions, revisions, events, and state replay.
5. Implement ContextPacks, candidates, ChangeSets, evidence, verification,
   assurance, acceptance review, and candidate sealing.
6. Implement fake Codex and OpenCode adapters and failure-injection tests.
7. Require focused Muse/OpenCode qualification, then let the parent decide
   whether to run a live adaptive canary.
8. Add specialist AgentSpecs, language packs, parallelism, richer views, and
   migration only after measured evidence justifies them.

## First Canary Acceptance

The first live canary exercises both optional stages and one defect-return loop:

1. Discovery requests Architect and UX through typed records.
2. Lead approves a future-only pipeline revision.
3. Architect and UX run sequentially.
4. Developer implements the bounded product.
5. Test Engineer finds a seeded product defect.
6. Developer corrects it in the same session.
7. Test Engineer resumes and passes.
8. Assurance Auditor passes selected domains.
9. Acceptance Reviewer accepts.
10. Candidate sealing and Lead closure are idempotent.

## ECC Lessons

Adopt owner/scope/state/evidence/gate contracts, explicit phases, artifact-based
handoffs, backend adapters, typed communication concepts, content-addressed
candidates, eval-first promotion, and observable projections.

Reject keyword-only chain selection, direct worker chains, free-text completion,
send-only messaging, universal coverage rules, automatic commits, worktree
dependence, early database/daemon complexity, remote dispatch, and regex risk
scores as authorization.

Substantially adapted ECC material must retain commit-pinned MIT provenance and
the upstream copyright notice.

## Deferred

- SQLite, daemon, scheduler, remote dispatch, and direct messaging
- arbitrary workflow scripting and parallel workers
- automatic retries and profile transfer
- worktree orchestration
- specialist and language catalogs
- runtime catalog downloads or a marketplace
- v1 migration or dual writing
- Git commits, releases, deployment, or publication in the canary

## Completion Standard

V2 becomes supported opt-in only after strict contract and catalog tests,
permission and evidence failure injection, deterministic fake-backend canaries,
one successful live OpenCode/Muse Glimmer adaptive canary, context-budget checks, and a
rollback drill. V1 remains the default until a separate migration decision.
