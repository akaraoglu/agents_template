from __future__ import annotations

import json
from pathlib import Path

import pytest

from codexteam_tools.v2.qualification import MUSE_OLLAMA_DIGEST, run_muse_qualification


class Response:
    def __init__(self, value) -> None:
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.value).encode("utf-8")


def metadata(url: str):
    if url.endswith("/api/tags"):
        return {"models": [{"name": "muse-glimmer:30b", "digest": MUSE_OLLAMA_DIGEST}]}
    if url.endswith("/api/show"):
        return {
            "details": {"family": "muse-glimmer"},
            "model_info": {"muse-glimmer.context_length": 131072},
            "capabilities": ["completion", "tools", "thinking", "vision"],
        }
    raise AssertionError(url)


class FakeAdapter:
    expected_version = "1.18.16"

    def __init__(self, catalog, root: Path, *, fail_metadata: bool = False) -> None:
        self.catalog = catalog
        self.root = root
        self.fail_metadata = fail_metadata
        self._configs = {}
        self.calls = []

    def preflight(self, role, _pack, _root):
        model = {
            "id": "muse-glimmer:30b", "name": "Muse Glimmer 30B local",
            "family": "muse-glimmer", "attachment": True, "reasoning": True,
            "tool_call": True, "interleaved": "reasoning", "temperature": True,
            "limit": {"context": 131072, "input": 114688, "output": 16384},
            "modalities": {"input": ["text", "image"], "output": ["text"]},
        }
        if self.fail_metadata:
            del model["reasoning"]
        self._configs[role.role_instance_id] = ({
            "provider": {"ollama": {"models": {"muse-glimmer:30b": model}}}
        }, "a" * 64)

    def _runtime(self, _root, role):
        path = self.root / ".runtime" / role.role_instance_id
        (path / "config/opencode").mkdir(parents=True, exist_ok=True)
        return path

    def qualification_turn(self, role, root, prompt, stem, *, agent, context_digest, session_id=None):
        del role, context_digest
        self.calls.append((stem, agent, session_id))
        evidence = {}
        if stem == "qualification-text":
            value, tools, session = {"summary": "READY", "notes": []}, (), "ses-text"
        elif stem == "qualification-read":
            value = {"summary": "Muse qualification fixture.", "notes": []}
            tools, session = ({"tool": "read", "input": {"filePath": "README.md"}, "status": "completed"},), "ses-read"
        elif stem == "qualification-write":
            target = root / "project/src/qualified.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("QUALIFIED\n")
            value, tools, session = {"summary": "WROTE", "notes": []}, (), "ses-write"
        else:
            value = {"summary": "QUALIFIED", "notes": []}
            tools, session = ({"tool": "read", "input": {"filePath": "src/qualified.txt"}, "status": "completed"},), session_id
        return {"session_id": session, "value": value, "tools": tools, "evidence": evidence}


def direct_opener(overrides=None, calls=None):
    overrides = overrides or {}
    calls = calls if calls is not None else []

    def open_request(request, **_kwargs):
        calls.append(request)
        value = metadata(request.full_url) if "/api/" in request.full_url else None
        if value is not None:
            return Response(value)
        body = json.loads(request.data)
        prompt = body["messages"][0]["content"]
        if "JSON object" in prompt:
            message, finish = {"content": '{"status":"READY"}'}, "stop"
        elif "Think through" in prompt:
            message, finish = {"content": "READY", "reasoning_content": "private reasoning"}, "stop"
        elif "Call get_magic_number" in prompt:
            message, finish = {"content": "", "tool_calls": [{
                "function": {"name": "get_magic_number", "arguments": '{"seed":7}'},
            }]}, "tool_calls"
        else:
            message, finish = {"content": "READY", "reasoning_content": "private reasoning"}, "stop"
        key = next((name for name in overrides if name in prompt), None)
        if key is not None:
            message, finish = overrides[key]
        return Response({"choices": [{"message": message, "finish_reason": finish}]})

    return open_request


