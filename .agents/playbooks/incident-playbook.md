# Incident Playbook

## Goal

Reduce active impact safely, preserve evidence, communicate facts, and leave a
verified recovery path.

## Preconditions

- An active or recent degraded condition is observed.
- The agent's operational authority and escalation contact are known.
- Evidence access does not require exposing credentials or sensitive data.

## Steps

1. Confirm symptom, start time, impact, affected users or systems, and current
   severity.
2. Establish an incident record or concise status channel using the project's
   process. Separate confirmed facts from hypotheses.
3. Preserve relevant logs, metrics, traces, configuration, deployments, and
   timestamps without collecting unnecessary sensitive content.
4. Prioritize the safest bounded mitigation over cleanup or optimization.
5. Before changing production, confirm exact authorization, target, expected
   effect, rollback procedure, and monitoring signal.
6. Apply one controlled mitigation or fix at a time and observe its effect.
7. Verify recovery through user-visible checks and monitoring, not only command
   success.
8. Continue monitoring for recurrence and side effects for a proportional period.
9. Record the timeline, root cause status, unresolved risk, recovery actions, and
   follow-up owners.

## Verification

- Impact is reduced or eliminated according to objective signals.
- The system is stable enough for the declared status.
- Evidence and exact actions are preserved for later review.
- Stakeholders receive concise updates when state materially changes.

## Recovery

- Roll back only with explicit operational authority and a repository-approved
  procedure.
- Confirm rollback artifacts and compatibility before relying on them.
- Preserve unrelated changes and evidence during recovery.
- If safe mitigation is not authorized or available, escalate with concrete
  impact, evidence, and the decision required.

## Related Guidance

- `.agents/skills/debugging/SKILL.md`
- `.agents/skills/releases/SKILL.md`
- `.agents/capabilities/boundaries.md`
