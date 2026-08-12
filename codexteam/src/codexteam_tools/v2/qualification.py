from __future__ import annotations

import hashlib
import json
import re
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .canonical import canonical_sha256
from .canary import FIXED_TIME
from .catalog import Catalog, load_catalog
from .compiler import build_role_instance, compile_pipeline
from .evidence import derive_change_set, workspace_manifest
from .models import (
    AcceptanceCriterion,
    ActorRef,
    Assignment,
    ContextPack,
    EvidenceType,
    LeadDecision,
    PipelineRevision,
    WorkItem,
)
from .pipeline_runtime import PipelineRuntime
from .runtime.base import RuntimeModel
from .runtime.base import opencode_execution_attestation
from .runtime.opencode import (
    DEFAULT_OLLAMA_ENDPOINT,
    DEFAULT_OPENCODE_EXECUTABLE,
    DEFAULT_OPENCODE_MODEL,
    MUSE_CONTEXT_LIMIT,
    MUSE_OLLAMA_DIGEST,
    OpenCodeRuntimeAdapter,
    QUALIFICATION_READ_AGENT,
    QUALIFICATION_TEXT_AGENT,
    QUALIFICATION_WRITE_AGENT,
)
from .storage import V2ProjectStore


CheckStatus = Literal["passed", "failed", "skipped", "planned"]


class QualificationCheck(RuntimeModel):
    check_id: str = Field(min_length=1)
    required: bool = True
    status: CheckStatus
    duration_ms: int = Field(ge=0)
    summary: str = Field(min_length=1)
    evidence_paths: tuple[str, ...] = ()
    observations: dict[str, Any] = Field(default_factory=dict)


class MuseQualificationResult(RuntimeModel):
    schema_version: Literal["2.0"] = "2.0"
    kind: Literal["muse_qualification"] = "muse_qualification"
    model: Literal["muse-glimmer:30b"] = "muse-glimmer:30b"
    model_digest: str = MUSE_OLLAMA_DIGEST
    workspace: str
    started_at: str
    duration_ms: int = Field(ge=0)
    mode: Literal["direct-only", "opencode"]
    dry_run: bool
    checks: tuple[QualificationCheck, ...]
    verdict: Literal["QUALIFIED", "NOT_QUALIFIED", "DRY_RUN"]

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


_Open = Callable[..., Any]
_AdapterFactory = Callable[[Catalog], OpenCodeRuntimeAdapter]
_EXPECTED_MUSE_MODEL_FIELDS = {
    "family": "muse-glimmer",
    "attachment": True,
    "reasoning": True,
    "tool_call": True,
    "interleaved": "reasoning",
    "temperature": True,
    "limit": {"context": 131072, "input": 114688, "output": 16384},
    "modalities": {"input": ["text", "image"], "output": ["text"]},
}


def _bounded(value: str, limit: int = 80) -> str:
    compact = " ".join(value.split())
    return compact[:limit]


