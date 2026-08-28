# AgentSpec Specialization Overlays

AgentSpecs add technical specialization without creating lifecycle roles.

```text
Protocol Role = lifecycle responsibility and authority ceiling
AgentSpec = technical specialization and narrowing
Execution profile = backend, model, reasoning, and runtime settings
Task handoff = exact task authority
Execution specification = immutable resolved attempt pin
```

AgentSpecs are optional. New attempts that omit `--agent-spec` use the ordinary
RolePolicy with `agent_spec: null`. Feedback and final omit the option and reuse
the pinned selection; selecting another specialization requires a new attempt.

Initial specialists are `python-developer`, `go-developer`,
`frontend-developer`, `cpp-developer`, `cpp-embedded-developer`,
`security-reviewer`, and `accessibility-reviewer`.

AgentSpecs may declare capabilities, add catalog-owned guidance, and narrow
allowed paths, denials, MCP servers/tools, or evidence types. They cannot select
a backend, model, reasoning level, task, lifecycle stage, gate, project state,
or permission outside the base RolePolicy ceiling. Role denials always win.
Only one curated AgentSpec is selected per attempt; task-specific details remain
in the handoff and automatic routing is not supported.

The `frontend-developer` overlay is design-system-first and requires semantic,
responsive, accessible implementations with complete UI states and targeted
console/network checks. It does not add a browser framework or visual-capture
infrastructure. The `security-reviewer` overlay remains within the Reviewer's
read-only ceiling and produces an evidence-backed threat model covering assets,
actors, entry points, trust boundaries, abuse cases, controls, and residual risk;
it never repairs the product or changes lifecycle state.