def run(tmp_path, *, overrides=None, include_opencode=False, fail_metadata=False, calls=None):
    holder = {}

    def factory(catalog):
        holder["adapter"] = FakeAdapter(catalog, tmp_path / "qualification", fail_metadata=fail_metadata)
        return holder["adapter"]

    result = run_muse_qualification(
        workspace=tmp_path / "qualification",
        include_opencode=include_opencode,
        opener=direct_opener(overrides, calls),
        adapter_factory=factory,
        timeout_seconds=10,
    )
    return result, holder["adapter"]


def test_direct_qualification_passes_and_redacts_reasoning(tmp_path) -> None:
    calls = []
    result, adapter = run(tmp_path, calls=calls)
    assert result.verdict == "QUALIFIED"
    assert adapter.calls == []
    checks = {item.check_id: item for item in result.checks}
    assert checks["direct.text"].observations["reasoning_chars"] > 0
    assert "private reasoning" not in json.dumps(result.as_dict())
    budgets = [json.loads(call.data)["max_tokens"] for call in calls if call.full_url.endswith("/chat/completions")]
    assert budgets == [512, 1024, 512, 2048]


@pytest.mark.parametrize(
    ("override", "failed"),
    [
        ({"Reply with exactly": ({"content": "", "reasoning_content": "x" * 32}, "length")}, "direct.text"),
        ({"Think through": ({"content": "READY", "reasoning_content": ""}, "stop")}, "direct.thinking"),
        ({"JSON object": ({"content": "not-json"}, "stop")}, "direct.json"),
        ({"Call get_magic_number": ({"content": "", "tool_calls": [{"function": {"name": "other", "arguments": "{}"}}]}, "tool_calls")}, "direct.tool_call"),
        ({"Reply with exactly": ({"content": "READY"}, "unknown")}, "direct.text"),
    ],
)
def test_direct_regressions_fail_closed_without_fallback(tmp_path, override, failed) -> None:
    calls = []
    result, adapter = run(tmp_path, overrides=override, include_opencode=True, calls=calls)
    assert result.verdict == "NOT_QUALIFIED"
    assert {item.check_id: item.status for item in result.checks}[failed] == "failed"
    assert adapter.calls == []
    assert len([call for call in calls if call.full_url.endswith("/chat/completions")]) == 4


def test_opencode_checks_use_exact_sessions_and_audit_write(tmp_path) -> None:
    result, adapter = run(tmp_path, include_opencode=True)
    assert result.verdict == "QUALIFIED"
    assert adapter.calls == [
        ("qualification-text", "qualification-text", None),
        ("qualification-read", "qualification-read", None),
        ("qualification-write", "qualification-write", None),
        ("qualification-candidate", "qualification-read", "ses-write"),
    ]
    assert (tmp_path / "qualification/project/src/qualified.txt").read_text() == "QUALIFIED\n"


def test_metadata_failure_prevents_all_model_calls(tmp_path) -> None:
    calls = []
    result, adapter = run(tmp_path, include_opencode=True, fail_metadata=True, calls=calls)
    assert result.verdict == "NOT_QUALIFIED"
    assert not [call for call in calls if call.full_url.endswith("/chat/completions")]
    assert adapter.calls == []


def test_dry_run_has_no_model_calls_and_writes_result(tmp_path) -> None:
    calls = []
    result, adapter = run_muse_qualification(
        workspace=tmp_path / "dry",
        include_opencode=True,
        dry_run=True,
        opener=direct_opener(calls=calls),
        adapter_factory=lambda catalog: FakeAdapter(catalog, tmp_path / "dry"),
        timeout_seconds=10,
    ), None
    assert result.verdict == "DRY_RUN"
    assert not [call for call in calls if call.full_url.endswith("/chat/completions")]
    assert all(item.status in {"passed", "planned"} for item in result.checks)
    assert (tmp_path / "dry/qualification-result.json").is_file()


def test_dry_run_does_not_mask_metadata_failure(tmp_path) -> None:
    result = run_muse_qualification(
        workspace=tmp_path / "dry-failure",
        dry_run=True,
        opener=direct_opener(),
        adapter_factory=lambda catalog: FakeAdapter(
            catalog, tmp_path / "dry-failure", fail_metadata=True
        ),
        timeout_seconds=10,
    )
    assert result.verdict == "NOT_QUALIFIED"
