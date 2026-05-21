# Repo Workspace

## Purpose
Make the entire repository an explicit working scope for inspection and task-relevant edits.

## Trigger
Use this skill when work may span multiple areas of `~/workspace/agent_template_new` and the whole repo should be treated as available context and writable workspace.

## Scope
- All files under this repository may be inspected when relevant to the task.
- Task-relevant edits may be made anywhere in this repository, not only in the immediately mentioned folder or file.
- Prefer the smallest sufficient change even when the whole repo is in scope.

## Boundaries
- This skill does not change sandbox or filesystem permissions.
- Actual read/write authority still comes from the Codex runtime, sandbox mode, and writable roots.
- Keep following repo safety rules in `.agents/capabilities/boundaries.md`.
- Do not make unrelated edits, broad cleanups, or destructive changes unless explicitly requested.

## Working Rules
- When a task may touch several files or directories, inspect the full local repo as needed before deciding where to edit.
- Treat cross-file updates inside this repository as normal when they are required to complete the task safely.
- Reuse existing repo patterns, helpers, memory, and playbooks before introducing new structures.
- If a request truly needs files outside this repository, say so explicitly instead of assuming this skill grants access there.

## Verification
- The task can be completed without artificial repo-scope hesitation.
- Changes remain relevant, minimal, and consistent with repo rules.
