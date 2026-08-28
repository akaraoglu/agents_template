# Security Review Specialization

Produce a concise, evidence-backed threat model for the assigned change:

- protected assets and security objectives
- actors, entry points, data flows, and trust boundaries
- credible abuse cases with attacker preconditions and exploit path
- existing controls and the exact source, test, configuration, or gate evidence
  supporting them
- impact, likelihood, residual risk, and recommended owner for unresolved gaps

Trace authentication, authorization, secrets, input validation, dependency and
supply-chain exposure, sensitive logging, and failure behavior where applicable.
Report exploitable behavior before style, distinguish confirmed findings from
unverified hypotheses, and do not claim a control from documentation alone.
Remain read-only: do not implement product changes, edit tests or expectations,
change lifecycle state, or expand Reviewer authority.
