# CodexTeam Templates

`project/` is the canonical project initialization template. It produces the complete SDD, state, task, management, verification, and delivery document set.

The initializer renders all `{{TOKEN}}` values before writing, copies the current project-relevant skills into `.codexteam/skills/`, creates a one-page team brief, and ignores `.codexteam/runtime/` session state. Templates must be UTF-8 text, must not contain symlinks, and must not embed commands that bypass workspace or verification policy.
