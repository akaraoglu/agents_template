# Local Documentation MCP

`local-docs` is an offline, read-only MCP server for bounded documentation
retrieval. It is separate from `codexteam-context`: one serves approved
documentation, while the other serves live CodexTeam project state.

## Contract

The permanent MCP surface has three tools:

| Tool | Purpose |
|---|---|
| `list_doc_sources` | List approved sources, installed versions, and index provenance |
| `search_docs` | Return ranked bounded excerpts and exact locators |
| `read_doc` | Read one bounded section by a locator returned from the index |

The MCP process opens SQLite with `mode=ro`. It has no indexing, file mutation,
network, shell, arbitrary-path, or subprocess tool.

## Indexing

`local-docs.toml` declares the ignored SQLite index and approved source
adapters. The indexer defaults to preview and writes only with `--update`:

```bash
../env-python/bin/python scripts/local-docs-index.py --manifest local-docs.toml
../env-python/bin/python scripts/local-docs-index.py --manifest local-docs.toml --update
../env-python/bin/python scripts/local-docs-index.py --manifest local-docs.toml --verify
```

Updates collect sources in stable order, split bounded sections, compute one
content digest, build a temporary SQLite FTS5 database, set mode `0600`, and
atomically replace the ignored index. Verification recomputes approved local
sources and compares metadata without modifying the index. Each MCP query reads
the digest and documents through the same read-only connection, so a long-running
server cannot pair new content with provenance cached before an atomic update.

## Source Adapters

- `text`: UTF-8 Markdown, reStructuredText, and text beneath one manifest-local
  approved root. Globs cannot traverse, and Git, runtime, cache, archive, and
  dependency directories are always excluded.
- `python-package`: public module, class, function, and method docstrings from a
  named installed distribution. The adapter reads distribution metadata and
  parses source with `ast`; it does not import package code.

New coverage should normally add an adapter or manifest source without adding
an MCP tool. Adapters must remain offline, deterministic, bounded, and covered
by representative and negative tests.

## Security

- STDIO transport only; no listening port.
- No network-capable or subprocess imports in the runtime modules.
- No arbitrary paths in tool arguments.
- Text roots remain beneath the manifest directory and reject symlinks.
- Python sources are limited to named installed distributions.
- The ignored index contains documentation only and is mode `0600`.
- Tool responses are capped and carry source, version, locator, content hash,
  index hash, and byte counts.
- Tool telemetry may record counts and sizes, never queries or content.

Local MCP output is still placed in the configured model's context. The local
boundary removes an additional documentation-service data flow; it does not
change the Codex model-provider boundary.

## Deployment

Global Codex registration points to the fixed interpreter, script, and
manifest:

```bash
codex mcp add local-docs -- \
  /home/alik/workspace/agent_template/env-python/bin/python \
  /home/alik/workspace/agent_template/codexteam/scripts/local-docs-mcp.py \
  --manifest /home/alik/workspace/agent_template/codexteam/local-docs.toml
```

CodexTeam allows the server for Architect and Developer only. Other roles keep
their existing MCP boundaries, and existing attempts retain their pinned
allowlist and guidance.

Validate before registration or role rollout:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  ../env-python/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_local_docs_mcp.py
../env-python/bin/python scripts/local-docs-index.py \
  --manifest local-docs.toml --verify
```

## Measured Pilot

The 2026-07-30 direct canary returned one 1,124-byte Flask result in 3.705 ms.
A subsequent two-task matched A/B pilot used the same model, read-only sandbox,
prompt, fixed interpreter fallback, and disabled unrelated MCP servers:

| Task | Path | Tool calls | Seconds | Input | Output |
|---|---|---:|---:|---:|---:|
| Flask cache behavior | fixed-interpreter shell | 3 | 37.0 | 87,937 | 2,048 |
| Flask cache behavior | `local-docs` | 1 | 17.7 | 48,888 | 760 |
| pytest nested groups | fixed-interpreter shell | 3 | 34.1 | 90,038 | 1,769 |
| pytest nested groups | `local-docs` | 1 | 19.4 | 48,388 | 693 |

All four bounded answers were correct. In aggregate, `local-docs` reduced tool
calls from six to two, latency from 71.1 to 37.1 seconds, input from 177,975 to
97,276 tokens, and output from 3,817 to 1,453 tokens. Uncached input fell from
31,287 to 26,876 tokens; most of the total-input reduction came from avoiding
repeated cached model cycles.

The pilot also found two orchestration constraints:

- A generic turn did not select the MCP merely because it was registered and
  entered a broad shell-discovery loop. Architect and Developer guidance is
  therefore part of the treatment, not optional documentation.
- Guessing a source ID caused retries. Server and role guidance now say to omit
  an unknown source filter, use a first limit of at most five, and call
  `list_doc_sources` only when an exact filter is required.

These results support the current Architect and Developer rollout. They do not
justify adding more roles or sources until real development attempts show the
same reduction.
