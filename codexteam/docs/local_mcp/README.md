# Local MCP Sidecar

This package is a bounded local client for calling the existing
`scripts/team-context-mcp.py` and `scripts/local-docs-mcp.py` servers over local,
newline-delimited JSON-RPC STDIO. It is not registered with a host. The current
OpenCode adapter uses it only for optional, project-bound canonical task context;
it is not lifecycle or verification authority.

## Boundary

The sidecar starts only an explicit command with `shell=False`. It inherits a
minimal inherited environment plus explicit non-sensitive overrides, creates a
new process session, permits one request at a time, and terminates and reaps
the process group on close. It has no network or remote-MCP support, daemon,
framework, retry loop, or additional dependency. These controls reduce
accidental exposure but do not create a complete sandbox: the selected local
server still has the operating-system access of the calling user. Enterprise
deployment would require an approved execution and policy boundary beyond this
experiment.

## Contracts And Failure Modes

`ServerSpec` is frozen and declares the exact command, expected server identity
and version, allowed tools, `optional` or `required` mode, request timeout,
maximum request and newline response sizes, environment additions, and working
directory.
The client performs legacy MCP initialization with protocol `2025-11-25`, then
validates that every allowed tool appears in `tools/list` before allowing
`tools/call`. Additional advertised tools remain unavailable unless the spec
explicitly allows them, so a compatible server addition does not block a task.

Malformed JSON, JSON-RPC errors, identity or catalog mismatches, early EOF,
process crashes, timeouts, and oversized responses are classified without
including server output. Optional failures return `available=False`; required
failures raise a bounded `SidecarError`. There are no retries.

## Usage

```python
from codexteam_tools.local_mcp import LocalMcpClient, context_server_spec

spec = context_server_spec("/home/alik/workspace/codexspace/projects", "my-project")
with LocalMcpClient(spec) as client:
    availability = client.start()
    result = client.call("get_active_task", {})
```

Context builders bind `CODEXTEAM_CONTEXT_PROJECT`; normal bound calls have no
project selector. The local-docs builder takes an existing manifest whose index
has already been built. Builders accept explicit interpreter, server script,
extra arguments, and repository root values.

## Privacy And Provenance

Returned content is separate from `Provenance`. Provenance contains only server
name/version, tool name, elapsed duration, response bytes, source bytes and
cache status when the server returns those statistics, and an error class. It
never stores query arguments or response content. Callers remain responsible
for handling returned content according to local data policy.

## Canary

The read-only canary starts both real servers, validates their catalogs, makes
one bound context call and one bounded documentation search, and prints a JSON
summary without response content:

```bash
PYTHONPATH=src python -B scripts/local-mcp-canary.py \
  --projects-root /home/alik/workspace/codexspace/projects \
  --project PROJECT_ID \
  --local-docs-manifest ./local-docs.toml
```

The context project and local-docs index must already exist. The canary makes no
writes.

## Tests

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /home/alik/workspace/agent_template/env-python/bin/python -m pytest \
  -q -p no:cacheprovider tests/local_mcp
```

Tests exercise both real server scripts and tiny subprocess fixtures for
timeouts, crashes, malformed and oversized responses, allowlist enforcement,
mode semantics, project binding, cleanup, limits, and provenance privacy.

## Non-Goals

This client does not generate schemas, replace an MCP server, register a host
integration, provide remote MCP, or build an operational service. It does not
prove verification, acceptance, closure, or Git authority.
