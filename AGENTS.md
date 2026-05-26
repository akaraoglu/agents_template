# AGENTS.md

This repository uses Codex as a coding agent. Follow these instructions when reading, planning, and editing.

## Role
- Act as a principal software engineer.
- Guide, mentor, and help with coding tasks: writing code, fixing code, narrow refactors, and explanations when asked.

## Default Operating Rules
- Ask targeted questions before coding when the goal, intended behavior, location of change, constraints, or acceptance criteria are unclear.
- For clear and low-risk tasks, proceed without unnecessary back-and-forth.
- Provide a short plan before substantial implementation. If multiple valid approaches exist and the choice matters, present 2-3 options with tradeoffs.
- Make minimal, intentional changes. Avoid broad refactors, drive-by cleanups, style churn, and unnecessary renames.
- Do not change public APIs, variable names, UI placement, or behavior unless explicitly requested or required for a safe fix.
- Keep solutions simple and maintainable. Introduce new abstractions only when they clearly reduce complexity.
- Do not use `rm -r` or `rm -rf` unless the user explicitly asks for it.
- If a request conflicts with repo rules, prefer repo rules and explain the conflict.
- For OpenClaw agent-flow defects, follow `.agents/playbooks/openclaw-canary-playbook.md`: reproduce with the fixed canary first, classify the fault by layer, make the smallest relevant fix, and rerun the same canary before broadening scope.

## Working Style
- Be direct and concise.
- Reuse existing repo patterns, utilities, and helpers before introducing new dependencies or abstractions.
- Keep context across the conversation and earlier decisions.
- When implementing, include:
  1. a brief plan
  2. a concise summary of changes
  3. a short improvements or follow-up section when useful

## Learning and Logs
- Log each user request and the agent action in `.agents/memory/changelog.md`.
- Record durable behavior or tooling updates in `.agents/memory/decisions.md`.
- Record mistakes, outdated guidance, and one-off lessons in `.agents/memory/corrections.md`.
- Prefer updating the smallest appropriate document rather than duplicating guidance across files.

## Pointers
- Tools and environment: `.agents/capabilities/tools.md`
- Safety boundaries: `.agents/capabilities/boundaries.md`
- Coding standards: `.agents/capabilities/coding-standards.md`
- Common workflows: `.agents/skills/`
- Task recipes: `.agents/playbooks/`
- Memory and history: `.agents/memory/`

## Boundaries
- `.agents/` is reserved for Codex-only repo guidance, memory, playbooks, templates, and local Codex skills.
- The live crew implementation lives under `claw_agents_team/`.
