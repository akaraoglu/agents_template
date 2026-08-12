# CodexTeam v2 Assets

This directory contains the versioned catalog and guidance consumed by the
Foundation v2 fake and live-OpenCode canaries. OpenCode `1.18.16` with
Ollama `0.32.9` or newer and `ollama/muse-glimmer:30b` is the sole active
backend/model. Qwen and Codex profiles remain inactive historical baselines.
Runtime state is private under `.codexteam/v2/`.

See `docs/v2/README.md` for commands and current limitations.

Status: deterministic and fake-canary proven, not live-model accepted. Focused
Muse qualification passed again after the Ollama `0.32.9` upgrade. The next
adaptive canary completed Discovery and the Architecture write, then failed
closed because Muse returned malformed JSON from the read-only Architecture
candidate despite receiving the stage-specific schema. No retry or fallback was
used. See `docs/v2/MUSE_QUALIFICATION.md` and `docs/v2/E2E_ACCEPTANCE_PLAN.md`.
