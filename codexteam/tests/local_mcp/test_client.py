from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

import pytest

from codexteam_tools.local_docs import collect_index, load_config, write_index
from codexteam_tools.local_mcp import (
    LocalMcpClient,
    Mode,
    ServerSpec,
    SidecarError,
    context_server_spec,
    local_docs_server_spec,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FAKE_SERVER = Path(__file__).with_name("fake_stdio_server.py")


def _fake_spec(
    behavior: str = "normal",
    *,
    mode: Mode = Mode.OPTIONAL,
    allowed_tools: frozenset[str] = frozenset({"echo"}),
    max_response_bytes: int = 1_000_000,
) -> ServerSpec:
    return ServerSpec(
        command=(
            sys.executable,
            str(FAKE_SERVER),
            "--behavior",
            behavior,
            "--catalog",
            ",".join(sorted(allowed_tools)),
        ),
        expected_name="fake-local",
        expected_version="1.0",
        allowed_tools=allowed_tools,
        mode=mode,
        timeout_seconds=0.2,
        max_response_bytes=max_response_bytes,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _context_project(tmp_path: Path) -> tuple[Path, Path]:
    projects = tmp_path / "projects"
    project = projects / "demo"
    project.mkdir(parents=True)
    _write(
        project / "CURRENT_TASK.md",
        "# Current Task\n\n- Task ID: T001\n- Status: In Progress\n",
    )
    _write(
        project / "TASKS.md",
        "# Tasks\n\n"
        "| Task ID | Description | Status | Owner | Verification | Evidence |\n"
        "|---|---|---|---|---|---|\n"
        "| T001 | Sidecar | In Progress | developer | Pending | pending |\n",
    )
    _write(
        project / "management/tasks/T001.md",
        "# Task T001: Sidecar\n\n## Objective\n\nExercise context.\n",
    )
    return projects, project


def _local_docs_manifest(tmp_path: Path) -> Path:
    _write(
        tmp_path / "docs/guide.md",
        "# Sidecar Guide\n\nA local MCP sidecar provides bounded offline documentation.\n",
    )
    manifest = tmp_path / "local-docs.toml"
    _write(
        manifest,
        'schema_version = 1\n\n'
        '[index]\npath = "index.sqlite3"\nmax_file_bytes = 100000\nchunk_chars = 600\n\n'
        '[[sources]]\nid = "guide"\nadapter = "text"\nroot = "."\n'
        'version = "test"\ninclude = ["docs/**/*.md"]\nexclude = []\n',
    )
    write_index(collect_index(load_config(manifest)))
    return manifest


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_fake_stdio_call_sanitizes_environment_and_keeps_content_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_API_KEY", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgres://secret.invalid/database")
    monkeypatch.setenv("GIT_ASKPASS", "/tmp/credential-helper")
    monkeypatch.setenv("Path", "/tmp/case-fold-bypass")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    with LocalMcpClient(_fake_spec()) as client:
        availability = client.start()
        result = client.call("echo", {"value": "private query"})

    assert availability.available is True
    assert result.available is True
    assert isinstance(result.content, dict)
    assert result.content["value"] == "private query"
    assert result.content["credential_present"] is False
    assert result.content["proxy_present"] is False
    assert result.content["other_secret_present"] is False
    assert result.content["case_folded_path_present"] is False
    assert result.provenance.source_bytes == 12
    assert result.provenance.cache_hit is False
    serialized = json.dumps(asdict(result.provenance), sort_keys=True)
    assert "private query" not in serialized
    assert "value" not in serialized


def test_request_size_and_encoding_errors_use_sidecar_semantics() -> None:
    with LocalMcpClient(replace(_fake_spec(), max_request_bytes=256)) as client:
        assert client.start().available is True
        too_large = client.call("echo", {"value": "x" * 500})

    cyclic: dict[str, object] = {}
    cyclic["value"] = cyclic
    with LocalMcpClient(_fake_spec()) as client:
        assert client.start().available is True
        invalid = client.call("echo", cyclic)

    assert too_large.available is False
    assert too_large.provenance.error_class == "RequestTooLarge"
    assert invalid.available is False
    assert invalid.provenance.error_class == "ArgumentError"


def test_interleaved_notifications_are_bounded_and_ignored() -> None:
    with LocalMcpClient(_fake_spec("notification")) as client:
        availability = client.start()
        result = client.call("echo", {"value": "ok"})

    assert availability.available is True
    assert result.available is True
    assert isinstance(result.content, dict)
    assert result.content["value"] == "ok"


def test_boolean_response_id_and_empty_tool_result_are_rejected() -> None:
    with LocalMcpClient(_fake_spec("boolean-id")) as client:
        bad_id = client.start()
    with LocalMcpClient(_fake_spec("empty-tool-result")) as client:
        assert client.start().available is True
        empty = client.call("echo", {})

    assert bad_id.available is False
    assert bad_id.provenance.error_class == "ResponseIdError"
    assert empty.available is False
    assert empty.provenance.error_class == "MalformedResponse"


def test_identity_mismatch_does_not_enter_provenance() -> None:
    with LocalMcpClient(_fake_spec("wrong-identity")) as client:
        unavailable = client.start()

    assert unavailable.available is False
    assert unavailable.provenance.error_class == "IdentityError"
    assert unavailable.provenance.server_name == "fake-local"
    assert unavailable.provenance.server_version == "1.0"
    assert unavailable.provenance.server_name != "attacker-controlled"
    assert unavailable.provenance.server_version != "9.9"


def test_allowlist_rejection_is_local_and_structured() -> None:
    with LocalMcpClient(_fake_spec()) as client:
        assert client.start().available is True
        result = client.call("spawn_child", {"secret": "not sent"})

    assert result.available is False
    assert result.content is None
    assert result.provenance.error_class == "AllowlistError"
    assert "secret" not in json.dumps(asdict(result.provenance))


def test_server_may_advertise_additional_tools_without_granting_them() -> None:
    spec = _fake_spec(allowed_tools=frozenset({"echo"}))
    spec = replace(
        spec,
        command=(
            sys.executable,
            str(FAKE_SERVER),
            "--behavior",
            "normal",
            "--catalog",
            "echo,server-added-tool",
        ),
    )
    with LocalMcpClient(spec) as client:
        availability = client.start()
        rejected = client.call("server-added-tool", {"value": "not sent"})

    assert set(availability.tools) == {"echo", "server-added-tool"}
    assert rejected.available is False
    assert rejected.provenance.error_class == "AllowlistError"


def test_allowed_tool_requires_read_only_annotations() -> None:
    spec = _fake_spec(allowed_tools=frozenset({"echo"}))
    command = (
        sys.executable,
        "-c",
        "import json,sys; "
        "req=json.loads(sys.stdin.readline()); "
        "print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':"
        "{'protocolVersion':'2025-11-25','capabilities':{'tools':{}},"
        "'serverInfo':{'name':'fake-local','version':'1.0'}}}),flush=True); "
        "sys.stdin.readline(); req=json.loads(sys.stdin.readline()); "
        "print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':{'tools':["
        "{'name':'echo','inputSchema':{'type':'object'},'annotations':"
        "{'readOnlyHint':False,'destructiveHint':True}}]}}),flush=True)",
    )
    with LocalMcpClient(replace(spec, command=command)) as client:
        unavailable = client.start()

    assert unavailable.available is False
    assert unavailable.provenance.error_class == "ToolCatalogError"


@pytest.mark.parametrize(
    ("behavior", "error_class"),
    [
        ("timeout", "Timeout"),
        ("crash", "EarlyEof"),
        ("malformed", "MalformedResponse"),
        ("oversize", "ResponseTooLarge"),
    ],
)
def test_optional_failures_are_unavailable(behavior: str, error_class: str) -> None:
    max_bytes = 512 if behavior == "oversize" else 1_000_000
    with LocalMcpClient(_fake_spec(behavior, max_response_bytes=max_bytes)) as client:
        result = client.start()

    assert result.available is False
    assert result.provenance.error_class == error_class


def test_required_failure_raises_bounded_sidecar_error() -> None:
    client = LocalMcpClient(_fake_spec("crash", mode=Mode.REQUIRED))
    with pytest.raises(SidecarError) as caught:
        client.start()
    client.close()

    assert str(caught.value) == "MCP sidecar fake-local: EarlyEof"
    assert "Process" not in str(caught.value)


def test_close_terminates_and_reaps_process_group() -> None:
    spec = _fake_spec(allowed_tools=frozenset({"spawn_child"}))
    client = LocalMcpClient(spec)
    client.start()
    parent_pid = client.pid
    child_result = client.call("spawn_child", {})
    assert isinstance(child_result.content, dict)
    child_pid = child_result.content["child_pid"]

    client.close()
    for _ in range(20):
        if not _process_exists(child_pid):
            break
        time.sleep(0.05)

    assert parent_pid is not None
    assert not _process_exists(parent_pid)
    assert not _process_exists(child_pid)


def test_real_bound_context_server_rejects_project_argument(tmp_path: Path) -> None:
    projects, _project = _context_project(tmp_path)
    spec = context_server_spec(
        projects,
        "demo",
        interpreter=sys.executable,
        repository_root=REPOSITORY_ROOT,
        mode=Mode.REQUIRED,
    )
    with LocalMcpClient(spec) as client:
        availability = client.start()
        bound = client.call("get_active_task", {})
        with pytest.raises(SidecarError) as rejected:
            client.call("get_active_task", {"project": "other"})

    active_tool = next(tool for tool in availability.tools if tool == "get_active_task")
    assert active_tool == "get_active_task"
    assert isinstance(bound.content, dict)
    assert bound.content["current"]["task_id"] == "T001"
    assert bound.provenance.source_bytes is not None
    assert bound.provenance.source_bytes > 0
    assert rejected.value.error_class == "ToolError"


def test_real_context_binding_cannot_select_another_project(tmp_path: Path) -> None:
    projects, _project = _context_project(tmp_path)
    other = projects / "other"
    other.mkdir()
    _write(other / "CURRENT_TASK.md", "# Current Task\n\n- Task ID: none\n")
    spec = context_server_spec(
        projects,
        "missing",
        interpreter=sys.executable,
        repository_root=REPOSITORY_ROOT,
    )

    with LocalMcpClient(spec) as client:
        unavailable = client.start()

    assert unavailable.available is False
    assert unavailable.provenance.error_class == "EarlyEof"


def test_real_local_docs_server_catalog_and_search(tmp_path: Path) -> None:
    manifest = _local_docs_manifest(tmp_path)
    spec = local_docs_server_spec(
        manifest,
        interpreter=sys.executable,
        repository_root=REPOSITORY_ROOT,
        mode=Mode.REQUIRED,
    )
    with LocalMcpClient(spec) as client:
        availability = client.start()
        result = client.call("search_docs", {"query": "bounded offline documentation", "limit": 1})

    assert set(availability.tools) == {"list_doc_sources", "search_docs", "read_doc"}
    assert result.available is True
    assert isinstance(result.content, dict)
    assert result.content["matches"][0]["source_id"] == "guide"
    assert result.provenance.cache_hit is True
    assert result.provenance.source_bytes is not None
    assert result.provenance.source_bytes > 0
    assert "bounded offline" not in json.dumps(asdict(result.provenance))


def test_server_spec_contract_is_immutable_and_validated() -> None:
    spec = _fake_spec()
    with pytest.raises(Exception):
        setattr(spec, "timeout_seconds", 10)
    with pytest.raises(ValueError, match="timeout_seconds"):
        replace(spec, timeout_seconds=0)
