# CodexTeam v2 Troubleshooting

## OpenCode preflight failed

Do not run a model. Confirm `/home/alik/.opencode/bin/opencode --version` is
exactly `1.18.16`, `ollama --version` is `0.32.9` or newer, the files are trusted
and not world-writable, the exact Ollama tag `muse-glimmer:30b` exists with the
pinned digest and metadata, and the private effective config validates.
Ollama `0.32.8` is unsupported for Muse canaries because its Glimmer parser can
lose malformed function-call boundary tokens. `/api/show` must receive the exact tag.
Config drift is a hard
session failure; do not regenerate it to hide a mismatch.

## User-systemd failed

Live and live dry-run require usable absolute `systemd-run` and `systemctl`
tools plus a user manager. There is no process-group fallback. A `HIGH:` error
means descendant cleanup could not be proven; do not audit or seal the turn.

## Permission or forbidden-write failure

OpenCode permissions are not an OS sandbox. Inspect the private turn
JSONL/stderr, role-private effective config, and StageRunner's product ChangeSet.
Writer roles have product-cwd edit/write access. The prompt carries the exact
compiled assignment scope, and StageRunner's immediate audit is the enforcement
boundary. It does not
remove forbidden files, so preserve a failed workspace for diagnosis and start
the parent run with a new absent or empty workspace. Candidate turns use the
readonly agent and any product mutation is rejected even if tool permission
regresses.

## Wrong paths

Model prompts use paths relative to `<canary>/project`, such as `src/...` and
`tests/...`. Kernel records continue to use `project/**`. Never expose the host
private runtime or parent `.codexteam` path in a model prompt.
