# Result Contract

The enforced machine-readable contract is `codexteam/schemas/result.json`. Validation is implemented in `codexteam_tools.contracts` and exposed through `scripts/verify-result.py`.

Required fields:

- `schema_version`, `result_id`, `team_id`, `task_id`, `agent_role`, `attempt_id`
- `status`, `summary`, `output`
- `file_changes`, `evidence`, `requested_followups`
- `errors`, `warnings`, `limitations`, `produced_at`

Completed and review-ready results require evidence. Paths must be relative and safe. Timestamps must be UTC. Copied example/template content is invalid.

Object shapes:

```json
{
  "output": {
    "exit_code": 0,
    "stdout_tail": "",
    "stderr_tail": "",
    "duration_seconds": 0
  },
  "file_changes": [
    {"path": "docs/DELIVERY.md", "action": "modified"}
  ],
  "evidence": [
    {
      "type": "artifact",
      "artifact_ref": "results/t005-delivery-audit.txt",
      "summary": "The delivery audit matches verified artifacts and limitations.",
      "metadata": {}
    }
  ]
}
```

Use actual task paths and observations. Use `[]` when there are no file changes; completed results still require at least one real evidence object. Valid file actions are `created`, `modified`, and `deleted`. Valid evidence types are `test_output`, `artifact`, `file_manifest`, `cli_invocation`, `spec_compliance`, and `code_review`.

Workers persist results under `<project>/results/<TASK_ID>-<timestamp>.json`. A valid completed result remains an untrusted claim until the leader runs independent verification and closes the task.
