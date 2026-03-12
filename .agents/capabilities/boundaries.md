# Boundaries

These rules are non-negotiable unless the user explicitly asks for a controlled exception.

## Clarify First When Needed
- Ask targeted questions before coding when the goal, intended behavior, change location, constraints, or acceptance criteria are unclear.
- Present options with tradeoffs when multiple valid approaches exist and the choice materially affects the implementation.

## Change Scope
- Change only what is required to satisfy the request.
- Avoid broad refactors, drive-by cleanups, style churn, and unnecessary renames.
- Do not touch unrelated code. If adjacent code must change to complete the task safely, keep the change narrow and justified.
- Do not change public APIs, variable names, UI placement, or behavior unless explicitly requested or required for a safe fix.
- Prefer small diffs over "perfect" code.

## Safety
- Do not overwrite, discard, or revert user changes unless explicitly requested.
- Do not use `rm -r` or `rm -rf` unless the user explicitly asks for it.
- Do not use destructive commands such as force resets or broad deletes without clear approval.
- Do not introduce secrets, credentials, or sensitive data into the repository.
- Do not log sensitive input or output.

## Conflict Handling
- Stop and clarify if a request conflicts with repo rules or creates ambiguous risk.
- Record durable lessons in the appropriate `.agents` document.
