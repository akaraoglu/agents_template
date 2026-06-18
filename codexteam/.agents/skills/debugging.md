# Debugging Skill

## Purpose

Diagnose failures and recover without guessing or overwriting useful evidence.

## When To Use

Use when tests fail, tools fail, project files are missing, the leader cannot find a document, or behavior does not match acceptance criteria.

## Inputs Needed

- Exact failure message
- Command or tool that failed
- Relevant file paths
- Current project tree
- Recent changes

## Workflow

1. Reproduce or inspect the exact failure.
2. Identify whether the failure is path resolution, missing context, bad spec, code defect, environment issue, or blocked requirement.
3. Read nearby files and docs before editing.
4. Make one focused fix.
5. Re-run the failed check.
6. If the issue is unclear, ask a targeted question.
7. Record the failure and fix in project state docs when it matters for future work.

## Expected Output

- Clear diagnosis
- Focused fix or blocker
- Re-run verification result

## Validation

- The original failure is addressed directly.
- Failed attempts are not erased from reports.
- The fix does not expand scope unnecessarily.

## Common Mistakes

- Editing random files without reproducing.
- Treating missing documents as nonexistent without listing files.
- Swallowing tool errors.
- Claiming recovery before the failed check passes.
