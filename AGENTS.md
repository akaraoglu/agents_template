## Skill, Tool, and Self-Improvement Rules

Codex may improve repository-local agent guidance only when the improvement is durable, specific, and useful for future tasks.

### Definitions

- A **skill** is a reusable workflow or capability description stored under `.agents/skills/`.
  - Use skills for repeatable tasks that require consistent steps, conventions, commands, validation, or domain-specific judgment.
  - Skills should explain how to perform the task, when to use it, expected inputs, expected outputs, validation steps, and common failure modes.

- A **playbook** is a task-specific troubleshooting or implementation procedure stored under `.agents/playbooks/`.
  - Use playbooks for narrow operational flows, incident/debugging procedures, migrations, canary workflows, or known defect classes.

- A **tool** is an executable helper script or command wrapper used by Codex to make repeated work safer or faster.
  - Prefer tools for deterministic, error-prone, or repetitive operations.
  - Tools must be small, documented, and testable.
  - Tools that modify files must support a clear preview/dry-run mode when practical.

- A **memory entry** is a concise record of durable project knowledge stored under `.agents/memory/`.
  - Use memory for decisions, corrections, recurring mistakes, and behavior updates.
  - Do not store noisy task transcripts or duplicate information already present elsewhere.

### When to Create or Update Skills

Create or update a skill when one or more of these are true:

- The same task pattern appears more than once.
- The task requires a checklist, sequence, or validation procedure.
- The task depends on project-specific conventions not obvious from code.
- A previous mistake would likely recur without written guidance.
- A workflow requires specific commands, paths, canaries, test data, or expected outputs.
- The user explicitly asks for reusable agent guidance.

Before creating a new skill, check existing files under `.agents/skills/` and update the closest existing skill when appropriate.

A skill should include:

1. Purpose
2. When to use it
3. Inputs needed
4. Step-by-step workflow
5. Commands to run, if any
6. Expected output
7. Validation steps
8. Common mistakes or failure modes
9. Related files, playbooks, tools, or memory entries

Keep skills concise. Move long examples, references, or schemas into adjacent files instead of bloating the main skill document.

### When to Create or Update Tools

Create or update a tool when:

- The same shell/Python/Node command sequence is repeated.
- Manual execution is risky or easy to get wrong.
- The task needs parsing, validation, formatting, or comparison.
- A script would reduce ambiguity or prevent future mistakes.
- The tool can be tested cheaply.

Do not create a tool when:

- A simple documented command is enough.
- The logic is one-off.
- The tool would hide important behavior from the user.
- The tool requires new dependencies without clear benefit.

Each tool must include:

1. A clear name and purpose
2. Usage instructions
3. Safe defaults
4. Input validation
5. Helpful error messages
6. A test or example invocation
7. Documentation in the relevant skill or playbook

Prefer existing project languages and tooling. Do not introduce new runtimes or package managers unless explicitly justified.

### Self-Improvement Loop

At the end of each substantial task, Agent should briefly evaluate:

1. Did this task reveal a reusable workflow?
2. Did this task expose a recurring mistake or outdated instruction?
3. Did this task require commands or checks that should become a tool?
4. Did existing agent guidance conflict with reality?
5. Would future Agent runs benefit from a small update?

If yes, update the smallest appropriate file:

- `.agents/memory/changelog.md` for request/action history
- `.agents/memory/decisions.md` for durable decisions
- `.agents/memory/corrections.md` for mistakes, outdated assumptions, or lessons
- `.agents/skills/` for reusable workflows
- `.agents/playbooks/` for specific procedures
- `.agents/capabilities/` for stable environment, safety, or coding standards
- `AGENTS.md` only for global rules that affect all Agent behavior

Do not rewrite broad guidance for a narrow lesson. Prefer local, specific updates.

### Review Requirements for Agent Guidance Changes

When Agent changes `.agents/`, include in the final response:

- What guidance changed
- Why it changed
- Which future task it improves
- Any commands or validations run

For non-trivial changes, show the relevant diff summary.

Agent must not silently change its own operating rules. Self-improvement must be visible, reviewable, and tied to the user’s task.