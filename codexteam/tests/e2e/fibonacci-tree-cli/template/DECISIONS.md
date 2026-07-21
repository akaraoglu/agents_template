# Decisions

## D001 - Product Shape

- Status: Accepted
- Decision: Deliver one standard-library Python module, one unittest module, and one README.
- Rationale: The small product remains easy to inspect while exercising implementation, testing, review, and documentation roles.

## D002 - Conversation Shape

- Status: Accepted
- Decision: Use one draft and one final turn in the same persistent attempt for each task.
- Rationale: Ten deterministic turns prove session continuity without automatic remediation hiding failures.

## D003 - Failure Handling

- Status: Accepted
- Decision: Stop at the first failure, preserve the workspace and session, and print exact same-session recovery guidance.
- Rationale: Failures remain inspectable and ownership does not silently change.
