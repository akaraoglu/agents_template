---
name: security-threat-modeling
description: Perform lightweight, change-scoped security and abuse analysis. Use for authentication, authorization, sensitive data, trust-boundary, externally reachable, parser, upload, execution, privilege, or security-control changes; not for routine edits without a plausible security boundary.
---

# Security and Threat Modeling

## Purpose

Identify credible threats and proportionate controls before a security-relevant
change ships, without requiring a heavyweight system-wide model.

## Trigger

Use when a change introduces or alters valuable assets, trust boundaries,
attacker-controlled input, privileges, security controls, or abuse-sensitive
workflows.

## Inputs

- Change scope, actors, deployment context, and existing controls
- Assets and sensitive operations affected
- Data flows, entry points, trust boundaries, and external dependencies

## Workflow

1. Bound the model to the change and adjacent paths an attacker can reach.
2. List assets, actors, entry points, data flows, trust boundaries, and privileges.
3. Describe credible threats and abuse cases as actor, capability, action, asset,
   and impact; include misuse by legitimate but unauthorized or automated users.
4. Rank scenarios by plausible impact and likelihood rather than producing an
   exhaustive taxonomy.
5. Map material scenarios to prevention, detection, rate or resource limits,
   safe failure behavior, and recovery. Keep authorization server-side and
   validation at the relevant boundary.
6. Add focused negative tests and verify logs or errors do not expose secrets or
   sensitive data.
7. Record accepted residual risks, assumptions, and owners when controls remain.

## Expected Output

A concise change-scoped threat model and implementation or review evidence for
the material controls.

## Validation

- Every identified asset crosses only explicit, controlled trust boundaries.
- High-impact abuse cases have a control, test, or documented residual risk.
- Authentication, authorization, validation, failure, and audit behavior are
  independently considered where applicable.

## Cautions

- Do not skip analysis because a feature is internal, low traffic, behind a UI,
  or protected by authentication; establish whether those facts remove the
  attacker path.
- Do not claim safety from validation alone when authorization, resource abuse,
  dependency compromise, or sensitive output remains possible.
- Do not include exploit details or sensitive architecture beyond what the task
  and destination require.

## Related Guidance

- `.agents/skills/planning-design/SKILL.md`
- `.agents/skills/testing/SKILL.md`
- `.agents/skills/code-review/SKILL.md`
- `.agents/capabilities/boundaries.md`
