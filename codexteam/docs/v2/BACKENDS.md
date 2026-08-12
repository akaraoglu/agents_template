# CodexTeam v2 Backends

## Active: OpenCode and local Muse Glimmer

Foundation v2 has one active backend: OpenCode `1.18.16` with
`ollama/muse-glimmer:30b`. All seven active AgentSpecs route to the
`muse-glimmer-opencode` profile. The inactive Qwen profiles remain as historical
baselines. Codex definitions remain in the catalog for experimental
compatibility, but no active AgentSpec references Qwen or Codex and the v2 CLI
does not expose a live Codex command.

The adapter maps the OpenCode model to the exact Ollama tag
`muse-glimmer:30b`. Preflight requires digest
`de878ce33ad81d060001db1469a02eebe4d86f0ad58cfe52dc062fdcbe4464c1`
and `/api/show` metadata for family `muse-glimmer`, size `27.9B`, quantization
`Q4_K_M`, context `131072`, and capabilities completion, tools, thinking, and
vision. `/api/show` is called with the exact tag, never an alias.

The adapter accepts the pinned absolute `/home/alik/.opencode/bin/opencode`
native x86-64 ELF. It requires root or current-user ownership and rejects world
write. A current-user source writable by one of that user's groups is accepted
as source data. Verified bytes are copied to a role-private `0500` executable;
only that private copy is executed.

Each role owns a private tree at
`<canary>/.codexteam/v2/runtime/<role>/opencode/`. `HOME`, all XDG paths, config,
state, data, cache, and runtime directories point there with private modes. The
generated `0400` config is written once and its digest is checked before and
after turns. The environment starts from an allowlist and contains no host
tokens or proxy variables. Project config, model fetch, auto-update, Claude Code
integration, default plugins, and external skills are disabled by environment;
`--pure` disables external plugins at execution.

The config enables only Ollama and the selected model. It sets `plugin=[]`,
`mcp={}`, `lsp=false`, `formatter=false`, `instructions=[]`, empty skill paths
and URLs, `subagent_depth=0`, `share=disabled`, `snapshot=false`, and
`autoupdate=false`. OpenCode validates the effective config during preflight.
The Muse model entry declares schema-valid `family=muse-glimmer`, attachment,
reasoning, tool-call, interleaved reasoning, and temperature support; text/image
input and text output; and limits of 131072 context, 114688 input, and 16384
output tokens. Preflight compares these values in effective config, not merely
the model key. No unverified provider option such as `maxTokens` is configured.
Two primary agents exist for each role:

- `mutable` has the role's compact responsibility and normal product-cwd
  edit/write tools. The compiled assignment scope is carried in every turn and
  enforced immediately by StageRunner's ChangeSet audit.
- `readonly` has the same responsibility but denies edit, write, and bash.

Discovery, Assurance, and Review are read-only. Architect owns
`docs/architecture/**`, UX owns `docs/design/**`, Developer owns `src/**` and
`tests/**`, and Test owns `tests/**`. The prompt makes those boundaries explicit,
and immediate auditing rejects any other product change. Reads use an explicit
product-only rule and external directories are denied. The first canary denies
bash for every model role;
kernel `VerificationExecutor` runs tests. Task, skill, web, LSP, question,
external-directory, and other fallback tools are denied. `--auto` is never used,
so no permission can hang waiting for an approval prompt.

## Practical Boundary

OpenCode permissions are not an OS sandbox. The product directory
`<canary>/project` is intentionally writable for writer roles and is the exact
cwd and `--dir`. Its authoritative `.codexteam` sibling is outside that working
directory and `external_directory` is denied. The host source repository is not
inside the working directory. StageRunner records a practical execution
attestation and independently audits the post-turn product manifest against the
role's exact assignment scope. Candidate reporting uses the `readonly` agent and
must leave the product manifest unchanged.

The parent OpenCode process can reach localhost Ollama. The model has no web or
bash tool in the canary, so it has no model-command network surface. This is a
documented practical limitation, not a network namespace guarantee.

Every turn runs in a unique transient user-systemd scope with
`KillMode=control-group`. There is no nested sandbox and no process-group
fallback. Timeout, exception, normal completion, and lingering descendants all
require the scope to become inactive; failure to prove cleanup is a high-severity
runtime error.

The exact OpenCode command after the systemd wrapper is:

```text
<private-opencode> run --pure --format json --model ollama/muse-glimmer:30b --agent <mutable|readonly> --dir <canary>/project --title <initial-title>
```

Continuations replace `--title` with `--session <exact-session-id>`. The adapter
never uses `--continue`, `--fork`, or `--auto`.

## Preflight And Sessions

Preflight makes no model call. It observes and records the exact source and
private executable identities, version, generated config digest, exact Ollama
tag digest, product read access, writer edit/write capability, compiled
assignment scope for authoritative auditing, readonly edit/write denial,
required context pins, and a working user-systemd scope. The product manifest
must remain unchanged.

The atomic private session record pins the OpenCode session ID, source and
runtime executable, version, config, selected model and mutable tag digest,
role/context/workspace identities, exact product path, mutable-agent name, and
private runtime paths. Resume verifies every pin. JSON events must all carry one
consistent `sessionID`, include exactly one terminal `step_finish` with reason
`stop`, and contain text. The last text part must be a raw JSON object or one
exact lowercase `json` fence. Any OpenCode error or malformed stream fails.

The qualification harness reuses this private config, executable pinning,
process cleanup, JSONL parsing, and exact-session machinery through a narrow raw
turn helper. It adds no retry or fallback path. See `MUSE_QUALIFICATION.md`.
