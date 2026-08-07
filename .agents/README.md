# Repository Agent Guidance

This folder contains provider-neutral working guidance for coding agents in
this repository.

## Layout

- `capabilities/`: stable boundaries, tool usage, and coding standards
- `skills/`: reusable engineering workflows and language-specific guidance
- `playbooks/`: narrow task recipes for features, bug fixes, and incidents
- `templates/`: reusable formats for reviews, PRs, triage, and reports
- `memory/`: concise durable decisions, corrections, and change history
- `scripts/`: deterministic helpers for repeated agent workflows

Read only the guidance relevant to the current task. More specific repository
instructions override general guidance when they do not conflict with higher
priority system, platform, or user instructions.

## Boundaries

- Guidance does not grant authorization to edit every readable file.
- Keep application behavior and project runtime configuration outside this
  folder unless they explicitly govern agent work.
- Keep provider-specific procedures clearly named and use them only for their
  stated provider or tool.
- Do not store credentials, local model catalogs, machine-specific settings, or
  generated environment files here.

## Maintenance

- Update guidance only when the task permits it and the lesson is durable.
- Prefer the smallest document that captures the rule.
- Keep entries concise, actionable, and supported by repository evidence.
- Report guidance changes explicitly in the final response.
