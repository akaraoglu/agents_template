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

## Current Status

The derived `muse-glimmer:30b-131k` profile is not qualified. On 2026-08-17,
OpenCode 1.18.18 with Ollama 0.32.9 completed a bounded edit and test, including
same-session correction, but a second fresh run failed to emit a terminal
response before the six-minute bound. The profile is therefore quarantined and
absent from the supported execution catalog. No automatic fallback is used.
