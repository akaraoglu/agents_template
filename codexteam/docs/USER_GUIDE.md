# CodexTeam User Guide

## 0. Start a Fresh Project Lead

Start Codex in `/home/alik/workspace/agent_template/codexteam`. Root `AGENTS.md` assigns the Project Lead role for the first proposal and routes approved initialization through `.agents/LEAD_BOOT.md`; the operator does not need to repeat the orchestration protocol.

When cloud use is acceptable, prefer `gpt54-mini` at medium reasoning for this root Project Lead. Before launching a local worker, check the Ollama endpoint from the same execution surface. A reachable nested route can use the documented `--trust-parent-sandbox` option; if the parent cannot reach host Ollama, use an approved host-level launch without the flag so the worker keeps its normal sandbox. MCP is not required.

For a new project, the lead first clarifies material requirements and presents the project description and management plan. Initialization requires approval, and later worker execution requires a separate explicit authorization such as `GO`.

## 1. Initialize Structure

Preview first:

```bash
./scripts/init-project.py "Example" \
  --goal "Deliver a verified example." --projects-root ./projects --dry-run --json
```

Run again without `--dry-run` only after approval. Use `--project-id` when a stable directory name is required. Initialization creates canonical files and task scaffolding; it does not authorize implementation or worker spawning.

Copy the initializer's exact project ID and absolute `Created:` path into all later commands. Do not reconstruct a generated path from memory. Confirm `PROJECT.md` and the selected task handoff exist there before starting a worker.

## 2. Specify, Plan, and Approve

Update `PROJECT.md` with the approved aim, scope, description, and observable acceptance criteria. Then prepare project-specific milestones, architecture, implementation plan, and responsible-AI tasks. Replace generic scaffold wording. Do not begin worker execution until the operator approves the plan.

After that approval, “handle it yourself” or “end to end” means the Project Lead should coordinate the assigned team without routine operator questions. It does not mean the lead should silently perform every role; solo execution requires an explicit instruction not to spawn agents.

## 3. Start a Worker Draft

```bash
./.agents/scripts/spawn-subagent.sh \
  --phase draft --profile qwen36-27b --team example --task T002 --attempt att-001 \
  --role developer --workspace <project-root> \
  --prompt-file <project-root>/management/tasks/T002.md
```

Use `--dry-run` to inspect the exact command, profile, guidance, session path, and final result path without starting Codex. The draft is conversational output and does not create a result.

Run `curl -fsS http://127.0.0.1:11434/api/version` from the same execution surface before the live draft. If it succeeds inside the already-sandboxed Project Lead, use a local profile and add `--trust-parent-sandbox` to draft, feedback, and final. If it fails there but succeeds on the host, use the approved host-level launcher on every turn and omit the flag. A successful `--dry-run` does not test model connectivity. See `.agents/playbooks/nested-worker-sandbox.md` for the app-server, `bwrap`, and endpoint failure routes.

Prefer `--prompt-file` for handoffs and feedback. Markdown backticks, dollar signs, and shell metacharacters inside an inline `--prompt` can be interpreted by the calling shell before Codex receives them.

## 4. Review and Continue the Same Session

The Project Lead inspects the draft and sends one consolidated decision. Use `--phase feedback` for corrections and `--phase final` only after acceptance. Keep the same team, task, attempt, role, profile, and workspace arguments. The launcher resumes the exact stored thread ID and never relies on the most recent global session.

Ordinary corrections do not create new attempts. Start a new attempt only after irrecoverable session loss, intentional reassignment, material scope change, or explicit abandonment.

If a turn fails or returns no final message, inspect the printed diagnostics path and the adjacent JSONL file. Resume the same attempt when its exact thread ID was captured. If repeated focused feedback demonstrates a real capability mismatch, record an intentional owner/profile transfer and continue in a new attempt; the abandoned attempt must remain result-free unless the Project Lead deliberately finalizes it as terminal.

## 5. Validate the Final Result

```bash
./scripts/verify-result.py \
  <project-root>/results/T002-att-001.json \
  --task T002 --team example --attempt att-001 --role developer \
  --expected-status completed
```

Validation does not prove the work is correct. It proves the result envelope is usable.

## 6. Close the Task

```bash
./scripts/close-loop.sh <project-root> --task T002 -- \
  python3 -m pytest -q
```

The command validates artifacts, runs verification without a shell, records output under `results/`, updates project state, and advances to the next incomplete task. Repeating the same successful close is idempotent.

## 7. Deliver

When the final planned task closes, CodexTeam writes `DELIVERY.md`, updates `DONE_REPORT.md`, and sets project status to `DELIVERED`.

After each closure, the Project Lead must also synchronize `BRIEF.md`, milestone checkboxes, and implementation-plan status. The closure command owns canonical task state, but it does not infer project-specific narrative updates.
