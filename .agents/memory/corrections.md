# Corrections Log

Append one-off lessons here when a mistake is discovered, the agent is corrected, or guidance becomes outdated.

## Entry Template
- Date:
- Problem:
- Root cause:
- New rule:
- Where it was recorded:

## Entries

- Date: 2026-03-30
- Problem: The live Niaobe verification run for `projects/fibonacci_niobe_test` stopped after planning instead of reaching Morpheus and Oracle.
- Root cause: The live `run_assistant_spawn.sh` project-manager flow is implemented as `Niaobe initial pass -> Architect -> Niaobe review` and only emits `MORPHEUS_READY` / `MORPHEUS_TASK`; it never actually invokes `run_team.sh` or any Morpheus path. The live `projectmanager.txt` prompt is also outdated and still tells Niaobe to read `PROJECT.md` from the repository root instead of the selected project's own `PROJECT.md` and `management/`.
- New rule: Treat the current Niaobe flow as planning-only until the runner actually executes the Morpheus handoff and the Niaobe prompt is updated to project-local instructions. Do not assume `MORPHEUS_READY: yes` means the software loop has started unless a real software-topic handoff or `run_team.sh` invocation is visible.
- Where it was recorded: `.agents/memory/changelog.md`

- Date: 2026-03-30
- Problem: The first live repair of the Niaobe loop still misread some successful Oracle and Morpheus outputs, leaving fields like `ORACLE_DECISION` empty even when the agent had clearly returned a valid answer.
- Root cause: The shell parsers in `run_team.sh` and `run_assistant_spawn.sh` only recognized plain multiline `SECTION:\nvalue` blocks. They did not accept markdown-formatted headers like `**PLAN_SUMMARY:**` or inline one-line values like `ORACLE_DECISION: accepted`.
- New rule: Shell-side agent output parsing must tolerate both decorated headers and inline `KEY: value` responses, because the live models do not reliably stick to one exact formatting style even when prompted with strict schemas.
- Where it was recorded: `.agents/memory/decisions.md`
- Date: 2026-03-30
- Correction: Template `systemd` bridge unit files must not commit live `/home/alik/...` paths.
- Why it was wrong: The initial reusable service files were copied from the live host setup and caused the template safety check to fail because they embedded one machine's bridge paths and username.
- Correct guidance: Keep committed service files as placeholders or examples, and substitute the real bridge user and directories during installation on the target host.

- Date: 2026-03-31
- Problem: The first V3 planning recommendation still leaned on strict topic ownership even after the user clarified that all visible agents should be DM-able and not locked into rigid topic-bound permissions.
- Root cause: The design carried over too much of the heavier V2 ownership model instead of fully adapting to the simpler chat-first use case.
- New rule: V3 should use light thread coordination (`active_run_id`, `current_speaker`, `awaiting_from`, `participants`, `mode`) plus mention/handoff activation rules, not strict topic ownership.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-03-31
- Problem: The first V3 template pass documented visible-role wrappers and gateway examples that the generic template did not actually ship.
- Root cause: The design work moved faster than the reusable runtime skeleton, so the docs started describing a target setup that still depended on deployment-specific files.
- New rule: When a setup guide or example registry names a role wrapper, prompt, or service file, the template must either ship that artifact or mark it explicitly as deployment-local. Do not leave documented default paths pointing at missing files.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-01
- Problem: The first live Neo wrapper test failed with `JSONDecodeError` even though the underlying `openclaw agent --agent neo --json` call was healthy.
- Root cause: The shell wrapper tried to pipe the JSON into `python3 - <<'PY'`, but the heredoc consumed `stdin`, so the piped JSON never reached `json.load(sys.stdin)`.
- New rule: When parsing piped command output in shell, use `python3 -c '...'` or a temporary file. Do not combine a heredoc-fed Python script with a pipe when the pipe is supposed to provide runtime input.
- Where it was recorded: `.agents/scripts/run_openai_oauth_host_runtime.sh`

- Date: 2026-04-01
- Problem: The template still looked like it had multiple equally current Zulip runtimes because the old split-bridge service units lived beside the V3 gateway service in the main `systemd/` folder.
- Root cause: Legacy fallback material was preserved, but not isolated strongly enough from the default path.
- New rule: Keep fallback bridge configs physically separated under a `legacy/` subtree whenever the repo has a newer default system. Do not leave old service files at the same top-level path as the recommended runtime.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-02
- Problem: A real live pipeline test woke Niaobe immediately from the user's initial `@AgentSmith ... @Niaobe ... @Architect ...` message, which caused the gateway to reject Smith's handoff with `that agent is already working on this thread`.
- Root cause: The V3 mention parser treated every explicit `@**Agent**` mention in a human stream message as an invocation target, instead of treating the initial addressed agent as the sole first responder.
- New rule: For human messages in shared Zulip threads, only the first explicit `@**Agent**` mention should trigger a visible run. Other mentions in that same message are references until a visible handoff activates them.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-02
- Problem: Live Oracle and other visible roles could replay stale local OpenClaw content from earlier ad hoc runs, even when the current Zulip thread had completely different context.
- Root cause: The live launchers relied on OpenClaw's default local session reuse because no explicit session id was passed per visible role/thread.
- New rule: All visible Zulip-driven OpenClaw runs need explicit session ids, and team-internal manager/planner/coder/tester stages need their own derived session ids as well. Never assume the default local session is safe for multi-threaded visible agent work.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-02
- Problem: Morpheus summaries were claiming `Oracle validation passed` even when only the internal tester had run, which let Niaobe skip the visible Oracle phase and close too early.
- Root cause: The software-team synthesis prompts and wording still blurred the line between the internal tester and the visible Oracle role.
- New rule: Internal tester output must be labeled as internal tester validation only, and any true Oracle approval must come from the visible Oracle role in-thread before Niaobe closes the phase.
- Where it was recorded: `.agents/memory/decisions.md`

- Date: 2026-04-02
- Problem: After deleting the old bridge directories from the template, the repo safety script still tried to inspect those removed paths and failed the cleanup validation.
- Root cause: The safety script had drifted with the older template layout and still encoded checks for the deleted legacy bridge directories.
- New rule: When a cleanup removes a whole supported path from the template, update the validation scripts in the same change so they only check the remaining current layout.
- Where it was recorded: `.agents/memory/decisions.md`
