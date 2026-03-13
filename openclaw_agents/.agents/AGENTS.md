# Local Workspace Rules

- Keep every project file change inside this repository root.
- Keep all project-specific context in `PROJECT.md`. Update that file when project goals, commands, constraints, or acceptance criteria change.
- Store OpenClaw prompts, scripts, Docker assets, config templates, sandboxes, and runtime state under `.agents/`.
- Do not write OpenClaw config or runtime state into any global path.
- Do not edit `.agents/openclaw.json` directly. It is generated from `.agents/openclaw.template.json`.
- Prefer `.agents/run_manager.sh`, `.agents/run_team.sh`, or `.agents/run_agent.sh` when invoking the local team again.
- `.agents/run_agent.sh` must preserve the role prompt and include `PROJECT.md` context when an ad hoc task message is provided.
- The local team roles are:
  - manager: `local-ollama-qwen-manager`
  - planner: `local-ollama-qwen-planner`
  - coder: `local-ollama-qwen-coder`
  - tester: `local-ollama-qwen-tester`
- Use `.agents/run_team.sh` when manager-led orchestration is needed.
- The canonical local team flow is manager -> planner (optional) -> coder -> tester -> manager summary.
- Keep the shared sandbox Python environment and prompt guidance aligned. Inside the sandbox, prefer `python` from PATH over hardcoded system interpreter paths.
- Keep extra sandbox packages defined in `.agents/docker/pytorch-shared-venv/requirements-extra.txt`.
- Read `.agents/SKILLS.md` when a task involves generating, using, or maintaining the local OpenClaw team.
- Keep `.agents/AGENTS.md`, `.agents/SKILLS.md`, prompts, wrappers, and local skill files aligned when instructions change.
