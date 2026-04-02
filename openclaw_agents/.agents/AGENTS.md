# Local Workspace Rules

- Keep every project file change inside this repository root.
- Keep project-specific context in `project_template/`-based project folders,
  not in the shared control workspace.
- In multi-project mode, keep the shared project registry in a local
  `.agents/project_registry.json` file derived from the example template.
- Store OpenClaw prompts, scripts, Docker assets, config templates, sandboxes,
  and runtime state under `.agents/`.
- Do not write OpenClaw config or runtime state into any global path.
- Do not edit `.agents/openclaw.json` directly. It is generated from
  `.agents/openclaw.template.json`.
- Prefer `.agents/run_assistant.sh`, `.agents/run_neo.sh`,
  `.agents/run_yoda.sh`, `.agents/run_projectmanager.sh`,
  `.agents/run_architect.sh`, `.agents/run_morpheus.sh`,
  `.agents/run_oracle.sh`, `.agents/run_manager.sh`, `.agents/run_team.sh`, or
  `.agents/run_agent.sh` when invoking the local team.
- `.agents/run_agent.sh` must preserve the role prompt and inject the current
  project context when an ad hoc task message is provided.
- The visible V3 roles are:
  - assistant: `local-ollama-qwen-assistant`
  - neo: host-backed OpenAI OAuth role through `.agents/run_neo.sh`
  - yoda: `local-ollama-qwen-yoda`
  - projectmanager: `local-ollama-qwen-projectmanager`
  - architect: `local-ollama-qwen-architect`
  - morpheus: `run_team.sh` through `.agents/run_morpheus.sh`
  - oracle: `local-ollama-qwen-oracle`
- The internal software-team roles are:
  - manager: `local-ollama-qwen-manager`
  - planner: `local-ollama-qwen-planner`
  - coder: `local-ollama-qwen-coder`
  - tester: `local-ollama-qwen-tester`
- Use `zulip_gateway_v3/` for visible multi-role chat integration.
- Use `.agents/run_team.sh` when manager-led software orchestration is needed.
- The canonical local software flow is:
  manager -> planner (optional) -> coder -> tester -> manager summary.
- Keep cross-role handoffs, status updates, and result blocks aligned with
  `.agents/COMMUNICATION_CONTRACT.md`.
- Use visible Zulip handoffs for cross-role work. Do not rely on nested
  in-sandbox spawning as the primary orchestration mechanism.
- Keep the shared sandbox Python environment and prompt guidance aligned.
  Inside the sandbox, prefer `python` from PATH over hardcoded system
  interpreter paths.
- Keep extra sandbox packages defined in
  `.agents/docker/pytorch-shared-venv/requirements-extra.txt`.
- Read `.agents/SKILLS.md` when a task involves generating, using, or
  maintaining the local OpenClaw team.
- Keep `.agents/AGENTS.md`, `.agents/SKILLS.md`, prompts, wrappers, and local
  skill files aligned when instructions change.
