# OpenCode Qwen 3.8 Qualification

## Qualified Combination

`opencode/qwen38-27b` was qualified on 2026-08-20 using OpenCode `1.18.18`,
Ollama `0.32.14`, and tuned alias `qwen3.8-27b:latest` at installed model ID
`e200453f7eea`. The alias preserves the base model's native `qwen3.8` renderer,
`qwen3.5` parser, and published sampling values, while explicitly pinning
`num_ctx=262144`.

Runtime inspection proved context `262144`, 100% GPU residency, q8_0 K/V cache,
flash attention, and approximately 29.2 GB VRAM use on the local RTX 5090.
Non-thinking chat stopped cleanly with exact output, and the OpenAI-compatible
endpoint emitted a valid required function call with the expected arguments.

A disposable OpenCode session edited one exact file, ran its assertion, then
resumed the same session ID for a second exact edit and assertion. The initial
turn completed in five model steps and the correction in four, with normal
terminal `stop` events and about 4.7K cumulative input tokens. A third turn wrote
the required artifact-report-shaped JSON and validated it. Its requested
`python` command was unavailable; the model diagnosed that environment fact and
successfully retried with `python3`.

This qualifies the exact backend/model/runtime combination for bounded
CodexTeam work. It remains an optional profile until real-project Developer,
Test Engineer, and Reviewer trials justify a routing change. It does not waive
task-specific gates or qualify a Codex backend profile.

## Real-Project Trial

Qwen 3.8 recovered the blocked T321 Developer task: it implemented the complete
chooser correction, passed the Development Gate, and corrected a Parent-trail
duplication found by Lead review. Its first broad turn still timed out after
finishing implementation; the clean acceptance attempt and focused correction
completed normally. A subsequent T322 Test Engineer trial exceeded bounded
scope across two long custom-oracle turns and produced no project evidence.
This supports optional bounded Developer use, not default Tester routing.

## Context-Projection Extension

On 2026-08-21, Qwen 3.8 was requalified against OpenCode `1.18.20` with an
attempt-private CodexTeam plugin and explicit `medium` reasoning. A matched
native Ollama harness comparison over architecture review, noisy failing-test
diagnosis, and cross-file impact retained strict correctness in 6/6 raw and 6/6
projected runs while reducing prompt tokens from 561,580 to 60,484 (`89.2%`),
model-visible tool bytes from 441,192 to 15,666 (`96.4%`), and model time from
127.263s to 72.921s (`42.7%`). Full output remained digest-bound in mode-`0600`
artifacts under mode-`0700` directories.

A live OpenCode canary then archived a 99,023-byte authoritative Bash output
from OpenCode's private `metadata.outputPath`, supplied a bounded projection to
later model steps, resumed the same session across format-only corrections, and
sealed the accepted result without a provider final turn. This qualifies the
plugin contract as `opencode/qwen38-27b-context` for bounded Qwen 3.8 attempts.
The original `opencode/qwen38-27b` identity retains provider-default behavior
for pinned-attempt compatibility. It does not qualify external
plugins, nested agents, or the archive as an OS security boundary.
