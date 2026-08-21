# Codex Local Profile Qualification

## Qualified Profiles

The following local Codex profiles were smoke-qualified on 2026-08-20 with
Codex CLI `0.147.0` and Ollama `0.32.14`:

| Profile | Model | Context | Result |
|---|---|---:|---|
| `codex/qwen38-27b` | `qwen3.8-27b:latest` | 262144 | PASS |
| `codex/muse-glimmer` | `muse-glimmer:30b` | 131072 | PASS |
| `codex/gemma4-26b` | `gemma4-26b:latest` | 32768 | PASS |

Each exact alias was then loaded through Ollama on the qualification host. `ollama
ps` reported the declared context and `100% GPU` residency for all three:

- Qwen 3.8: model ID `e200453f7eea`, context `262144`.
- Muse Glimmer: model ID `b02871905d63`, context `131072`.
- Gemma 4 26B: model ID `99c730acdc90`, context `32768`.

Each profile ran in a disposable Git workspace with Codex's normal
`workspace-write` sandbox. The first turn changed one exact file and passed an
exact shell assertion. The same persistent thread was then resumed with the
model/provider/catalog/reasoning/verbosity pinned explicitly; it changed the
same file to a second expected value and passed the corrected assertion.

Qwen 3.8, Muse Glimmer, and Gemma all completed both turns successfully. These
results qualify them as optional CodexTeam Codex-backend profiles; they do not
change default routing or replace task-specific verification.

## Not Curated

- `ornith35b`: initial edit passed, but the resumed turn claimed success without
  executing the correction; the file remained unchanged.
- `gpt56-luna` and `gpt56-terra`: profile selection and authentication reached
  OpenAI, but both live smokes were blocked because the workspace was out of
  credits. They remain installed profiles, not CodexTeam-curated profiles.

## Notes

- Raw `codex exec resume` does not preserve the original `-C` working directory
  or profile selection automatically. CodexTeam's adapter explicitly replays
  model, provider, catalog, reasoning, verbosity, and workspace on continuation.
- Local Ollama aliases remained unchanged during qualification.
