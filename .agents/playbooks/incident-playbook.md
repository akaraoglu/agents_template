# Incident Playbook

## Goal
Stabilize a production or operational problem and leave a clear trail of facts.

## Preconditions
- An active issue or degraded condition has been observed
- The current impact is understood well enough to prioritize action

## Steps
1. Confirm the symptom, impact, and affected surface area.
2. Prioritize mitigation before cleanup or optimization.
3. Capture concrete facts: logs, timestamps, triggers, and failed checks.
4. Apply the safest available mitigation or fix.
5. Verify the system has returned to an acceptable state.
6. Record follow-up actions and lessons learned.

## Verification
- The immediate impact is reduced or eliminated
- Monitoring, checks, or reproductions show recovery
- Stakeholders have a concise status summary

## Recovery
- Roll back to the last known safe state if the mitigation fails
- Preserve evidence needed for a post-incident review
