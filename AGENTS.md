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

## Durable Discovery Notes

Substantial discovery or deep research may produce findings that future agents
should reuse instead of repeating the same investigation. Persist those findings
only when they are durable, evidence-backed, and materially useful beyond the
current conversation.

- First identify the exact active project root. A repository may contain several
  projects, so the current working directory or repository root is not sufficient
  proof of the active project.
- If the active project or its root path is unclear, ask the user before creating
  a discovery note. Do not guess a destination.
- Write discovery notes only under
  `<active-project-root>/design/architecture/` using
  `YYYY-MM-DD_descriptive_title.md`.
- In split-root work, the active project root for discovery notes is always the
  control root under `codexspace/projects`, never the source work root.
- Before substantial source investigation, search existing control-root
  discovery notes with task-specific terms. Inspect relevant matches first,
  verify important claims against current source, and record no relevant match
  when none exists.
- Use one coherent subject per note. Include the research scope, decision-bearing
  evidence and source locations, findings, implications, and unresolved risks or
  follow-up questions.
- Prefer updating an existing note when the same subject has materially evolved;
  create a new note for a distinct finding or investigation.
- Do not create notes for routine file inspection, transient debugging output,
  speculative ideas, or information already captured accurately in project
  documentation.
- A request for deep research or substantial project analysis authorizes a
  relevant discovery note unless the user explicitly requests read-only work or
  no file changes. Explicit read-only instructions always win.
- Never save one project's findings in a parent toolkit, another project, or a
  shared repository folder merely because that location is convenient.
- Discovery notes are advisory research. Promote accepted product truth through
  a separate source task into source-owned architecture or documentation; do not
  maintain a competing product specification in control.

## Control And Source Ownership

- Control roots under `/home/alik/workspace/codexspace/projects` own tasks,
  handoffs, project state, runtime, results, gate configuration, discoveries,
  control/program architecture, and project-specific agent guidance.
- Source repositories under `/home/alik/workspace/codexspace/repos` or explicit
  external bindings own product source, product tests, build configuration,
  product architecture/ADRs, and user/developer/operator documentation.
- Split-root controls must not contain product `src/` or product test trees.
  Source repositories must not contain CodexTeam lifecycle, runtime, result, or
  task-board artifacts.
- One source task targets one registered repository and one source Git history.

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
- `source-grounded-development/` covers version-sensitive external technical
  evidence and untrusted fetched content.
- `security-threat-modeling/` covers change-scoped assets, boundaries, threats,
  abuse cases, and controls.
- `observability/` covers question-driven structured telemetry and bounded
  cardinality.
- `performance/` covers controlled, variance-aware performance experiments.
- `browser-verification/` covers isolated local browser checks and cleanup.
- `frontend-engineering/` covers semantic, responsive, accessible user interfaces
  and design-system use.
- `migration-deprecation/` covers staged state migration and usage-gated removal.
- `api-interface-design/` covers cross-boundary contracts, compatibility, errors,
  idempotency, and unknown outcomes.
- `git-delivery/` covers commits, pushes, branches, and pull requests.
- `releases/` covers release preparation, publication, and deployment.

Use `.agents/playbooks/` for narrower task recipes and `.agents/capabilities/`
for stable safety, tooling, and coding standards. Provider-specific playbooks
apply only when their named platform or tool is part of the task.

## Core Rules

- Implement the user's stated request directly and minimally. Do not add
  speculative features, abstractions, wrappers, compatibility layers, files, or
  adjacent cleanup that the requested outcome does not require.
- Prefer modifying existing files, functions, and repository patterns over
  introducing new structure. Every changed file must have a clear, necessary
  connection to the accepted scope.
- Do not reinterpret a narrow request as permission for a redesign. If the
  correct solution requires materially broader changes, stop and agree on a
  plan with the user before implementation.
- Before creating multiple files, splitting components, renaming public
  interfaces, or changing the planned file set, explain why it is necessary and
  obtain explicit user approval. A single unavoidable generated or conventional
  companion file may be created only when the repository workflow requires it.
- When new information invalidates the agreed plan, report the conflict and ask
  for direction rather than improvising a different design.
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

## Execution Discipline

- Plans include only requested, necessary work.
- Implementation includes only required code.
- No nice-to-have features unless requested.
- No speculative abstractions or adjacent cleanup.
- Plans and responses stay concise and direct.
- Optional improvements are mentioned only after required work, with your permission.

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

Before creating a skill, check for an existing workflow to extend. Give each
skill a narrow positive trigger and important non-triggers so it is loaded only
when relevant. A skill should define:

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
Use explicit anti-rationalization rules only for high-risk workflows that agents
commonly skip on weak grounds; do not add generic anti-skip boilerplate.
