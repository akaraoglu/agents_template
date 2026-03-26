# Request and Change Log

Track template-level requests and changes only. Do not record local deployment
history, live credentials, or project-specific task transcripts here.

## Entry Template
- Date:
- Request:
- Action:
- Validation:
- Outcome:

## Entries

- Date: 2026-03-26
- Request: Write canonical template instructions so another agent can recreate the same OpenClaw, project, bridge, and Zulip setup without reverse-engineering the repository.
- Action: Added `openclaw_agents/SETUP_BLUEPRINT.md` with the full architecture, bridge split, bot rules, creation workflows, checklists, and validation sequence, and linked it from the main OpenClaw guide and README.
- Validation: Reviewed the new blueprint against the current agent creation guide, persona bridge guide, and software bridge guide to keep the described workflow aligned with the existing template structure.
- Outcome: The template now contains a single reusable instruction file that another agent can follow to recreate the same setup consistently.

- Date: 2026-03-26
- Request: Build a reusable shared multi-bot persona bridge for DM-capable discussion personas such as AgentSmith, Yoda, and later Architect.
- Action: Added `openclaw_agents/persona_bridge_v1/` with a shared multi-persona bridge runtime, example config and persona registry files, private and state placeholders, an entrypoint script, and updated the OpenClaw and Zulip template docs to separate persona bridges from team bridges.
- Validation: Compile-checked the new persona bridge runtime, shell-checked the entrypoint script, and extended the template safety check coverage to include persona bridge generated artifacts and runtime residue.
- Outcome: The template now includes a reusable single-process multi-bot persona bridge for human-facing Zulip personas without mixing that layer into the team bridge architecture.

- Date: 2026-03-26
- Request: Make Oracle visibly participate in the Zulip `software` stream instead of staying hidden behind Morpheus summaries.
- Action: Patched the live software-team wrapper to emit structured role output, wired the live software bridge to load an Oracle bot client and post tester output separately, added the Oracle Zulip credential file for the software bridge, and subscribed the tester bot to the `software` stream.
- Validation: Verified the updated wrapper and bridge syntax, confirmed Oracle is subscribed to `software`, restarted the live software bridge, and observed the new software-topic flow running through the updated Morpheus bridge path.
- Outcome: Oracle is now structurally wired to speak in the `software` stream when tester output is available, though end-to-end visibility still depends on the underlying software-team run succeeding for the given topic.

- Date: 2026-03-26
- Request: Check why the live Zulip `Oracle` identity is not visible.
- Action: Inspected the live Zulip bot record, stream subscriptions, and assistant bridge configuration for the renamed tester bot.
- Validation: Verified that `tester-bot@localhost.localdomain` exists, is active, is named `Oracle`, is wired in the assistant bridge, and is subscribed to the `assistant` stream.
- Outcome: Oracle is present but only configured to speak through the assistant-side helper flow, which explains why it is not visible in ordinary software-team discussions.

- Date: 2026-03-26
- Request: Switch the live Architect agent from Qwen 3.5 to Nemotron Cascade 2 and test how it behaves in the document-driven project-management role.
- Action: Updated the live OpenClaw Architect agent to use `ollama/nemotron-cascade-2:30b`, re-rendered the local config, verified the live agent registry, and ran a direct Architect smoke test against the management documents.
- Validation: Confirmed `openclaw agents list` shows Architect on Nemotron and reviewed the first direct Architect response on the new model.
- Outcome: Architect is now running on Nemotron locally, with an initial smoke-test result available for role-quality comparison.

- Date: 2026-03-26
- Request: Clarify whether AgentSmith has explicit skill instructions and add a proper skill layer for his discussion, helper spawn, handoff, and admin behavior.
- Action: Added a dedicated AgentSmith operator skill in the live claw workspace and updated the local `SKILLS.md`, `AGENTS.md`, and `README.md` pointers so his capabilities and entrypoints are explicitly documented.
- Validation: Reviewed the new `agentsmith-operator/SKILL.md` file and the updated live workspace docs after the changes.
- Outcome: AgentSmith now has a documented skill layer instead of relying only on the prompt and wrapper scripts.

- Date: 2026-03-25
- Request: Check the installed local Ollama models, identify the image-generation models, and test them with a photorealistic cat-and-sign prompt to diagnose generation failures.
- Action: Listed the local Ollama models, inspected the two installed image-model entries, checked the current official Ollama image-generation documentation, and ran the exact requested prompt against both installed local image-generation models.
- Validation: Confirmed both installed image models advertise `image` capability locally, captured the actual local failure modes for each run, checked for generated output files, and compared the observed behavior with the official Ollama image-generation support note for macOS versus Linux/Windows.
- Outcome: The local failures are consistent with Ollama's current Linux image-generation support status rather than a prompt-format issue.

