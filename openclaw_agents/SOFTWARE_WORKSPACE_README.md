# Software Workspace Template

This file is a reusable starting README for the project workspace mounted into
the Zulip V1 software team.

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
- `.agents/`

Inside the Docker sandbox, this project workspace is mounted at `/workspace`.

## First Local Steps

1. Update `PROJECT.md` with the real project summary, constraints, commands,
   and acceptance criteria.
2. Render the local OpenClaw config:

```bash
bash .agents/scripts/setup_local_team.sh
```

3. Validate the manager locally if needed:

```bash
bash .agents/run_manager.sh "Read PROJECT.md and summarize the next best step."
```

4. Once the Zulip bridge is configured, let the bridge invoke the team with:

```bash
bash .agents/run_team.sh "Implement the requested change and validate it."
```

## Notes

- Treat `PROJECT.md` as the source of truth for the software team.
- Keep project-specific code and files in this workspace, not in the template.
- Do not commit generated `.agents/openclaw.json` or runtime state if this
  workspace becomes its own repository.
