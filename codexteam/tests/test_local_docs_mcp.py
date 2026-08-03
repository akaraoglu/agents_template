import ast
import io
import json
import stat
from pathlib import Path

import pytest

import codexteam_tools.local_docs as local_docs_module
import codexteam_tools.local_docs_mcp as local_docs_mcp_module
from codexteam_tools.local_docs import (
    LocalDocsError,
    LocalDocsReader,
    collect_index,
    index_main,
    load_config,
    verify_index,
    write_index,
)
from codexteam_tools.local_docs_mcp import (
    PROTOCOL_VERSION,
    LocalDocsMcpServer,
    modern_meta,
)
from codexteam_tools.paths import PathValidationError
from codexteam_tools.roles import LOCAL_MCP_TOOL_CATALOG


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manifest(
    root: Path,
    *,
    source_root: str = ".",
    includes: tuple[str, ...] = ("docs/**/*.md",),
    extra_sources: str = "",
) -> Path:
    include_lines = ",\n  ".join(json.dumps(item) for item in includes)
    manifest = root / "local-docs.toml"
    _write(
        manifest,
        f"""schema_version = 1

[index]
path = ".codexteam/local-docs.sqlite3"
max_file_bytes = 100000
chunk_chars = 600

[[sources]]
id = "project-docs"
adapter = "text"
root = {json.dumps(source_root)}
version = "test"
include = [
  {include_lines}
]
exclude = []
{extra_sources}
""",
    )
    return manifest


def _built_reader(tmp_path: Path) -> tuple[Path, LocalDocsReader]:
    _write(
        tmp_path / "docs" / "guide.md",
        """# Project Guide

## Development Gate

The Development Gate runs focused algorithm tests and an inexpensive smoke test.

## Integration Gate

The Integration Gate runs the Development Gate before independent regression tests.
""",
    )
    manifest = _manifest(tmp_path)
    plan = collect_index(load_config(manifest))
    write_index(plan)
    return manifest, LocalDocsReader(plan.config.index_path)


def _request(
    request_id: int,
    method: str,
    params: dict | None = None,
) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {"_meta": modern_meta(), **(params or {})},
    }


def test_role_policy_local_docs_catalog_matches_server_tools(tmp_path: Path):
    _manifest_path, reader = _built_reader(tmp_path)
    server = LocalDocsMcpServer(reader)

    assert {tool.name for tool in server.tools} == LOCAL_MCP_TOOL_CATALOG[
        "local-docs"
    ]


def test_text_adapter_is_deterministic_and_hard_excludes_runtime(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "docs" / "guide.md", "# Guide\n\nApproved local documentation.")
    _write(
        tmp_path / ".codexteam" / "secret.md",
        "# Secret\n\nThis must never be indexed.",
    )
    manifest = _manifest(tmp_path, includes=("**/*.md",))

    first = collect_index(load_config(manifest))
    second = collect_index(load_config(manifest))

    assert first.sha256 == second.sha256
    assert [item.locator for item in first.documents] == [
        "docs/guide.md#L1"
    ]
    assert "Secret" not in first.documents[0].text
    assert not first.config.index_path.exists()