- Date: 2026-03-25
- Request: Attach a new custom avatar image from the live claw workspace to the Zulip `master` user profile.
- Action: Located the copied `master` avatar image in the live project workspace, used the live Zulip API with the correct delivery-email login identifier for the owner account, uploaded the image to the `master` profile, and verified the account switched to an uploaded avatar.
- Validation: Confirmed the Zulip avatar upload API returned success, checked the live `/api/v1/users/me` response for the owner account, and verified the Zulip user record changed to `avatar_source = U` with a bumped avatar version.
- Outcome: The live Zulip `master` profile now uses the uploaded custom avatar instead of the default gravatar-generated image.

- Date: 2026-03-25
- Request: Attach a custom avatar image from the live claw workspace to the AgentSmith Zulip bot profile.
- Action: Located the copied avatar image in the live project workspace, uploaded it to the live Zulip bot profile through the Zulip avatar API, and verified the bot profile switched to a user-uploaded avatar source.
- Validation: Confirmed the upload API returned success and checked the live Zulip user record for `avatar_source = U` with an incremented avatar version.
- Outcome: The live AgentSmith bot now uses the uploaded custom avatar instead of the default generated avatar.

- Date: 2026-03-26
- Request: Create a reusable per-project template and plan the split between the shared runtime and project-specific documents for a future multi-project setup.
- Action: Added `openclaw_agents/project_template/` with reusable `PROJECT.md`, management documents, and story/task templates; added `MULTI_PROJECT_PLAN.md`; and updated the OpenClaw and Zulip docs to reference the new per-project scaffold and the shared-runtime versus per-project split.
- Validation: Reviewed the new template tree and checked the updated OpenClaw workspace and planning docs for consistency with the intended multi-project direction.
- Outcome: The repository now includes a reusable per-project scaffold and a concrete migration plan for moving project-specific state out of the shared runtime.

- Date: 2026-03-26
- Request: Design a shared multi-bot persona bridge for AgentSmith, Yoda, and later Architect, and clarify whether a separate team bridge should exist for multi-agent teams.
- Action: Recommended a split architecture with one shared persona bridge for DM-able discussion bots, one separate team bridge for manager-led execution teams, and a shared host-side control plane that lets AgentSmith create bots, update registries, reload bridges, and verify the wiring safely.
- Validation: Reasoned against the current single-bot and single-team bridge boundaries and mapped the recommendation to the existing OpenClaw, Zulip, and admin-control model.
- Outcome: The template history now captures the intended next-step architecture: discussion personas and execution teams should not share the same bridge layer.

- Date: 2026-03-26
- Request: Clarify whether AgentSmith can attach a new Zulip bot such as Yoda to an agent by using a new channel without introducing a new bridge process.
- Action: Documented the current bridge boundary: channels alone do not connect a bot account to an agent runtime, send-only persona posting can reuse an existing bridge, and true DM-able or independently listening personas still require either a dedicated bridge or a shared multi-bot bridge.
- Validation: Reviewed the current bridge architecture and the generic template bridge behavior to confirm that only the main registered bot receives inbound events while role bots are send-only.
- Outcome: The current design limitation and the recommended upgrade path are now captured in the template history.

- Date: 2026-03-26
- Request: Implement the next runtime step for a shared multi-project setup so one runtime can route work to multiple project folders cleanly.
- Action: Added a reusable project registry example and validator under `.agents/`, extended the generic software bridge to support multi-project mode with per-topic `/project list`, `/project use`, `/project status`, and `/project clear` commands, and updated the generic OpenClaw and Zulip docs to describe the registry-driven flow.
- Validation: Compile-checked the new bridge and registry scripts, reran the template safety check, and ran a temporary smoke test with two synthetic project workspaces to verify both the registry validator and bridge `--check` path in multi-project mode.
- Outcome: The template now supports a shared multi-project routing layer for the software bridge instead of assuming one fixed project workspace.

