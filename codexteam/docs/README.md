# CodexTeam Docs

Design notes, threat models, runtime layout, policy descriptions, and operator guides belong here.

Keep generated runtime state and agent outputs in `/home/alik/workspace/codexspace`.

## Current Architecture References

- `CORE_DOMAIN_MODEL.md`: current core orchestration model for worker results, requested actions, attempts, health, workspace lifecycle, board read models, operator commands, and E2E evidence bundles.
- `E2E_ACCEPTANCE_PLAN.md`: release-grade E2E scenarios, evidence bundle requirements, consistency checks, and blockers.
- `ARCHITECTURE_REVIEW.md`: historical Phase 0 readiness review and local model findings.
- `RUNTIME_LAYOUT.md`: runtime filesystem layout.
- `SECURITY_GUIDE.md`: safety and policy guidance.
- `ADAPTER_GUIDE.md`: dry-run, manual, and local Codex/Ollama adapter guidance.
- `PUBLIC_CONTRACTS.md`: versioned board/read-model and controller command contract policy.
- `OPTIONAL_INTERFACES.md`: deferred HTTP, MCP, and app-server notes.
