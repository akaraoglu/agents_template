# Milestone Retrospective

Run the retrospective after each verified milestone commit. It binds completed
task results and runtime evidence to accepted per-task Integration Gate
snapshots, then binds the milestone commit to an Integration Gate verification
artifact whose workspace digest matches one of those accepted snapshots.

Run the commands below from the CodexTeam toolkit root. Each command targets an
exact control project through its `<control-root>` argument; generated control
projects do not contain a private copy of the script.

The v2 commands and `agent-evaluator` AgentSpec described here are the staged
new-round contract. When working from a branch where their implementation has
not yet landed, do not substitute historical v1 `analyze`; keep the milestone
pending until the v2 surfaces are available.

## V2 Lead Flow

New retrospective rounds use one staged path:

```text
prepare
  -> tool-free local evaluate
  -> review the strict evaluation report
  -> deterministic retrospective accept
  -> present prioritized Proposed entries
  -> human decide
```

`agent-evaluator` specializes the existing Reviewer role. It is not a new role
or authority, worker task, or workspace-capable session. `evaluate` supplies its
identity, guidance, strict schema, and immutable preparation packet directly to
one curated local Ollama request. The request has no tools, filesystem, MCP,
cloud profile, retries, or other project context. Deterministic caller code is
the only writer of the strict report under
`results/retrospectives/<boundary>/evaluations/`.

The evaluator handles the prepared metric and event material. The Lead need not
manually read all turn metrics or transcripts, but still reviews the evaluation
report and deterministic acceptance response. Observations are not causes: a
timeout, correction loop, replacement attempt, repeat, or large metric may
reflect natural complexity and does not by itself justify a change.

## Prepare

`prepare` validates the milestone evidence and, with `--apply`, writes one
content-addressed, immutable packet under
`results/retrospectives/<boundary>/preparations/<digest>/`. It makes no model
call and does not touch the backlog. The packet contains sanitized evidence,
deterministic observations, conservative evidence ceilings, and investigation
questions.

```bash
./scripts/milestone-retrospective.py prepare <control-root> \
  --boundary <id> --tasks <T001,T002> --apply --json
```

Same-root preparation uses the Git Steward commit record by default. Split-root
preparation requires `--work-root`, `--repo-id`, and the exact full `--commit`
together. The commit trailers must name the exact boundary, ordered task list,
and verification artifact. Each included completed task must resolve to exactly
one accepted Integration Gate snapshot for its result attempt. The milestone
verification workspace digest must match an included accepted snapshot; in
same-root mode, the commit record and committed verification artifact are also
checked against Git.

## Evaluate And Accept

Run one schema-constrained evaluator request and persist its validated report:

```bash
./scripts/milestone-retrospective.py evaluate <control-root> \
  --boundary <id> --preparation <preparation-digest> \
  --profile <curated-local-profile> --apply --json
```

Review that command's strict evaluation output. Then preview deterministic
acceptance with the exact digest and path it returned; add `--apply` only after
the preview is acceptable:

```bash
./scripts/milestone-retrospective.py accept <control-root> \
  --boundary <id> --preparation <preparation-digest> \
  --evaluation-digest <evaluation-digest> \
  --evaluation-path <evaluation-path> --json
```

The deterministic accept stage validates the Reviewer-derived AgentSpec
identity and digest, strict evaluation report, preparation digests, evidence
references, and action ceiling before publishing. It makes no model call.

- `E1`: retain an observation or conclude `NO_CHANGE`.
- `E2`: request investigation or conclude `NO_CHANGE`.
- `E3`: permit a proposal only when it names a concrete target and mechanism,
  alternatives, falsifiable validation cases, and rollback.

Proposals should be rare. Do not use a baseline from unlike work to judge speed.
A v2 `NO_CHANGE` result may contain observations and investigation requests; it
means no concrete change is justified now, not that nothing was observed.

Applied acceptance automatically adds validated E3 proposals to
`management/BACKLOG.md` with `Status: Proposed`, `Human disposition: None`, no
created task, and no implementation authority. Preview acceptance writes no
backlog entry.

The Lead presents the accepted entries categorically, without a composite
numeric score. Keep impact, change risk, change amount, reversibility,
confidence, and action band (`Candidate`, `Investigate`, or `Hold`) separate.
Order impact high to low, then action band, evidence strength, change risk low
to high to unknown, change amount small to large to unknown, reversibility easy
to hard to unknown, recurrence breadth, and stable ID. When appropriate, state
prominently:
`No candidate recommended this round`.

## Human Disposition

Preview a decision without mutation:

```bash
./scripts/milestone-retrospective.py decide <control-root> \
  --boundary <id> --proposal <IMP-...> --decision approve|reject|defer \
  --approver <identity> --reason <reason> --json
```

Apply a reviewed human decision:

```bash
./scripts/milestone-retrospective.py decide <control-root> \
  --boundary <id> --proposal <IMP-...> --decision approve|reject|defer \
  --approver <identity> --reason <reason> --human-approved --apply --json
```

Only an explicit human `decide` command may write a disposition, and an applied
decision requires both `--human-approved` and `--apply`. The immutable record is
stored under `results/retrospectives/<boundary>/dispositions/`, and the backlog
links to it. The record binds the exact proposal content by SHA-256. `approve`
means approved for normal planning only. It does not
create a task, authorize execution, change guidance or contracts, or grant
implementation authority. `reject` and `defer` are not approvals.

## Historical V1

Historical v1 `analyze` outputs, proposals, and dispositions remain immutable
and readable. The current CLI does not expose `analyze`. Do not resume,
reclassify, rewrite, or backfill them as v2. V1's
deterministic signal-to-proposal behavior is historical and must not be used for
a new round.

## Idempotency And Recovery

Reapplying unchanged preparation or acceptance validates and reuses the existing
content-addressed artifacts. Conflicting evidence or artifacts block rather
than overwrite prior state. Publication builds complete temporary artifacts
before atomic rename and serializes mutations with the project lock.

Decision application creates the immutable disposition before updating the
backlog. If interruption occurs between those writes, rerun the identical
human-approved command: it validates and reuses the matching record, then
finishes the backlog update. A conflicting record or backlog block fails closed.
