# CodexTeam Source

`codexteam_tools/` contains the deterministic implementation shared by operator scripts:

- contracts and schemas
- safe path handling
- atomic writes
- project initialization
- task-ledger parsing
- result verification
- local Codex spawning
- strict role policies, native-agent projection, and project guidance sync
- machine-readable Development and Integration Gate execution
- deterministic authorized local milestone commits
- project-local subagent status inspection
- read-only project, task, metric, and milestone-commit readers used by operator surfaces
- verified task closure

Runtime projects and model output belong under the configured projects root, not here.
