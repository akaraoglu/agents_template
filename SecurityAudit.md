Security audit: OpenCode worker write boundary
Executive finding
The OpenCode boundary is policy-and-audit based, not containment based.
For ordinary OpenCode workers:
1. The generated permission map denies direct OpenCode file tools outside the workspace unless --add-dir allows them.
2. It leaves bash allowed through "*": "allow".
3. OpenCode’s external_directory check analyzes tool arguments/command text; it is not a kernel filesystem policy inherited by child processes.
4. The launcher executes OpenCode directly on the host, as the invoking Unix user, without bubblewrap, namespaces, seccomp, chroot, Landlock, or mount restrictions.
5. Therefore a permitted shell can start Node, Python, compilers, browsers, or arbitrary binaries, and those children receive the invoking user’s normal host filesystem access.
6. Post-turn auditing snapshots only:
- the assigned workspace, excluding .git and .codexteam/runtime; and
- each explicit --add-dir.
7. Writes to /tmp, home, sibling repositories, runtime state, browser state, or any other unscanned location are generally invisible.
Consequently, denying direct write/edit access to /tmp does not prevent:
node -e 'require("fs").writeFileSync("/tmp/file", "data")'
python3 -c 'open("/tmp/file","w").write("data")'
The OpenCode permission decision authorizes bash; after process creation, Node/Python performs the filesystem syscall itself. No OS sandbox mediates that syscall.
1. Role-policy layer
Policy model
Role policies are loaded and validated in:
- /home/alik/workspace/agent_template/codexteam/src/codexteam_tools/roles.py
- RolePolicy
- RolePolicy.allows_change()
- load_role_policy()
- role_policy_from_mapping()
- role_boundary_errors() is in spawn.py
The policy contains:
- sandbox_mode
- allowed_change_patterns
- denied_change_patterns
- MCP ceilings
- evidence types
These path rules are post-turn change classification, not filesystem ACLs.
Key roles
- Developer:
- /home/alik/workspace/agent_template/codexteam/roles/developer.toml
- sandbox_mode = "workspace-write"
- broad allowed_change_patterns = ["**"], narrowed by denials and task scope.
- Test Engineer:
- /home/alik/workspace/agent_template/codexteam/roles/tester.toml
- Reviewer:
- /home/alik/workspace/agent_template/codexteam/roles/reviewer.toml
- Git Steward:
- /home/alik/workspace/agent_template/codexteam/roles/git_steward.toml
- nominally read-only, but OpenCode does not translate that value into OS containment.
- Leader:
- /home/alik/workspace/agent_template/codexteam/roles/leader.toml
AgentSpecs can only narrow policy:
- /home/alik/workspace/agent_template/codexteam/src/codexteam_tools/agent_specs.py
- effective_role_policy()
- _pattern_subset()
- effective_policy_digest()
Again, this narrows audit acceptance, not host write capability.
2. Generated OpenCode permissions
Generated configuration:
- /home/alik/workspace/agent_template/codexteam/src/codexteam_tools/opencode_backend.py
- build_config()
For normal mode:
common_permissions = {
    "*": "allow",
    "task": "deny",
    "skill": "deny",
    "lsp": "deny",
    "external_directory": external_directories,
    "question": "deny",
    "webfetch": "deny",
    "websearch": "deny",
}
The important result is:
- bash: allowed by "*": "allow"
- write/edit: allowed inside OpenCode’s understood workspace boundary
- external_directory: denied by default
No explicit normal-mode bash restriction exists.
Direct mode
For Context Mode: direct, build_config() explicitly denies:
- read
- glob
- grep
- list
- bash
and allows edits only to declared literal paths.
Relevant code:
- opencode_backend.py:70-82
- spawn.py:_build_handoff_contract()
- spawn.py:_direct_verification_command()
Thus the shell-runtime bypass applies to ordinary shell-capable attempts, not direct mode unless OpenCode itself has a separate permission-enforcement defect.
Format-only mode
codexteam-format explicitly denies bash and other tools:
- opencode_backend.py:83-100
- opencode_backend.py:137-146
Because OpenCode 1.18 does not support ordered exact-path edit rules reliably, it grants edit broadly and relies on post-turn repair:
"edit": "allow" if artifact_report_path else "deny"
The launcher then permits only the report mutation.
Tests:
- /home/alik/workspace/agent_template/codexteam/tests/test_spawn.py
- test_format_only_feedback_uses_no_tools_agent_and_rejects_other_changes
- test_format_only_invalid_report_restores_previous_bytes
- test_opencode_format_agent_allows_only_exact_report_edit
- test_opencode_format_agent_config_preserves_edit_tool_for_post_turn_audit
The name “no tools” in some documentation is imprecise: edit/write remains available when a report exists, with launcher-side auditing.
3. external_directory behavior
Construction:
external_directories = {"*": "deny"}
external_directories.update({f"{path}/**": "allow" for path in add_dirs})
Source:
- opencode_backend.py:58-65
--add-dir is accepted by:
- spawn.py:2775
- resolved by prepare_request() at spawn.py:455-460
- pinned in ExecutionSpec by _resolve_execution_spec()
- restored on continuation from permissions.additional_write_roots
ExecutionSpec implementation:
- /home/alik/workspace/agent_template/codexteam/src/codexteam_tools/execution_spec.py
- compile_execution_spec()
- validate_execution_spec()
Documentation:
- /home/alik/workspace/agent_template/codexteam/docs/rules/project_isolation.md:17
What external_directory actually controls
It is an OpenCode tool authorization rule. Historical logs show OpenCode resolving apparent path arguments and evaluating external_directory:
- /home/alik/workspace/agent_template/codexteam/projects/git_gui/.codexteam/runtime/sessions/git_gui/T317/att-001/opencode-runtime/xdg-data/opencode/log/opencode.log
The same history shows commands whose path forms were denied, while other shell commands involving /tmp/opencode executed successfully.
This is command/tool inspection, not syscall mediation. It cannot reliably determine paths constructed dynamically inside an interpreter:
python3 -c 'p="/tmp/"+"hidden"; open(p,"w").write("x")'
node -e 'let p=["","tmp","hidden"].join("/"); require("fs").writeFileSync(p,"x")'
Nor does it mediate a compiler, browser, script, or subprocess after launch.
4. Execution surface and absence of OS sandboxing
OpenCode command:
- /home/alik/workspace/agent_template/codexteam/src/codexteam_tools/opencode_backend.py
- build_command()
It runs:
opencode run --pure --format json --model ... --agent ... --dir <workspace>
Process creation:
- /home/alik/workspace/agent_template/codexteam/src/codexteam_tools/spawn.py
- run_process()
- _run_streaming_process()
Ultimately:
subprocess.Popen(
    command,
    ...
    start_new_session=True,
    env=env,
    cwd=cwd,
)
There is no sandbox wrapper.
The OpenCode adapter explicitly rejects:
- --trust-parent-sandbox
- --run-guard
Relevant code:
- spawn.py:298-307
- /home/alik/workspace/agent_template/codexteam/src/codexteam_tools/backend_adapter.py
- OpenCodeBackendAdapter
Authoritative documentation acknowledges this:
- /home/alik/workspace/agent_template/codexteam/docs/SECURITY_GUIDE.md:30-31
- /home/alik/workspace/agent_template/codexteam/docs/ADAPTER_GUIDE.md:67,77
- /home/alik/workspace/agent_template/codexteam/.agents/skills/subagent-orchestration.md:66-69,177
- /home/alik/workspace/agent_template/codexteam/.agents/playbooks/nested-worker-sandbox.md
OpenCode is intentionally launched at an approved host-level surface because it needs host Ollama access. “Approved host-level” is an operational route, not containment.
5. Why Node/Python bypass direct /tmp denial
The authorization sequence is:
1. Worker requests the OpenCode bash tool.
2. Normal generated permissions match "*": "allow".
3. OpenCode may inspect literal path-looking shell tokens against external_directory.
4. If the command is accepted, /bin/sh, Node, Python, or another executable starts as the same Unix user.
5. That process performs openat(2), renameat(2), mkdirat(2), etc.
6. No kernel policy restricts those calls to the workspace.
7. The launcher later scans only selected roots.
Direct write/edit and external_directory rules are not inherited by subprocesses. They are application-level checks in the OpenCode tool layer.
A direct file-tool request such as:
write(filePath="/tmp/opencode/x")
can be denied while this succeeds:
node -e 'require("fs").writeFileSync("/tmp/opencode/x","data")'
because the latter exposes only a permitted bash invocation to OpenCode. The actual write occurs later inside Node.
The repository has no focused regression test proving prevention of this bypass—because current design cannot prevent it.
6. Bypass-equivalent paths
All of the following are equivalent once bash is allowed.
Shell-native writes
- >, >>, 2>, &>
- heredocs and here-strings
- tee
- shell built-ins such as printf > path
- command substitution that creates files
- temporary files generated by shell utilities
Guidance discourages these but does not enforce them:
- /home/alik/workspace/agent_template/codexteam/.agents/capabilities/tools.md:44
- /home/alik/workspace/agent_template/codexteam/.agents/skills/subagent-orchestration.md:185
- /home/alik/workspace/agent_template/codexteam/AGENTS.md:79
File utilities
- cp
- mv
- install
- rsync
- tar -C
- dd
- truncate
- touch
- mkdir
- rm
- ln and symlink creation
- archive extraction
mv can both write a destination and delete/rename a source outside audited roots.
Language runtimes
- Node fs.writeFile*, streams, rename, copy, mkdir
- Python open, pathlib, shutil, os.rename
- Ruby, Perl, PHP, Java, Go programs
- inline scripts, scripts read from stdin, or scripts already present
- native FFI/syscall wrappers
Path strings can be computed dynamically, defeating token-level path analysis.
Subprocess chains
- sh -c
- bash -c
- Node/Python spawning another child
- build tools invoking compilers/linkers
- a helper binary that writes to a compiled-in path
- setsid, daemonization, or service launch
The launcher starts OpenCode in a process group and can signal it on timeout, but:
- it does not kill all descendants after every successful turn;
- a child can create a new session/process group and escape later group signaling;
- ordinary background processes may remain after OpenCode exits.
Compiler and build outputs
Examples include:
- go build -o /tmp/...
- GOCACHE=/tmp/...
- cargo target directories
- C/C++ object and linker outputs
- Java class/jar outputs
- TypeScript/Babel/Webpack outputs
- package-manager caches
- test coverage and profiling files
Historical proof:
- /home/alik/workspace/agent_template/codexteam/projects/git_gui/.codexteam/runtime/sessions/git_gui/T317/att-001/turns/003-feedback.jsonl
It records a successful Go build to:
/tmp/opencode/t317-git-gui
Browser state
A browser can create:
- user-data profiles
- cache and GPU cache
- crash databases
- logs
- downloads
- screenshots
- temporary files
- extension state
Historical examples:
- /home/alik/workspace/agent_template/codexteam/projects/git_gui/.codexteam/runtime/sessions/git_gui/T319/att-001/turns/005-feedback.jsonl
- /home/alik/workspace/agent_template/codexteam/projects/git_gui/.codexteam/runtime/sessions/git_gui/T319/att-001/turns/007-feedback.jsonl
- /home/alik/workspace/agent_template/codexteam/projects/git_gui/results/m52-t322-testing/REPORT.md
The logs show Chrome profiles under /tmp/opencode, and crashpad state under the attempt’s XDG configuration tree.
A worker can also override HOME=/home/alik, as historical commands did, bypassing the launcher’s private HOME convention. Mount containment would be required to make that harmless.
Filesystem aliasing
Additional invisible or misleading paths include:
- writing through an existing workspace symlink to an external target;
- symlink races between snapshot and operation;
- hard-linked files, where an audited workspace hash changes but collateral mutation outside the workspace is not identified;
- bind mounts or mounted paths visible to the host user.
snapshot_workspace() records a directory symlink’s target string but does not follow it. Writing through an unchanged symlink can therefore leave no workspace snapshot delta.
7. Private HOME/XDG state
OpenCode receives private environment paths:
- opencode_backend.py:environment()
- backend_adapter.py:OpenCodeBackendAdapter.environment()
It sets:
- HOME
- XDG_CONFIG_HOME
- XDG_DATA_HOME
- XDG_STATE_HOME
- XDG_CACHE_HOME
- OPENCODE_CONFIG
- integration-disabling flags
This usefully isolates normal OpenCode state and disables inherited configuration, but it is not a security boundary:
- shell commands can override the variables;
- absolute paths remain available;
- child processes retain normal host access;
- the private directories themselves are writable from worker shell commands.
8. Workspace snapshots and post-turn audit
Core symbols:
- spawn.py:snapshot_workspace()
- changed_workspace_paths()
- _workspace_change_actions()
- role_boundary_errors()
- _merge_worker_change_manifest()
- _accepted_product_paths()
- _accepted_checkpoint()
- _ensure_accepted_checkpoint()
Per-turn flow is in spawn.py:run_spawn():
1. Snapshot workspace.
2. Snapshot each additional write root.
3. Run OpenCode.
4. Snapshot both again.
5. Compare content hashes.
6. Apply RolePolicy and task-write-scope checks.
7. Mark forbidden changes correction_needed.
Tests include:
- test_forbidden_tester_write_requires_correction
- test_declared_task_write_scope_rejects_role_allowed_out_of_scope_change
- test_additional_write_root_changes_are_audited
- test_workspace_snapshot_keeps_control_paths_for_role_boundary_auditing
- test_opencode_worker_change_manifest_uses_attempt_baseline
- test_opencode_restored_baseline_bytes_remove_net_change
- test_opencode_workspace_baseline_digest_is_pinned
- test_opencode_worker_cannot_repin_mutated_workspace_baseline
What is detected
Within scanned roots, it detects net:
- file creation
- file deletion
- content modification
- changed symlink target
It can reject:
- role-forbidden project paths;
- paths outside Task Write Scope;
- most mutations in explicit additional roots;
- tampering with the private workspace-baseline file;
- changes to the ExecutionSpec;
- changed accepted report/evidence bytes before finalization.
What is not reverted
For ordinary revision/draft boundary violations, the launcher marks correction_needed but generally leaves mutations in place.
This behavior is documented:
- /home/alik/workspace/agent_template/codexteam/.agents/skills/subagent-orchestration.md:115
What is invisible even inside scanned roots
The snapshot hashes file contents only. It does not represent:
- empty directory creation/deletion;
- mode/permission changes;
- owner/group changes;
- timestamps;
- ACLs;
- xattrs;
- capabilities;
- sparse-layout changes;
- file flags;
- same-byte replacement;
- process creation or surviving daemons;
- sockets, listeners, IPC, or signals;
- transient create/use/delete operations completed between snapshots;
- writes followed by restoration to the original bytes;
- external effects reached through an unchanged symlink;
- network effects.
Excluded workspace trees
WORKSPACE_SCAN_EXCLUDES:
(".git", ".codexteam/runtime")
Therefore arbitrary changes under these roots are absent from the general workspace audit.
Some specific private objects receive separate integrity checks:
- delegation digest
- ExecutionSpec
- AgentSpec snapshot
- workspace baseline
- accepted artifact/evidence digests
But there is no complete .codexteam/runtime mutation audit. Role-policy or guidance material not covered by a specific post-run check can be changed without appearing in changed_paths; some will only fail when later reloaded.
All .git mutations are invisible to the workspace snapshot. Role policy says .git/** is denied, but this cannot be enforced by an audit that excludes .git.
9. Additional write roots
Additional roots are:
- explicitly supplied by --add-dir;
- normalized with ensure_existing_workspace();
- pinned in ExecutionSpec;
- restored for continuation;
- allowed in generated external_directory;
- independently snapshotted before and after turns.
Relevant tests:
- test_continuation_restores_additional_write_roots_from_execution_spec
- test_additional_write_root_changes_are_audited
Limitations:
1. Only listed roots are scanned.
2. Their changes are not incorporated into the workspace’s accepted product manifest.
3. Audit errors report relative paths without identifying the originating additional root, making collisions ambiguous.
4. The same workspace-oriented role patterns are applied to additional-root-relative paths.
5. Metadata/transient/symlink bypasses remain.
6. Any unlisted host path remains writable through subprocesses but unaudited.
10. Format-only audit
Format-only is stronger than ordinary mode because bash is denied.
After execution:
- all workspace changes except the report are rejected;
- the previous report bytes are restored on invalid mutation;
- newly created non-report files are removed if they are regular files or symlinks.
Relevant code:
- spawn.py:1081-1086
- spawn.py:1243-1250
- spawn.py:_restore_format_only_report()
Limitations:
- restoration only covers the assigned report and newly created workspace files;
- modified or deleted pre-existing non-report files are not restored;
- created directories are not removed;
- additional roots and all unscanned host paths are not specially restored;
- it still depends on OpenCode honoring bash = deny;
- it is not OS containment.
11. /tmp/opencode
There is no current special /tmp/opencode handling in the launcher.
Current source has no hard-coded /tmp/opencode allowlist, snapshot, cleanup, ownership, or per-attempt namespace.
The only general mechanism that can intentionally authorize it is:
--add-dir /tmp/opencode
Historical project handoffs and runtime records explicitly used it, including:
- /home/alik/workspace/agent_template/codexteam/projects/git_gui/management/tasks/T322.md
- /home/alik/workspace/agent_template/codexteam/projects/git_gui/results/m52-t322-testing/REPORT.md
- /home/alik/workspace/agent_template/codexteam/projects/git_gui/.codexteam/runtime/sessions/git_gui/T317/att-001/turns/003-feedback.jsonl
- /home/alik/workspace/agent_template/codexteam/design/architecture/2026-08-14_opencode_token_and_latency_findings.md:197
Historical /tmp/opencode is shared and broadly populated. That creates:
- cross-attempt observation and overwrite risks;
- stale-artifact confusion;
- collisions;
- accidental reliance on old binaries/profiles;
- no provenance or cleanup guarantee.
Even without --add-dir, shell children can write there if OpenCode’s command parser does not recognize the effective path.
12. Smallest fail-closed remediation
Required design
Wrap the entire OpenCode process and all descendants in an OS filesystem sandbox.
A minimal Linux design:
1. Launch OpenCode through bubblewrap from the host-level execution surface.
2. Read-only bind /.
3. Read-write bind only:
- a per-attempt working workspace;
- explicit --add-dir roots;
- attempt-private OpenCode HOME/XDG state;
- a fresh per-attempt temporary directory mounted as /tmp.
4. Do not bind host /tmp/opencode.
5. Retain host networking if required for 127.0.0.1:11434; filesystem namespaces can be isolated without unsharing the network namespace.
6. Mount immutable launcher inputs read-only:
- OpenCode config;
- ExecutionSpec;
- role-policy snapshot;
- guidance snapshots;
- handoff contract;
- delegation metadata.
7. On timeout or completion, kill the sandbox cgroup/process tree, not merely the original process group.
8. Keep post-turn role/task auditing as defense in depth.
This immediately makes shell redirection, Node/Python, compilers, browsers, and subprocesses obey the same root boundary.
Stronger fail-closed workspace semantics
To ensure forbidden role/task writes never touch the canonical workspace:
1. Give the sandbox a reflink/copy/overlay working tree.
2. Audit its delta against RolePolicy and Task Write Scope.
3. Promote only accepted files atomically into the canonical workspace.
4. Discard the working tree on rejection.
This is the smallest coherent way to make task-path restrictions fail closed. Attempting to bind only individual allowed files is brittle for new files, renames, build tools, and directory-scoped tasks.
Tests that should be added
At minimum, assert that normal shell-capable OpenCode cannot:
- Node-write outside the sandbox;
- Python-write outside the sandbox;
- redirect to an external path;
- cp/mv to an external path;
- emit compiler output externally;
- create browser profiles/logs externally;
- write through a workspace symlink to an external target;
- create a detached process that writes after turn completion;
- modify .git or immutable runtime inputs;
- observe or overwrite another attempt’s temporary directory.
Also verify:
- /tmp is attempt-private;
- /tmp/opencode on the host is neither visible nor writable;
- explicit additional roots work and remain audited;
- Ollama remains reachable;
- rejected workspace deltas are never promoted.
Bottom line
Current controls reliably support detection of many net content changes inside selected roots. They do not enforce a host filesystem write boundary. Any normal OpenCode role with bash effectively has the invoking Unix user’s write authority, modulo OpenCode’s bypassable command inspection. The only complete remediation is OS-level descendant containment, preferably combined with audited staging before canonical workspace promotion.