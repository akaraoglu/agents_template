# CodexTeam Foundation v2

Foundation v2 is an experimental backend-neutral stage runner with a
deterministic fake adapter and one active live backend: OpenCode `1.18.16` using
`ollama/muse-glimmer:30b` through Ollama `0.32.9` or newer. Ollama `0.32.9`
fixes the Muse Glimmer function-call boundary parser failure observed with
`0.32.8`. All seven AgentSpecs use Muse Glimmer exclusively.
The Qwen and Codex profiles remain defined as inactive historical baselines.

Run from the repository root with the pinned Python:

```bash
PYTHONPATH=src /home/alik/workspace/agent_template/env-python/bin/python scripts/v2/codexteam.py catalog-check
PYTHONPATH=src /home/alik/workspace/agent_template/env-python/bin/python scripts/v2/codexteam.py compile --optional architecture,ux
PYTHONPATH=src /home/alik/workspace/agent_template/env-python/bin/python scripts/v2/codexteam.py canary --fake --scenario happy --json
PYTHONPATH=src /home/alik/workspace/agent_template/env-python/bin/python scripts/v2/codexteam.py canary --live-opencode --workspace /absolute/empty/path --dry-run --json
./scripts/v2/codexteam.py qualify-muse --opencode --dry-run --workspace /absolute/empty/path --json
```

The live command without `--dry-run` invokes the local model and is intentionally
left for the parent operator. Live workspaces must be absent or empty. Dry run
uses an internal temporary fixture, preflights read-only Discovery and writable
Developer roles, checks OpenCode/config/Ollama/systemd without a model call,
removes the fixture, and does not create the requested workspace.

OpenCode writer roles have normal edit/write freedom inside the disposable
product cwd. Architecture owns `docs/architecture/**`, UX owns `docs/design/**`,
Developer owns `src/**` and `tests/**`, and Test owns `tests/**`; those exact
compiled paths are carried in the prompt and immediately enforced by
StageRunner's authoritative post-turn audit. Root manifests and configuration
are outside those assignments. Model bash is denied in the first canary. The
parent needs localhost Ollama. OpenCode permissions deny external directories
and integrations, candidate reporting is read-only, and kernel
`VerificationExecutor` runs acceptance tests.
See `BACKENDS.md` for the exact trust boundary and session protocol.

Candidate criterion dispositions are stage-specific. Discovery, architecture,
UX, assurance, and review report `not_evaluated`; implementation reports
`claimed_satisfied` with producer artifact evidence; verification is replaced
with a receipt-backed `verified` candidate only after an accepted independent
receipt. Work-item required evidence types are authoritative at verification,
not forced onto every producer stage.

Assurance receives bounded canonical summaries of the implementation candidate,
current work item and pipeline revision, and accepted verification receipt.
Review receives the same inputs plus the assurance report. Adaptive execution
walks stage dependencies, so architecture and UX may be omitted independently.

## Current Acceptance Status

Foundation contracts and deterministic execution are green: the active v2 suite
passes, and both fake happy-path and same-session defect-loop canaries seal and
close. Historical OpenCode/Qwen experiments proved read-only Discovery, typed adaptive
revision requests, immediate forbidden-change detection, exact sessions, and
scope communication. They did not complete the full pipeline: Qwen sometimes
returned no final text after tool use, and OpenCode's path-pattern write policy
was not reliable for creating absent nested files. The final adapter therefore
uses practical product-cwd edit/write access with authoritative StageRunner
scope auditing, but no further live retries were performed in this task.

Foundation v2 remains experimental and deterministic/fake-proven, not yet
live-model accepted. Muse qualification passed all metadata, direct
text/JSON/reasoning/tool, and minimal OpenCode checks without retries or
fallback. The first post-qualification adaptive canary reached Verification but
failed closed because the Test candidate selected evidence types allowed by the
generated broad enum but rejected by the stage-specific runtime contract. The
schema now exposes only stage-valid evidence types. A later benchmark completed
Verification with a clean product and accepted receipt, then failed at Assurance
when Ollama `0.32.8` could not parse Muse's malformed `read` function boundary.
Ollama `0.32.9` contains the exact upstream parser fix. No automatic live retry
was made. Post-upgrade qualification passed all nine checks, but the next fresh
canary failed closed at the read-only Architecture candidate because Muse
returned malformed JSON despite the correct stage-specific schema. See
`MUSE_QUALIFICATION.md` and `E2E_ACCEPTANCE_PLAN.md`.
