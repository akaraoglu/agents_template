# Mandatory Project Isolation

All generated project source, tests, documentation, results, and delivery artifacts must remain inside one dedicated project directory.

The default root is:

```text
/home/alik/workspace/agent_template/codexteam/projects
```

Rules:

1. Preview initialization before writing.
2. Resolve every project path beneath the configured projects root.
3. Reject absolute paths, traversal, backslashes, malformed segments, and symlink escapes.
4. Run workers from the assigned project root.
5. Grant additional writable directories only through explicit `--add-dir` arguments.
6. Keep runtime projects and result artifacts out of the repository.

`CODEXTEAM_PROJECTS_ROOT` may select another operator-approved root. It does not weaken containment checks.
