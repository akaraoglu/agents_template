# Milestone Retrospective

Run the retrospective after each verified milestone commit. It binds completed
task results and runtime evidence to accepted per-task Integration Gate
snapshots, then binds the milestone commit to an Integration Gate verification
artifact whose workspace digest matches one of those accepted snapshots.

Run the commands below from the CodexTeam toolkit root. Each command targets an
exact control project through its `<control-root>` argument; generated control
projects do not contain a private copy of the script.

## Outcomes

Every analysis invocation returns exactly one outcome:

- `NO_CHANGE`: evidence was sufficient and no deterministic signal qualified.
- `PROPOSALS_RECORDED`: evidence was sufficient and one or more signals
  qualified.
- `BLOCKED_INSUFFICIENT_EVIDENCE`: identity, evidence, advisory, locking, or
  publication validation failed.

Only the first two are persisted dispositions in
`results/retrospectives/<boundary>/analysis.json`. A blocked response is
transient CLI/API output. Normally it has `applied: false` and `mutates: false`
and is never persisted as `analysis.json`. If artifact publication succeeded but the
backlog write was interrupted, it truthfully reports the published artifact
root and mutation; rerun the same boundary to finish backlog insertion.

## Analysis

Preview without writes:

```bash
./scripts/milestone-retrospective.py analyze <control-root> \
  --boundary <id> --tasks <T001,T002> --without-model --json
```

Publish the evidence, strict `analysis.json`, report, and disposition directory:

```bash
./scripts/milestone-retrospective.py analyze <control-root> \
  --boundary <id> --tasks <T001,T002> --apply --json
```

Same-root analysis uses the Git Steward commit record by default. Split-root
analysis requires `--work-root`, `--repo-id`, and the exact full `--commit`
together. The commit trailers must name the exact boundary, ordered task list,
and verification artifact. Each included completed task must resolve to exactly
one accepted Integration Gate snapshot for its result attempt. The milestone
verification workspace digest must match an included accepted snapshot; in
same-root mode, the commit record and committed verification artifact are also
checked against Git.

The optional advisory is a single tool-free request to a curated local Ollama
profile at the fixed loopback endpoint, constrained by a strict schema. It receives sanitized,
deterministic evidence, has no tools, cannot qualify or suppress signals, and
cannot authorize action. Use `--without-model` for deterministic analysis with
`advisory_model: null`.

With `--apply`, every qualified proposal is automatically added to the backlog
with `Status: Proposed`, `Human disposition: None`, no created task, and no
implementation authority. `NO_CHANGE` writes the retrospective artifacts but
adds no proposal. Preview mode never writes either artifacts or backlog entries.
Proposal IDs include a 64-bit hash of the exact boundary identity so differently
spelled boundaries cannot collide after normalization.

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

## Idempotency And Recovery

Reapplying unchanged analysis returns the existing retrospective after checking
its evidence, deterministic analysis, report, disposition directory, and
backlog proposal blocks. Conflicting evidence or artifacts block rather than
overwrite prior state. Publication builds a complete temporary artifact tree
before an atomic rename and serializes mutations with the project lock.

Decision application creates the immutable disposition before updating the
backlog. If interruption occurs between those writes, rerun the identical
human-approved command: it validates and reuses the matching record, then
finishes the backlog update. A conflicting record or backlog block fails closed.
