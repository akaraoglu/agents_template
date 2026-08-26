# CodexTeam Architecture Review

## Status

The current architecture is a small workflow-tool package plus repository-local agent guidance.

## Components

- `.agents/`: reusable leader, worker, verification, and delivery guidance.
- `roles/`: strict role-policy manifests for nine accountable identities, including the optional Feature Planner and UX Designer.
- `generated/native-agents/`: deterministic optional projections for native Codex custom agents.
- `src/codexteam_tools/`: deterministic path, contract, task, spawn, gate, Git boundary, artifact-reader, and closure logic.
- `/home/alik/workspace/codexspace/repos/codexteam-project-management-web-ui`:
  standalone Flask/Jinja operator UI consuming the shared artifact readers and
  controls under `/home/alik/workspace/codexspace/projects`.
- `scripts/`: operator-facing compatibility entrypoints.
- `schemas/`: machine-readable handoff, result, role-policy, gate, commit-plan, authorization, and commit-record contracts.
- `templates/project/`: complete project initialization template.
- `tests/`: model-free unit, integration, and security validation.

## Boundaries

- Control projects are isolated under `/home/alik/workspace/codexspace/projects`
  by default; product source uses registered work roots.
- Workers may write only inside the assigned workspace and explicit additional roots.
- A worker receives common `AGENTS.md` guidance plus one selected role policy; the draft pins the policy snapshot for every continuation.
- Post-turn workspace comparison rejects changes outside the role boundary. Handoff-specific scope remains an assignment and review constraint within the broader mechanical role boundary.
- Developer and Test Engineer ownership is split by test gate. Developers own algorithm/unit and smoke evidence; Test Engineers use the wire-compatible tester role and own handoff-scoped integration/regression expectations plus the CI-equivalent gate without production writes.
- Architects own requirement-traceable system and repository design but neither implementation nor self-approval. The optional Feature Planner turns accepted design into advisory implementation subtasks under `results/` without canonical task or lifecycle authority. The optional UX Designer owns interface design artifacts and design QA without production writes or self-approval. Local Git Steward model turns are read-only and run only at named boundaries.
- Worker results are untrusted until schema validation and independent verification pass.
- Shell text is never evaluated. Verification and Codex commands use structured argument arrays.
- The leader owns state closure; a worker result cannot update task or delivery state directly.

## Role Policy Precedence

The Lead explicitly selects Role, optional AgentSpec, backend-scoped profile,
and reasoning. RolePolicy supplies responsibility and permission ceilings only;
the curated execution registry resolves runtime material and ExecutionSpec pins it.

The external persistent-session launcher is the authoritative execution mechanism. Native-agent files are generated from the same manifest for optional Codex multi-agent use; they are namespaced and installed only by an explicit operator command.

## Verification Pipeline

T001 configures both shell-free command arrays in `management/TEST_GATES.toml`. T002 produces accepted architecture before T003 implementation. A Developer draft must pass the Development Gate before T004 Test Engineer work. The Test Engineer may begin against that draft, return classified product defects to the same Developer session, and rerun affected checks plus the Integration Gate after correction. T005 Reviewer audits architecture conformance, source changes, test changes, expectation justification, both gate artifacts, and evidence claims. External CI and leader closure invoke the Integration Gate or an exact wrapper so acceptance commands cannot drift.

## Git Boundary

New projects are standalone Git repositories. The Project Lead names important-task or milestone boundaries. Git Steward inspection and plan generation are read-only; explicit authorization pins branch, HEAD, evidence, task IDs, path set, and plan digest. The deterministic executor builds the candidate tree, runs Integration Gate against an isolated worktree, stages only approved paths, and creates exactly one local commit. It does not expose remote operations.

## Known External Dependencies

- Python 3.12+
- Bash for thin compatibility wrappers
- Codex CLI for live subagent execution
- Curated backend/model material listed by `inspect-execution-catalog.py`

No live model is required for deterministic tests.