- Date: 2026-03-26
- Request: Make the live AgentSmith Zulip flow report step-by-step progress and support an explicit stop command for the active thread.
- Action: Added active-run tracking, visible per-phase status posts, `/status` reporting, `/stop` cancellation with stronger process termination, and aligned the live AgentSmith docs in the software workspace.
- Validation: Compile-checked the updated assistant bridge, restarted the live bridge, and ran an end-to-end Zulip DM smoke test that showed status updates, a live `/status` reply, a `/stop` acknowledgement, and a final stopped-on-request message.
- Outcome: AgentSmith now exposes live progress and thread-local cancellation in Zulip instead of appearing opaque while a run is in progress.

- Date: 2026-03-25
- Request: Rename the live assistant bot to AgentSmith and give it a more animated Matrix-style discussion persona while keeping the existing software-manager flow intact.
- Action: Renamed the Zulip assistant bot display name to `AgentSmith`, rewrote the live assistant prompt to be sharper and more playful while still useful, updated the live assistant bridge strings and history labels to use the new identity, and restarted the assistant bridge.
- Validation: Verified the Zulip bot profile reflected the new name, compile-checked the patched bridge, restarted it successfully, and confirmed a live DM reply arrived under the `AgentSmith` name with the updated persona.
- Outcome: The assistant front door now presents as AgentSmith without changing the separate software-manager execution path.

- Date: 2026-03-25
- Request: Validate a live assistant-to-Zulip discussion flow that can front the software team without replacing the existing software-manager bridge.
- Action: Implemented and exercised a separate assistant bridge pattern in the live workspace, confirmed DM and assistant-stream discussion behavior, kept the software-manager bridge intact, and verified the assistant uses explicit handoff gating before posting tasks into the software stream.
- Validation: Smoke-tested assistant replies in both a Zulip DM and the `assistant` stream, checked bridge state transcripts, and confirmed both assistant and software bridge processes were running concurrently.
- Outcome: The template architecture was validated against a live two-bridge setup: one discussion-first assistant front door and one unchanged software-manager execution path.

- Date: 2026-03-25
- Request: Sanitize the OpenClaw and Zulip template so it contains no local-machine paths, no generated local runtime files, and no deployment-specific history.
- Action: Replaced hardcoded workspace and Zulip deployment values in the template docs and config examples with explicit `YOUR_...` variables, removed the generated local OpenClaw config from the template tree, added a template-repo safety check script, tightened the bridge example defaults, and cleaned ignored local runtime residue from the template directories.
- Validation: Scanned the repository for local-machine paths and secret-like material, checked tracked runtime files, and verified the new template safety check covers generated config, runtime residue, and local-instance string leakage.
- Outcome: The repository now behaves as a reusable template rather than a snapshot of one local deployment.

- Date: 2026-03-25
- Request: Add the first Zulip software-team bridge template and align the OpenClaw runtime with a manager-led software flow.
- Action: Added the reusable Zulip V1 software-team docs, the bridge runtime under `software_bridge_v1/`, and the supporting OpenClaw manager/planner/coder/tester template updates.
- Validation: Reviewed the new docs and bridge sources and verified the template tree shape.
- Outcome: The repository gained a reusable first-pass Zulip-to-software-team template.

- Date: 2026-03-24
- Request: Add Zulip installation, planning, and human-operator documentation for the OpenClaw template.
- Action: Added Zulip setup and planning guides for Docker Compose deployment, bridge architecture, and operator workflow.
- Validation: Reviewed the new docs and verified the OpenClaw template README and guide references.
- Outcome: The repository gained a coherent Zulip documentation set for future setup and bridge work.

- Date: 2026-03-13
- Request: Turn the OpenClaw folder into a reusable Docker-backed team template with a manager orchestrator and project-specific context in `PROJECT.md`.
- Action: Refactored the OpenClaw assets into a manager/planner/coder/tester template, added `PROJECT.md`, switched to generated local config from `openclaw.template.json`, removed committed runtime state, and rewrote the related docs and scripts.
- Validation: Verified shell syntax, rendered the local config successfully, validated the generated JSON, and confirmed no stale host-specific project paths remained in committed OpenClaw files.
- Outcome: The OpenClaw folder became a portable local team template instead of a machine-specific project snapshot.

- Date: 2026-03-12
- Request: Create the initial `.agents` template structure and migrate the old single-file `AGENTS.md` guidance into the split layout.
- Action: Added the `.agents` directories and starter documents, then merged the old workflow, coding, testing, and logging rules into the corresponding capability, skill, playbook, and memory files.
- Validation: Verified the resulting file tree and reviewed the updated target files after the migration.
- Outcome: The repository gained a reusable split agent documentation structure and the legacy guidance was absorbed into it.
