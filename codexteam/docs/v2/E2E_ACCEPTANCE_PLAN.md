# CodexTeam v2 E2E Acceptance Plan

The deterministic fake canary proves the adaptive seven-stage pipeline, exact
session reuse, product changes, defect correction, stale evidence rerun, strict
semantic parsing, StageRunner permission audit, kernel verification, assurance,
review, deterministic sealing, and closure.

The fake OpenCode executable proves all seven stages through the real adapter
protocol. Tests assert the private `0500` executable, strict generated config,
sanitized environment, exact initial and continuation argv, no `--continue`,
`--fork`, or `--auto`, product-only cwd/`--dir`, one event session ID, terminal
stop, last-text semantic parsing, config/model/workspace/context drift rejection,
role-specific assignment-scope prompts, immediate root-write detection, exact
allowed writes, readonly candidate denial, malicious permission-bypass audit,
and user-systemd timeout cleanup.

Automated live verification runs only `--dry-run`. It creates an internal
fixture, preflights Discovery and Developer without a model call, and leaves the
requested path untouched. The parent operator owns any real model invocation.

Historical live OpenCode/Qwen trials are recorded as non-passing canaries. Discovery and
adaptive pipeline revisioning executed correctly, and the kernel blocked
out-of-scope writes. Later stages exposed model/backend reliability issues:
inconsistent final text after tool use and unreliable path-pattern permission
matching for new nested files. These are adapter/model concerns; they do not
invalidate deterministic contract, evidence, verification, assurance, review,
or sealing tests. No automatic retries or fallback model were used.

Muse Glimmer is the sole active profile. Its focused qualification returned
`QUALIFIED` on 2026-08-11: exact metadata, four direct requests, and three
minimal OpenCode behaviors all passed without retries or fallback. The first
post-qualification adaptive canary then completed Discovery, revision,
Architecture, UX, Developer, and the Test writer turn before failing closed on
the Test candidate's invalid `artifact`/`analysis` evidence types. The product
files were correct; the generated JSON Schema had advertised all evidence enum
values even though StageRunner correctly requires `test_output` at Verification.
The schema is now stage-specific. No automatic retry was made, and full live
acceptance still requires a fresh successful adaptive canary.

A subsequent benchmark under Ollama `0.32.8` completed the first five stages,
accepted kernel verification, and preserved a clean product before Assurance
returned `step_finish(reason="unknown")` with no usable text. The Ollama service
log showed Muse emitted `read<|message|><atem:parameter ...`; Ollama `0.32.9`
ships the exact boundary-token recovery fix. The benchmark remains non-passing
and is preserved at `/tmp/opencode/codexteam-v2-benchmark-20260811`.

After the `0.32.9` upgrade, all nine qualification checks passed again. One
fresh adaptive canary then completed Discovery and the Architecture writer turn
with only the allowed document change. The read-only Architecture candidate
received a schema whose evidence enum contained only `artifact`, but Muse
returned malformed JSON (`["findings": ...`). The adapter rejected it before
UX, with no retry or fallback. That non-passing workspace is preserved at
`/tmp/opencode/codexteam-v2-muse-live-ollama-0329`.
