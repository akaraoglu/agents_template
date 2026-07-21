# Handoff Contract V1

The enforced machine-readable contract is `codexteam/schemas/handoff-v1.json`. The spawn adapter constructs and validates this handoff before embedding it in the worker prompt.

Required fields:

- `schema_version`: `1.0`
- `handoff_id`
- `team_id`
- `task_id`: uppercase `T` plus 3-6 digits
- `attempt_id`
- `agent_role`
- `model_profile`
- `workspace_root`
- `task_context`
- `constraints`
- `completion_criteria`

The handoff must include enough context, allowed paths, outputs, verification, evidence, and stop conditions for a worker to execute without hidden chat history.
