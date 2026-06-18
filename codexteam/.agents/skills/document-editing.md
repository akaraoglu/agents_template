# Document Editing Skill

## Purpose

Edit existing project documents like a careful engineer: read first, preserve structure, change only what was requested, and verify the result.

## When To Use

Use whenever updating Markdown, project docs, task files, reports, plans, decisions, README files, or handoff documents.

## Inputs Needed

- User request
- Target document path
- Existing document content
- Relevant project doc map entry
- Any acceptance criteria or task constraints related to the edit

## Workflow

1. Resolve the document path from the request. If unclear, use the project doc map or ask a focused question.
2. Read the existing file before editing.
3. Identify the exact section, paragraph, table row, or list items that need to change.
4. Preserve all unrelated headings, metadata, IDs, task IDs, tables, and stable structure.
5. Make the smallest targeted edit that satisfies the request.
6. Do not rewrite the whole file unless the user explicitly asks for a full rewrite.
7. Do not invent requirements, tests, decisions, architecture, or delivery evidence.
8. If needed details are missing, ask the user or record them in `OPEN_QUESTIONS.md`.
9. Reread the edited file.
10. Verify the requested change is present and unrelated content survived.
11. Report the changed file and changed section.

## Expected Output

- Minimal document edit
- Existing document structure preserved
- Clear report of what changed

## Validation

- The file was read before editing.
- The edit is limited to the requested area.
- Stable metadata and unrelated sections remain.
- No placeholder text like `TBD`, `TODO`, `define later`, or fake evidence was introduced.
- The edited file still makes sense without chat history.

## Common Mistakes

- Rewriting `PROJECT.md` from scratch to change one paragraph.
- Deleting sections that were not mentioned by the user.
- Renaming headings without being asked.
- Inventing acceptance criteria or verification results.
- Guessing a document path instead of listing or asking.