def _reasoning_evidence(value: str) -> dict[str, Any]:
    return {
        "reasoning_chars": len(value),
        "reasoning_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }


def _json_object(value: str) -> dict[str, Any]:
    candidate = value.strip()
    if candidate.startswith("```"):
        match = re.fullmatch(r"```json\r?\n(.*)\r?\n```", candidate, re.DOTALL)
        if match is None:
            raise ValueError("response is not raw JSON or one exact json fence")
        candidate = match.group(1)
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("response JSON is not an object")
    return parsed


def _request_json(
    opener: _Open,
    url: str,
    *,
    timeout: int,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="GET" if payload is None else "POST",
        headers={} if payload is None else {"Content-Type": "application/json"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            value = json.load(response)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise RuntimeError(f"request failed: {url}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"response was not an object: {url}")
    return value


def _message(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("completion did not contain one choice")
    message = choices[0].get("message")
    finish = choices[0].get("finish_reason")
    if not isinstance(message, dict) or not isinstance(finish, str):
        raise ValueError("completion omitted message or finish_reason")
    return message, finish


def _direct_payload(prompt: str, max_tokens: int, **extra: Any) -> dict[str, Any]:
    return {
        "model": "muse-glimmer:30b",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "stream": False,
        **extra,
    }


def _work_item() -> WorkItem:
    return WorkItem(
        schema_version="2.0",
        kind="work_item",
        work_item_id="muse-qualification",
        title="Muse Glimmer qualification",
        objective="Qualify strict semantic output and bounded OpenCode tools.",
        acceptance_criteria=(
            AcceptanceCriterion(
                id="qualification", statement="All selected qualification checks pass.",
                required_evidence_types=(EvidenceType.TEST_OUTPUT,),
            ),
        ),
        approved_scope=("project/src/qualified.txt",),
    )


def _lead_decision(subject: Any) -> LeadDecision:
    return LeadDecision(
        schema_version="2.0",
        kind="lead_decision",
        decision_id="decision-muse-qualification",
        decision="approve",
        subject=subject,
        rationale="Authorize the isolated Muse qualification only.",
        decided_by=ActorRef(actor_id="qualification-lead", kind="project_lead"),
        decided_at=FIXED_TIME,
    )


def _role_materials(root: Path, catalog: Catalog) -> dict[str, tuple[Any, ContextPack]]:
    store = V2ProjectStore(root)
    work = _work_item()
    store.write_immutable(work, work.work_item_id)
    compiled = compile_pipeline(
        catalog, work, (), ActorRef(actor_id="qualification-lead", kind="project_lead"), FIXED_TIME,
    )
    projection = PipelineRuntime(store, catalog=catalog).initialize(
        "muse-qualification", compiled.plan, _lead_decision(compiled.refs.plan), created_at=FIXED_TIME,
    )
    revision = store.resolve(projection.pipeline_revision)
    if not isinstance(revision, PipelineRevision):
        raise RuntimeError("qualification pipeline revision was not stored")
    result: dict[str, tuple[Any, ContextPack]] = {}
    for stage_name in ("discovery", "implementation"):
        stage = next(item for item in revision.stages if item.stage == stage_name)
        scope = ("project/src/qualified.txt",) if stage_name == "implementation" else ()
        assignment = Assignment(
            schema_version="2.0",
            kind="assignment",
            assignment_id=f"assignment-qualification-{stage_name}",
            work_item=store.reference(work),
            stage=stage.stage,
            agent_spec=stage.agent_spec,
            scope=scope,
            assurance_domain=stage.assurance_domain,
        )
        assignment_ref = store.write_immutable(assignment, assignment.assignment_id)
        pack = ContextPack(
            schema_version="2.0",
            kind="context_pack",
            context_pack_id=f"context-qualification-{stage_name}",
            assignment=assignment_ref,
            items=(),
            digest=canonical_sha256(()),
        )
        role = build_role_instance(
            catalog,
            assignment=assignment,
            work_item=work,
            pipeline_revision=revision,
            stage_spec=stage,
            attempt_id=f"attempt-qualification-{stage_name}",
            host_isolation_authorization=(
                opencode_execution_attestation() if stage_name == "implementation" else None
            ),
        )
        result[stage_name] = (role, pack)
    return result


def _run_check(check_id: str, action: Callable[[], tuple[str, dict[str, Any], tuple[str, ...]]]) -> QualificationCheck:
    started = time.monotonic()
    try:
        summary, observations, evidence = action()
        status: CheckStatus = "passed"
    except Exception as exc:
        summary = f"{type(exc).__name__}: {_bounded(str(exc), 240)}"
        observations = {}
        evidence = ()
        status = "failed"
    return QualificationCheck(
        check_id=check_id,
        status=status,
        duration_ms=round((time.monotonic() - started) * 1000),
        summary=summary,
        observations=observations,
        evidence_paths=evidence,
    )


def run_muse_qualification(
    *,
    workspace: str | Path | None = None,
    include_opencode: bool = False,
    dry_run: bool = False,
    timeout_seconds: int = 600,
    opener: _Open = urllib.request.urlopen,
    adapter_factory: _AdapterFactory | None = None,
) -> MuseQualificationResult:
    """Run the one-shot Muse gate. There are no retries or model fallbacks."""
    if timeout_seconds < 1:
        raise ValueError("timeout must be positive")
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    started = time.monotonic()
    requested = Path(workspace).absolute() if workspace is not None else None
    root = requested or Path(tempfile.mkdtemp(prefix="codexteam-v2-muse-qualification-"))
    if root.exists() and any(root.iterdir()):
        raise ValueError("qualification workspace must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    product = root / "project"
    product.mkdir()
    (product / "README.md").write_text("Muse qualification fixture.\n", encoding="utf-8")
    checks: list[QualificationCheck] = []
    endpoint = DEFAULT_OLLAMA_ENDPOINT.rstrip("/")

    def metadata() -> tuple[str, dict[str, Any], tuple[str, ...]]:
        tags = _request_json(opener, f"{endpoint}/api/tags", timeout=min(timeout_seconds, 10))
        matches = [
            item for item in tags.get("models", [])
            if isinstance(item, dict) and item.get("name") == "muse-glimmer:30b"
        ]
        if len(matches) != 1 or matches[0].get("digest") != MUSE_OLLAMA_DIGEST:
            raise ValueError("exact Muse tag and digest were not present")
        show = _request_json(
            opener, f"{endpoint}/api/show", timeout=min(timeout_seconds, 10),
            payload={"model": "muse-glimmer:30b"},
        )
        details = show.get("details")
        info = show.get("model_info")
        capabilities = show.get("capabilities")
        contexts = [
            value for key, value in (info.items() if isinstance(info, dict) else ())
            if (key == "context_length" or key.endswith(".context_length"))
        ]
        if (
            not isinstance(details, dict)
            or details.get("family") != "muse-glimmer"
            or contexts != [MUSE_CONTEXT_LIMIT]
            or not isinstance(capabilities, list)
            or set(capabilities) != {"completion", "tools", "thinking", "vision"}
        ):
            raise ValueError("Muse family, context, or capabilities differ from the pinned profile")
        return "Exact Ollama Muse metadata matched.", {
            "digest": MUSE_OLLAMA_DIGEST,
            "family": "muse-glimmer",
            "context": MUSE_CONTEXT_LIMIT,
            "capabilities": sorted(capabilities),
        }, ()

    checks.append(_run_check("metadata.ollama", metadata))
    catalog = load_catalog(Path(__file__).resolve().parents[3] / "v2")
    adapter: OpenCodeRuntimeAdapter | None = None
    read_role = read_pack = write_role = write_pack = None

    def opencode_metadata() -> tuple[str, dict[str, Any], tuple[str, ...]]:
        nonlocal adapter, read_role, read_pack, write_role, write_pack
        materials = _role_materials(root, catalog)
        read_role, read_pack = materials["discovery"]
        write_role, write_pack = materials["implementation"]
        adapter = adapter_factory(catalog) if adapter_factory else OpenCodeRuntimeAdapter(
            catalog=catalog,
            executable=DEFAULT_OPENCODE_EXECUTABLE,
            model=DEFAULT_OPENCODE_MODEL,
            timeout_seconds=timeout_seconds,
            overall_timeout_seconds=timeout_seconds * 4,
        )
        adapter.preflight(read_role, read_pack, root)
        adapter.preflight(write_role, write_pack, root)
        read_config, _ = adapter._configs[read_role.role_instance_id]
        model = read_config["provider"]["ollama"]["models"]["muse-glimmer:30b"]
        if any(model.get(key) != value for key, value in _EXPECTED_MUSE_MODEL_FIELDS.items()):
            raise ValueError("effective OpenCode config omitted exact Muse metadata")
        return "Pinned OpenCode version and exact effective Muse config matched.", {
            "version": adapter.expected_version,
            "model_metadata": model,
        }, tuple(
            str(adapter._runtime(root, role) / "config/opencode/opencode.json")
            for role in (read_role, write_role)
        )

    checks.append(_run_check("metadata.opencode", opencode_metadata))
    metadata_ok = all(item.status == "passed" for item in checks)

    direct_specs = (
        ("direct.text", 512), ("direct.json", 1024),
        ("direct.thinking", 512), ("direct.tool_call", 2048),
    )
    if dry_run:
        checks.extend(
            QualificationCheck(
                check_id=check_id, status="planned", duration_ms=0,
                summary=f"Would issue one request with max_tokens={budget}; no model call made.",
                observations={"max_tokens": budget},
            )
            for check_id, budget in direct_specs
        )
    elif not metadata_ok:
        checks.extend(
            QualificationCheck(
                check_id=check_id, status="skipped", duration_ms=0,
                summary="Skipped because a model-free metadata check failed.",
            )
            for check_id, _ in direct_specs
        )
    else:
        completion_url = f"{endpoint}/v1/chat/completions"

        def direct_text() -> tuple[str, dict[str, Any], tuple[str, ...]]:
            payload = _request_json(opener, completion_url, timeout=timeout_seconds, payload=_direct_payload(
                "Reply with exactly READY and nothing else.", 512,
            ))
            message, finish = _message(payload)
            content = message.get("content")
            if not isinstance(content, str) or content.strip() != "READY" or finish != "stop":
                raise ValueError("text response was not READY with finish_reason stop")
            reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
            return "Direct text returned READY and stop.", {
                "content": "READY", "finish_reason": finish,
                **(_reasoning_evidence(reasoning) if isinstance(reasoning, str) and reasoning else {}),
            }, ()

        def direct_json() -> tuple[str, dict[str, Any], tuple[str, ...]]:
            payload = _request_json(opener, completion_url, timeout=timeout_seconds, payload=_direct_payload(
                'Return exactly the JSON object {"status":"READY"} and nothing else.', 1024,
            ))
            message, finish = _message(payload)
            content = message.get("content")
            if not isinstance(content, str) or _json_object(content) != {"status": "READY"} or finish != "stop":
                raise ValueError("JSON response was not the exact object with stop")
            return "Direct JSON returned the exact object and stop.", {
                "object": {"status": "READY"}, "finish_reason": finish,
            }, ()

        def direct_thinking() -> tuple[str, dict[str, Any], tuple[str, ...]]:
            payload = _request_json(opener, completion_url, timeout=timeout_seconds, payload=_direct_payload(
                "Think through whether 2+2 equals 4, then reply with exactly READY.", 512,
            ))
            message, finish = _message(payload)
            content = message.get("content")
            reasoning = message.get("reasoning_content") or message.get("reasoning")
            if (
                not isinstance(content, str) or content.strip() != "READY" or finish != "stop"
                or not isinstance(reasoning, str) or not reasoning.strip()
            ):
                raise ValueError("thinking response omitted reasoning, READY content, or stop")
            return "Direct thinking returned redacted reasoning plus READY and stop.", {
                "content": "READY", "finish_reason": finish, **_reasoning_evidence(reasoning),
            }, ()

        def direct_tool() -> tuple[str, dict[str, Any], tuple[str, ...]]:
            tool = {
                "type": "function",
                "function": {
                    "name": "get_magic_number",
                    "description": "Return the magic number for a seed.",
                    "parameters": {
                        "type": "object", "properties": {"seed": {"type": "integer"}},
                        "required": ["seed"], "additionalProperties": False,
                    },
                },
            }
            payload = _request_json(opener, completion_url, timeout=timeout_seconds, payload=_direct_payload(
                "Call get_magic_number exactly once with seed 7. Do not answer directly.",
                2048, tools=[tool], tool_choice="auto",
            ))
            message, finish = _message(payload)
            calls = message.get("tool_calls")
            if finish != "tool_calls" or not isinstance(calls, list) or len(calls) != 1:
                raise ValueError("tool response did not finish with one tool call")
            function = calls[0].get("function") if isinstance(calls[0], dict) else None
            if not isinstance(function, dict) or function.get("name") != "get_magic_number":
                raise ValueError("tool response selected the wrong function")
            arguments = function.get("arguments")
            if not isinstance(arguments, str) or _json_object(arguments) != {"seed": 7}:
                raise ValueError("tool response supplied wrong JSON arguments")
            return "Direct tool call selected the exact function and arguments.", {
                "finish_reason": finish, "function": "get_magic_number", "arguments": {"seed": 7},
            }, ()

        for check_id, action in (
            ("direct.text", direct_text), ("direct.json", direct_json),
            ("direct.thinking", direct_thinking), ("direct.tool_call", direct_tool),
        ):
            checks.append(_run_check(check_id, action))

    opencode_specs = ("opencode.text", "opencode.read", "opencode.write_candidate")
    if not include_opencode:
        checks.extend(
            QualificationCheck(
                check_id=check_id, required=False, status="skipped", duration_ms=0,
                summary="Not selected in direct-only mode.",
            )
            for check_id in opencode_specs
        )
    elif dry_run:
        checks.extend(
            QualificationCheck(
                check_id=check_id, status="planned", duration_ms=0,
                summary="Would issue one pinned OpenCode session check; no model call made.",
            )
            for check_id in opencode_specs
        )
    elif not metadata_ok or any(item.status == "failed" for item in checks if item.required):
        checks.extend(
            QualificationCheck(
                check_id=check_id, status="skipped", duration_ms=0,
                summary="Skipped because an earlier required check failed.",
            )
            for check_id in opencode_specs
        )
    else:
        assert adapter is not None and read_role is not None and write_role is not None
        active_adapter = adapter
        read_context = canonical_sha256(("muse-qualification", "read"))
        write_context = canonical_sha256(("muse-qualification", "write"))

        def strict_value(result: dict[str, Any], expected: str) -> None:
            if result.get("value") != {"summary": expected, "notes": []}:
                raise ValueError("OpenCode response was not the strict SemanticResponse")

        def oc_text() -> tuple[str, dict[str, Any], tuple[str, ...]]:
            result = active_adapter.qualification_turn(
                read_role, root,
                'Return exactly {"summary":"READY","notes":[]} with no fence.',
                "qualification-text", agent=QUALIFICATION_TEXT_AGENT, context_digest=read_context,
            )
            strict_value(result, "READY")
            if result["tools"]:
                raise ValueError("text-only OpenCode session used a tool")
            return "OpenCode text-only session returned strict SemanticResponse.", {
                "session_id": result["session_id"], "tool_count": 0,
            }, tuple(result["evidence"].values())

        def oc_read() -> tuple[str, dict[str, Any], tuple[str, ...]]:
            result = active_adapter.qualification_turn(
                read_role, root,
                'Read README.md, then return exactly {"summary":"Muse qualification fixture.","notes":[]}.',
                "qualification-read", agent=QUALIFICATION_READ_AGENT, context_digest=read_context,
            )
            strict_value(result, "Muse qualification fixture.")
            if not any(item["tool"] == "read" and item["status"] == "completed" for item in result["tools"]):
                raise ValueError("read-only OpenCode session did not complete the read tool")
            return "OpenCode read-only session read README and returned strict SemanticResponse.", {
                "session_id": result["session_id"], "tools": result["tools"],
            }, tuple(result["evidence"].values())

        def oc_write() -> tuple[str, dict[str, Any], tuple[str, ...]]:
            before = workspace_manifest(product)
            draft = active_adapter.qualification_turn(
                write_role, root,
                'Create only src/qualified.txt with exact content QUALIFIED followed by a newline. '
                'Then return exactly {"summary":"WROTE","notes":[]}.',
                "qualification-write", agent=QUALIFICATION_WRITE_AGENT, context_digest=write_context,
            )
            strict_value(draft, "WROTE")
            after_write = workspace_manifest(product)
            change = derive_change_set(before, after_write)
            if [(item.path, item.action) for item in change.entries] != [("src/qualified.txt", "create")]:
                raise ValueError("writable session changed paths other than src/qualified.txt")
            target = product / "src/qualified.txt"
            if target.read_text(encoding="utf-8") != "QUALIFIED\n":
                raise ValueError("writable session created the wrong content")
            candidate = active_adapter.qualification_turn(
                write_role, root,
                'Read src/qualified.txt, do not edit anything, then return exactly '
                '{"summary":"QUALIFIED","notes":[]}.',
                "qualification-candidate", agent=QUALIFICATION_READ_AGENT,
                context_digest=write_context, session_id=draft["session_id"],
            )
            strict_value(candidate, "QUALIFIED")
            if candidate["session_id"] != draft["session_id"]:
                raise ValueError("candidate did not use the exact writable session")
            if workspace_manifest(product).root_digest != after_write.root_digest:
                raise ValueError("read-only candidate changed the workspace")
            evidence = (*draft["evidence"].values(), *candidate["evidence"].values())
            return "OpenCode wrote one exact file and reported through the exact read-only session.", {
                "session_id": draft["session_id"], "changes": ["src/qualified.txt"],
                "candidate_tools": candidate["tools"],
            }, tuple(evidence)

        for check_id, action in (
            ("opencode.text", oc_text), ("opencode.read", oc_read),
            ("opencode.write_candidate", oc_write),
        ):
            checks.append(_run_check(check_id, action))

    required = [item for item in checks if item.required]
    if dry_run and all(item.status != "failed" for item in required):
        verdict: Literal["QUALIFIED", "NOT_QUALIFIED", "DRY_RUN"] = "DRY_RUN"
    elif required and all(item.status == "passed" for item in required):
        verdict = "QUALIFIED"
    else:
        verdict = "NOT_QUALIFIED"
    result = MuseQualificationResult(
        workspace=str(root),
        started_at=started_at,
        duration_ms=round((time.monotonic() - started) * 1000),
        mode="opencode" if include_opencode else "direct-only",
        dry_run=dry_run,
        checks=tuple(checks),
        verdict=verdict,
    )
    result_path = root / "qualification-result.json"
    result_path.write_text(json.dumps(result.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


__all__ = ["MuseQualificationResult", "QualificationCheck", "run_muse_qualification"]
