# Repository Agent Guidance

These instructions apply to any coding agent working in this repository. Follow
system, platform, and user instructions first; then apply the most specific
repository guidance available for the files being changed.

## Before Work

1. Determine the task mode: analysis, planning, implementation, review, or
   delivery. Do not turn a read-only request into an editing task.
2. Inspect relevant repository guidance, including more specific `AGENTS.md`
   files, before substantial work.
3. Inspect the affected code, tests, configuration, and repository-native
   commands before proposing or making changes.
4. Identify acceptance criteria, non-goals, affected interfaces, and material
   risks. Ask a targeted question only when unresolved ambiguity would
   materially change the result.
5. Treat filesystem access as capability, not authorization. Modify only files
   relevant to the user's request.

## Engineering Lifecycle

Use the smallest relevant workflow under `.agents/skills/`:

- `engineering-workflow/` routes substantial coding tasks through discovery,
  design, implementation, verification, and review.
- `discovery-scoping/` establishes task mode, repository context, authorized
  scope, and acceptance criteria.
- `planning-design/` covers implementation planning and software design.
- `implementation/` covers safe, scoped code changes.
- `verification/` covers tests and risk-based quality gates.
- `testing/` covers test design, test layers, fixtures, and assertion quality.
- `code-review/` covers read-only review and implementation self-review.
- `debugging/` covers diagnosis and root-cause analysis.
- `refactoring/` covers behavior-preserving structural changes.
- `python/` adds Python-specific implementation and testing guidance.
- `git-delivery/` covers commits, pushes, branches, and pull requests.
- `releases/` covers release preparation, publication, and deployment.

Use `.agents/playbooks/` for narrower task recipes and `.agents/capabilities/`
for stable safety, tooling, and coding standards. Provider-specific playbooks
apply only when their named platform or tool is part of the task.

## Core Rules

- Prefer the smallest coherent change that fully satisfies the request.
- Preserve existing behavior unless the request intentionally changes it.
- Follow established repository patterns before introducing new abstractions,
  dependencies, or tools.
- Never overwrite, discard, stage, or revert unrelated user changes.
- Behavior changes and bug fixes normally require practical regression
  coverage. Explain when suitable automated coverage is unavailable.
- Run the smallest relevant checks first, then broaden verification according
  to risk and repository requirements.
- Inspect the final diff for unintended changes before reporting completion.
- Report commands actually run, observed results, skipped checks, and residual
  risks. Do not claim verification that was not performed.
- Commit, push, open or merge pull requests, tag, publish, or deploy only when
  explicitly requested or already authorized by the task.

## Guidance Layout

- `.agents/capabilities/`: stable boundaries, coding standards, and tool rules
- `.agents/skills/`: reusable workflows and language-specific guidance
- `.agents/playbooks/`: narrow implementation, debugging, and operations recipes
- `.agents/templates/`: reusable review, triage, PR, and report formats
- `.agents/memory/`: concise durable decisions, corrections, and change history
- `.agents/scripts/`: documented deterministic workflow helpers

Guidance files describe how to work; they are not application source. Keep
project runtime behavior and machine-specific configuration elsewhere unless
the task is specifically about agent guidance.

## Maintaining Guidance

At the end of a substantial task, consider whether it exposed a durable,
repeatable improvement. Update guidance only when all of these are true:

- The current task permits edits to agent guidance.
- The improvement is specific, reusable, and supported by observed evidence.
- The change belongs in the smallest relevant guidance file.
- It does not duplicate source code, generated configuration, or scoped
  subsystem guidance.

For read-only, review, or planning tasks, report a recommended guidance change
instead of editing files. Do not silently alter operating rules.

When guidance changes, the final response must state what changed, why, which
future tasks it improves, and what validation was performed. Include a diff
summary for non-trivial changes.

## Skill Authoring

Before creating a skill, check for an existing workflow to extend. A skill
should define:

1. Purpose and trigger
2. Inputs and prerequisites
3. Workflow
4. Expected output
5. Validation
6. Failure modes or cautions
7. Related guidance

Keep the main `SKILL.md` concise. Put language details, long examples, or stable
reference material in a skill's `references/` directory. Add a helper tool only
when a repeated, error-prone process benefits from deterministic execution;
document safe defaults, validation, errors, and a test or example invocation.
