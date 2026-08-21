# Muse Glimmer Qualification

## Qualified Combination

`opencode/muse-glimmer` was qualified on 2026-08-12 using OpenCode `1.18.16`
and Ollama model `muse-glimmer:30b` at digest
`de878ce33ad81d060001db1469a02eebe4d86f0ad58cfe52dc062fdcbe4464c1`.

The bounded gate completed eleven checks without retry or fallback: exact
Ollama and OpenCode metadata, direct text/JSON/thinking/tool-call behavior,
OpenCode text-only/read-only/write-read behavior, and tool-free same-session
Discovery and Architecture candidate checks. The machine result recorded
`QUALIFIED`, schema `2.0`, duration `124821` ms, and start time
`2026-08-12T07:52:17.820246Z`.

This is dated qualification evidence for the exact model/runtime combination,
not proof of current host availability or every current registry metadata field.
The original machine result remains outside the repository; Git history is the
archive for the retired qualification implementation.

## Current Qualified Status

On 2026-08-17, the existing `muse-glimmer:30b` tag was tuned in place to
`num_ctx=131072`, temperature `0.6`, top-k `20`, and top-p `0.95`, then tested
through OpenCode 1.18.18 and Ollama 0.32.9 on the local RTX 5090. Five fresh
isolated runs each made the exact requested edit, passed the shell assertion,
and emitted non-empty terminal text whose `messageID` matched
`step_finish(reason="stop")`. Same-session correction also passed. The exact
combination is qualified for implementation-oriented spawned roles. Real-project
Tester and Reviewer canaries exceeded bounded scope and timed out, so Qwen
remains the default for those independent evidence roles. There is no automatic
model fallback.
