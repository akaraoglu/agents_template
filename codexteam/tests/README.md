# CodexTeam Tests

The suite covers deterministic workflow behavior without starting Ollama or Codex:

- path and symlink containment
- handoff and result contract validation
- task-ledger updates
- complete project initialization
- subagent subprocess result extraction and failure envelopes
- independent task closure and delivery
- command and documentation integrity

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 ../env-python/bin/python -m pytest -q tests
```

Live local-model canaries run only after this suite passes and require explicit operator approval.
