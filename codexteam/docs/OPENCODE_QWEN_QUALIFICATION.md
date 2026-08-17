# OpenCode Qwen Qualification

## Qualified Combination

`opencode/qwen36-27b` was requalified on 2026-08-17 using OpenCode `1.18.18`,
Ollama `0.32.9`, and `qwen3.6-27b:latest` at installed model ID
`c58032aa2fe5`.

Three fresh bounded canaries each read and edited one exact file, ran the
requested shell assertion successfully, and emitted terminal text whose
`messageID` matched the final `step_finish` with reason `stop`. A same-session
correction also edited the exact file, passed its assertion, preserved the
session ID, and emitted a matching terminal report.

The canaries ran through OpenCode's Ollama provider on the local RTX 5090. They
used isolated disposable workspaces and did not modify a project or toolkit
source file. This evidence qualifies the exact backend/model/runtime
combination for bounded CodexTeam work; it does not waive task-specific gates or
prove every large-context workflow.