def test_python_package_adapter_indexes_public_docstrings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(
        tmp_path / "demo_pkg" / "__init__.py",
        '''"""Demo package documentation."""

def public_api():
    """Return a stable public value."""

def _private_api():
    """Do not index this."""
''',
    )
    dist_info = tmp_path / "demo_local_docs-1.2.3.dist-info"
    _write(
        dist_info / "METADATA",
        "Metadata-Version: 2.1\nName: demo-local-docs\nVersion: 1.2.3\n",
    )
    _write(
        dist_info / "RECORD",
        "demo_pkg/__init__.py,,\n"
        "demo_local_docs-1.2.3.dist-info/METADATA,,\n"
        "demo_local_docs-1.2.3.dist-info/RECORD,,\n",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    _write(tmp_path / "docs" / "guide.md", "# Guide\n\nProject documentation.")
    manifest = _manifest(
        tmp_path,
        extra_sources="""

[[sources]]
id = "python-demo"
adapter = "python-package"
distribution = "demo-local-docs"
""",
    )

    plan = collect_index(load_config(manifest))
    python_docs = [
        document
        for document in plan.documents
        if document.source_id == "python-demo"
    ]

    assert {document.section for document in python_docs} == {
        "<module>",
        "public_api",
    }
    assert all(document.version == "1.2.3" for document in python_docs)
    assert "_private_api" not in " ".join(document.text for document in python_docs)


def test_update_verify_search_and_read_are_bounded(tmp_path: Path) -> None:
    manifest, reader = _built_reader(tmp_path)
    plan = collect_index(load_config(manifest))

    verified = verify_index(plan)
    assert verified["verified"] is True
    assert stat.S_IMODE(plan.config.index_path.stat().st_mode) == 0o600

    sources = reader.list_doc_sources()
    assert sources["sources"][0]["id"] == "project-docs"
    assert sources["sources"][0]["version"] == "test"

    searched = reader.search_docs(
        "Development Gate smoke test",
        source_ids=["project-docs"],
        version="test",
        limit=2,
    )
    assert searched["matches"][0]["section"] == "Development Gate"
    assert searched["matches"][0]["matched_terms"] == 4
    match = searched["matches"][0]

    read = reader.read_doc(
        match["source_id"],
        match["locator"],
        max_chars=200,
    )
    assert len(read["content"]) <= 200
    assert read["source_id"] == "project-docs"
    assert read["sha256"] == match["sha256"]

    absent = reader.search_docs("React hooks", limit=3)
    assert absent["matches"] == []
    assert absent["minimum_match_terms"] == 2


def test_live_reader_uses_replaced_index_content_and_matching_digest(
    tmp_path: Path,
) -> None:
    manifest, reader = _built_reader(tmp_path)
    original = reader.search_docs("Development Gate", limit=1)
    _write(
        tmp_path / "docs" / "guide.md",
        """# Project Guide

## Role-filtered context

Workers receive bounded context tools without broad repository discovery.
""",
    )
    updated = collect_index(load_config(manifest))
    write_index(updated)

    searched = reader.search_docs("bounded context tools", limit=1)
    sources = reader.list_doc_sources()
    match = searched["matches"][0]
    read = reader.read_doc(match["source_id"], match["locator"])

    assert updated.sha256 != original["index_sha256"]
    assert searched["index_sha256"] == updated.sha256
    assert sources["index_sha256"] == updated.sha256
    assert read["index_sha256"] == updated.sha256
    assert "broad repository discovery" in read["content"]


def test_reader_rejects_unapproved_source_locator_and_bounds(
    tmp_path: Path,
) -> None:
    _, reader = _built_reader(tmp_path)

    with pytest.raises(LocalDocsError, match="unknown source ids"):
        reader.search_docs("gate", source_ids=["missing-source"])
    with pytest.raises(LocalDocsError, match="unknown document locator"):
        reader.read_doc("project-docs", "../../secret")
    with pytest.raises(LocalDocsError, match="max_chars"):
        reader.read_doc("project-docs", "docs/guide.md#L1", max_chars=10)
    with pytest.raises(LocalDocsError, match="limit"):
        reader.search_docs("gate", limit=100)


def test_manifest_and_text_sources_reject_symlinks_and_traversal(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.md"
    _write(outside, "# Outside\n\nNot approved.")
    link = tmp_path / "docs" / "link.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    manifest = _manifest(tmp_path)

    with pytest.raises(LocalDocsError, match="symlinked documentation"):
        collect_index(load_config(manifest))

    link.unlink()
    escaped = _manifest(tmp_path, source_root="../")
    with pytest.raises(PathValidationError):
        collect_index(load_config(escaped))


def test_index_cli_previews_by_default_and_updates_only_explicitly(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write(tmp_path / "docs" / "guide.md", "# Guide\n\nPreview first.")
    manifest = _manifest(tmp_path)
    index_path = tmp_path / ".codexteam" / "local-docs.sqlite3"

    assert index_main(["--manifest", str(manifest), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "preview"
    assert not index_path.exists()

    assert index_main(
        ["--manifest", str(manifest), "--update", "--json"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["action"] == "updated"
    assert index_path.is_file()

    assert index_main(
        ["--manifest", str(manifest), "--verify", "--json"]
    ) == 0
    assert json.loads(capsys.readouterr().out)["verified"] is True


def test_mcp_exposes_exactly_three_read_only_tools_and_never_writes(
    tmp_path: Path,
) -> None:
    manifest, reader = _built_reader(tmp_path)
    index_path = load_config(manifest).index_path
    server = LocalDocsMcpServer(reader)
    before = index_path.read_bytes()

    listed = server.handle(_request(1, "tools/list"))
    tools = listed["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "list_doc_sources",
        "search_docs",
        "read_doc",
    ]
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
    assert all(not tool["annotations"]["destructiveHint"] for tool in tools)
    assert all(tool["inputSchema"]["additionalProperties"] is False for tool in tools)
    assert "Do not guess source IDs" in local_docs_mcp_module.SERVER_INSTRUCTIONS
    assert "limit of at most 5" in local_docs_mcp_module.SERVER_INSTRUCTIONS

    searched = server.handle(
        _request(
            2,
            "tools/call",
            {
                "name": "search_docs",
                "arguments": {"query": "Integration Gate", "limit": 1},
            },
        )
    )
    assert searched["result"]["isError"] is False
    assert searched["result"]["structuredContent"]["query_stats"]["cache_hit"] is True
    assert searched["result"]["structuredContent"]["query_stats"]["returned_bytes"] > 0
    assert index_path.read_bytes() == before


def test_stdio_protocol_is_newline_delimited_and_legacy_compatible(
    tmp_path: Path,
) -> None:
    _, reader = _built_reader(tmp_path)
    server = LocalDocsMcpServer(reader)
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    input_stream = io.StringIO(
        "".join(json.dumps(request) + "\n" for request in requests)
    )
    output_stream = io.StringIO()

    assert server.serve(input_stream, output_stream) == 0
    responses = [
        json.loads(line) for line in output_stream.getvalue().splitlines()
    ]
    assert responses[0]["result"]["protocolVersion"] == "2025-11-25"
    assert len(responses[1]["result"]["tools"]) == 3
    assert PROTOCOL_VERSION == "2026-07-28"


def test_mcp_argument_errors_are_actionable(tmp_path: Path) -> None:
    _, reader = _built_reader(tmp_path)
    server = LocalDocsMcpServer(reader)

    response = server.handle(
        _request(
            1,
            "tools/call",
            {
                "name": "search_docs",
                "arguments": {"query": "gate", "extra": True},
            },
        )
    )

    assert response["result"]["isError"] is True
    assert "unknown arguments" in response["result"]["content"][0]["text"]


def test_runtime_modules_have_no_network_or_subprocess_imports() -> None:
    forbidden = {"http", "requests", "socket", "subprocess", "urllib"}
    for module in (local_docs_module, local_docs_mcp_module):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        assert imported.isdisjoint(forbidden)
