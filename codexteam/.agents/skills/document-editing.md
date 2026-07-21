# Document Editing Skill

## Purpose

Edit project documents carefully while preserving structure and recording only verified, temporally accurate truth.

## When To Use

Use for Markdown, plans, decisions, task files, briefs, reports, READMEs, and delivery handoffs.

## Inputs Needed

- User request or active handoff
- Target document and project doc map
- Relevant acceptance criteria and verified evidence
- Current project phase and task ownership

## Workflow

1. Resolve and read the existing document before editing.
2. Identify the smallest section that must change and preserve unrelated metadata and structure.
3. Match every status or delivery statement to current evidence and tense.
4. Do not turn future work, readiness, or a worker claim into completed verification.
5. Edit management state only when the handoff explicitly assigns it and the Project Lead has authorized the transition.
6. Return missing routine details to the Project Lead; involve the operator only for a genuine showstopper.
7. Reread the edited file and verify that requested changes are present and unrelated content survived.
8. Use the repository editing mechanism directly. Do not create one-off Python writers, patch files, scratch documents, or probe files for ordinary Markdown corrections.

## Communication Example

Good: “Focused unit tests passed; end-to-end verification is scheduled and is not yet a delivery claim.”

Bad: “The project is fully verified” when only the test harness is ready.

## Expected Output

- Minimal, reviewable document edits
- Preserved structure and stable identifiers
- Claims whose tense and evidence match current truth

## Validation

- The file was read before editing.
- No requirements, decisions, ownership, tests, or evidence were invented.
- Management changes were explicitly assigned and leader-authorized.
- The document makes sense without chat history.

## Common Mistakes

- Rewriting a whole document for a local correction
- Inventing delivery or test evidence
- Converting “will verify” into “verified”
- Silently changing task ownership or completion state
- Asking the operator for a routine missing detail the Project Lead can resolve
- Creating helper scripts or scratch files to perform a one-off document edit
- Adding a precise timestamp that was not actually observed
- Leaving carriage returns, broken Markdown delimiters, or temporary patch artifacts after a failed edit

## Related Files

- `.agents/skills/project-doc-map.md`
- `.agents/skills/subagent-orchestration.md`
- `BRIEF.md`
