# Mandatory Project Isolation

All generated control state, task management, runtime, results, discoveries,
and delivery artifacts remain inside one dedicated control project. Product
source, tests, build configuration, and product documentation remain in
registered source repositories.

The default root is:

```text
/home/alik/workspace/codexspace/projects
```

Rules:

1. Preview initialization before writing.
2. Resolve every project path beneath the configured projects root.
3. Reject absolute paths, traversal, backslashes, malformed segments, and symlink escapes.
4. Run workers from the exact registered source root for split-root tasks.
5. Grant additional writable directories only through explicit `--add-dir` arguments.
6. Keep control runtime and result artifacts out of product source repositories.

`CODEXTEAM_PROJECTS_ROOT` may select another operator-approved root. It does not weaken containment checks.
