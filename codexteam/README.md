# CodexTeam

CodexTeam is a local workflow toolkit for coordinating bounded Codex subagents around a specification-driven software project. It provides project guidance, task handoffs, strict result contracts, safe local-model spawning, independent verification, and deterministic project-state closure.

It is not an application server, controller service, board, HTTP API, or MCP implementation. Historical archives are not source inputs for this system.

## Workflow

1. Clarify the goal and initialize a complete project workspace.
2. Approve the project specification before implementation.
3. Assign each task to one responsible AI and start a persistent draft session.
4. Review the draft and return consolidated feedback in the same session and attempt.
5. Accept the draft and persist one final result using result contract v1.
6. Verify worker output independently.
7. Close the task and advance project state only after verification passes.

## Runtime

The cold-start Project Lead creates projects under:

```text
./projects/<project-id>/
```

The guaranteed Project Lead base folder is `/home/alik/workspace/agent_template/codexteam`. Start a fresh Codex session there; root `AGENTS.md` establishes the lead role immediately and routes approved initialization through `.agents/LEAD_BOOT.md`.

## Fresh Codex Startup

When the operator asks for a new project, the root agent acts as Project Lead. It clarifies material requirements, proposes the project description and management plan, waits for initialization approval, creates structure under `./projects`, prepares project-specific milestones and responsible-AI tasks, and waits for `GO` before spawning workers.

The operator should not need to restate the orchestration protocol. See `.agents/LEAD_BOOT.md` for the one-page cold-start contract.

After initialization, the lead carries the exact `Created:` path forward instead of retyping a generated directory name. An instruction such as “handle it yourself end to end” tells the lead to manage the team autonomously; it does not collapse responsible-AI roles into solo lead work. Only an explicit “do not spawn agents” instruction selects solo execution.

For a cloud-enabled cold start, `gpt54-mini` at medium reasoning is the recommended Project Lead. Before it starts a local subprocess worker, it checks whether the same execution surface can reach host Ollama. A reachable nested route may use `--trust-parent-sandbox`; an isolated route launches at the approved host level without that flag and retains the worker's normal sandbox. MCP is not required for either route.

## Model Profiles

- `qwen36-27b`: default for implementation, testing, review, and documentation
- `gemma4-26b`: optional bounded secondary perspective when its task-specific capability has been confirmed
- `gpt54-mini`: controlled cloud canary profile; E2E runner examples explicitly override it to medium reasoning

Profiles must exist under `$CODEX_HOME` or `~/.codex` before a subagent is started.

## Commands

Initialize a project without writing:

```bash
./scripts/init-project.py "Example Project" \
  --goal "Deliver a verified example." --projects-root ./projects --dry-run
```

Start a developer draft:

```bash
./.agents/scripts/spawn-subagent.sh \
  --phase draft --profile qwen36-27b --team example --task T002 --attempt att-001 \
  --role developer --workspace ./projects/example \
  --prompt-file ./projects/example/management/tasks/T002.md
```

Review the draft, then continue the exact session with `--phase feedback`. After acceptance, use `--phase final` with the same team, task, attempt, role, profile, and workspace. Draft and feedback may edit handoff-scoped project files, but they never write the deterministic result; finalization writes that one result after acceptance.

Validate its result:

```bash
./scripts/verify-result.py \
  ./projects/example/results/T002-att-001.json \
  --task T002 --team example --attempt att-001 --role developer \
  --expected-status completed
```

Close the task after independent verification:

```bash
./scripts/close-loop.sh ./projects/example \
  --task T002 -- python3 -m pytest -q
```

## Validation

```bash
PYTHONDONTWRITEBYTECODE=1 ../env-python/bin/python -m pytest -q tests
```

## Read-only WebUI

Start the local status UI with:

```bash
../env-python/bin/python scripts/run-webui.py
```

Open `http://127.0.0.1:5000`. The Flask/Jinja UI reads `./projects` on every request and provides an activity-sorted project dashboard plus expandable project, agent, task, attempt, and turn details. Its theme menu defaults to the operating-system theme and remembers an explicit Light or Dark choice in the browser. It exposes GET views only and cannot start workers, retry tasks, edit project state, or modify Git.

Preview the controlled end-to-end team canary with:

```bash
./scripts/run-e2e-fibonacci-test.sh --dry-run \
  --profile gpt54-mini --reasoning-effort medium
```

See `scripts/TOOLS-README.md` for live-run budgeting, reports, product-only verification, and same-session failure recovery. The cold-start-through-team acceptance definition, including product-audit and proportional-performance gates, is in `docs/E2E_ACCEPTANCE_PLAN.md`.

Start with `docs/USER_GUIDE.md`, `.agents/skills/project-lead.md`, and `.agents/skills/subagent-orchestration.md`.
