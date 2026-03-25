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
