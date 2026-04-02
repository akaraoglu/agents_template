# Software Workspace Template

This file is a reusable starting README for the project workspace used by the
current V3 Zulip and OpenClaw system.

## Recommended Variables

Replace these values for each project:
- `YOUR_PROJECT_WORKSPACE`: host path to the software project root
- `YOUR_SOFTWARE_STREAM_NAME`: Zulip stream used for software requests
- `YOUR_SOFTWARE_MANAGER_BOT_NAME`: visible Zulip manager bot name

Recommended defaults for the current template:
- `YOUR_SOFTWARE_STREAM_NAME`: `software`
- `YOUR_SOFTWARE_MANAGER_BOT_NAME`: `software-manager-bot`

## Expected Structure

The mounted project workspace should contain at minimum:
- `PROJECT.md`
- `management/`

Inside the Docker sandbox, this project workspace is mounted at `/workspace`.

If the project also carries its own local OpenClaw runtime, it may additionally
contain:
- `.agents/`

## First Local Steps

1. Bootstrap the project documents from `project_template/` if the project does
   not already have them.
2. Update `PROJECT.md` with the real project summary, constraints, commands,
   and acceptance criteria.
3. Update `management/STATUS.md`, `management/MILESTONES.md`, and
   `management/BACKLOG.md` to reflect the real project state.
4. If the project carries its own local runtime, render the local OpenClaw
   config:

```bash
bash .agents/scripts/setup_local_team.sh
```

5. Validate the manager locally if needed:

```bash
bash .agents/run_manager.sh "Read PROJECT.md and summarize the next best step."
```

6. Once the Zulip gateway is configured, let the gateway invoke the team with:

```bash
bash .agents/run_team.sh "Implement the requested change and validate it."
```

## Notes

- Treat `PROJECT.md` and `management/` as the source of truth for the software
  team.
- Keep `.agents/` inside the project only when the project needs its own local
  runtime. In a shared multi-project setup, `.agents/` stays in the shared
  control workspace.
- Keep project-specific code and files in this workspace, not in the template.
- Do not commit generated `.agents/openclaw.json` or runtime state if this
  workspace becomes its own repository.
