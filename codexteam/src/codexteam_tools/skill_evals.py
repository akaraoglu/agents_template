from __future__ import annotations

import argparse
import json
import re
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .execution_registry import load_execution_registry
from .files import create_json

CODEXTEAM_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = CODEXTEAM_ROOT.parent
DEFAULT_CATALOG = CODEXTEAM_ROOT / "tests" / "fixtures" / "skill_evals" / "cases.toml"
DEFAULT_SKILLS_ROOT = REPO_ROOT / ".agents" / "skills"
CODEXTEAM_ROUTES = {
    "codexteam-feature-planning": CODEXTEAM_ROOT / ".agents" / "skills" / "feature-planning.md",
    "codexteam-integration-testing": CODEXTEAM_ROOT / ".agents" / "skills" / "integration-testing.md",
    "codexteam-self-improvement": CODEXTEAM_ROOT / ".agents" / "skills" / "codexteam-self-improvement.md",
    "codexteam-verification": CODEXTEAM_ROOT / ".agents" / "skills" / "verification.md",
}
CASE_FIELDS = {
    "id", "prompt", "required_routes", "allowed_routes", "forbidden_routes",
    "required_decisions", "allowed_decisions", "forbidden_decisions",
}
TOKEN = re.compile(r"[a-z][a-z0-9-]{1,63}")
MAX_CASES = 8
MAX_PROMPT_CHARS = 4_000
MAX_EVALUATION_PROMPT_CHARS = 96_000
MAX_RESPONSE_BYTES = 64 * 1024
MAX_PROVIDER_RESPONSE_BYTES = 256 * 1024
PASS_THRESHOLD = 1.0
OLLAMA_CHAT_URL = "http://127.0.0.1:11434/api/chat"


class SkillEvalError(ValueError):
    pass


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    prompt: str
    required_routes: tuple[str, ...]
    allowed_routes: tuple[str, ...]
    forbidden_routes: tuple[str, ...]
    required_decisions: tuple[str, ...]
    allowed_decisions: tuple[str, ...]
    forbidden_decisions: tuple[str, ...]


@dataclass(frozen=True)
class EvalCatalog:
    source_path: Path
    cases: tuple[EvalCase, ...]


def load_catalog(path: str | Path = DEFAULT_CATALOG) -> EvalCatalog:
    candidate = Path(path).expanduser()
    if candidate.is_symlink():
        raise SkillEvalError(f"case catalog must not be a symlink: {candidate}")
    source = candidate.resolve(strict=True)
    if not source.is_file():
        raise SkillEvalError(f"case catalog must be a regular file: {source}")
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SkillEvalError(f"invalid case catalog TOML: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"schema_version", "cases"}:
        raise SkillEvalError("case catalog fields must be schema_version and cases")
    if data["schema_version"] != "1.0":
        raise SkillEvalError("case catalog schema_version must be '1.0'")
    raw_cases = data["cases"]
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= MAX_CASES:
        raise SkillEvalError(f"case catalog must contain between 1 and {MAX_CASES} cases")
    cases = tuple(_case_from_mapping(value, index) for index, value in enumerate(raw_cases, 1))
    ids = [case.case_id for case in cases]
    if len(ids) != len(set(ids)):
        raise SkillEvalError("case catalog contains duplicate case IDs")
    return EvalCatalog(source, cases)


def _case_from_mapping(value: Any, index: int) -> EvalCase:
    if not isinstance(value, dict) or set(value) != CASE_FIELDS:
        raise SkillEvalError(f"case {index} fields do not match the case contract")
    case_id = value["id"]
    if not isinstance(case_id, str) or not TOKEN.fullmatch(case_id):
        raise SkillEvalError(f"case {index} has an invalid ID")
    prompt = value["prompt"]
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise SkillEvalError(f"case {case_id} prompt must be 1-{MAX_PROMPT_CHARS} characters")
    groups = {
        field: _tokens(value[field], f"case {case_id} {field}")
        for field in CASE_FIELDS - {"id", "prompt"}
    }
    for kind in ("routes", "decisions"):
        required = set(groups[f"required_{kind}"])
        allowed = set(groups[f"allowed_{kind}"])
        forbidden = set(groups[f"forbidden_{kind}"])
        if not required and not allowed and not forbidden:
            raise SkillEvalError(f"case {case_id} has no {kind} expectations")
        if required & allowed or required & forbidden or allowed & forbidden:
            raise SkillEvalError(f"case {case_id} has overlapping {kind} expectations")
    return EvalCase(
        case_id, prompt,
        groups["required_routes"], groups["allowed_routes"], groups["forbidden_routes"],
        groups["required_decisions"], groups["allowed_decisions"],
        groups["forbidden_decisions"],
    )


def _tokens(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not TOKEN.fullmatch(item) for item in value
    ):
        raise SkillEvalError(f"{label} must be a list of lowercase identifiers")
    if len(value) != len(set(value)):
        raise SkillEvalError(f"{label} contains duplicates")
    return tuple(value)


def response_schema(catalog: EvalCatalog) -> dict[str, Any]:
    routes = sorted({
        item
        for case in catalog.cases
        for item in (*case.required_routes, *case.allowed_routes, *case.forbidden_routes)
    })
    decisions = sorted({
        item
        for case in catalog.cases
        for item in (
            *case.required_decisions, *case.allowed_decisions, *case.forbidden_decisions,
        )
    })
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "cases"],
        "properties": {
            "schema_version": {"const": "1.0"},
            "cases": {
                "type": "array",
                "minItems": len(catalog.cases),
                "maxItems": len(catalog.cases),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["case_id", "routes", "decisions"],
                    "properties": {
                        "case_id": {"type": "string", "enum": [case.case_id for case in catalog.cases]},
                        "routes": {"type": "array", "uniqueItems": True, "items": {"type": "string", "enum": routes}},
                        "decisions": {"type": "array", "uniqueItems": True, "items": {"type": "string", "enum": decisions}},
                    },
                },
            },
        },
    }


def build_prompt(catalog: EvalCatalog, *, skills_root: str | Path = DEFAULT_SKILLS_ROOT) -> str:
    root = Path(skills_root).expanduser().resolve(strict=True)
    route_names = sorted({
        route
        for case in catalog.cases
        for route in (*case.required_routes, *case.allowed_routes, *case.forbidden_routes)
    })
    guidance: list[str] = []
    for name in route_names:
        configured_path = CODEXTEAM_ROUTES.get(name)
        path = (
            configured_path.resolve(strict=True)
            if configured_path is not None
            else (root / name / "SKILL.md").resolve(strict=True)
        )
        expected_root = (
            (CODEXTEAM_ROOT / ".agents" / "skills").resolve()
            if configured_path is not None
            else root
        )
        try:
            path.relative_to(expected_root)
        except ValueError as exc:
            raise SkillEvalError(f"skill route escapes skill root: {name}") from exc
        if path.is_symlink() or not path.is_file():
            raise SkillEvalError(f"skill route is missing or unsafe: {name}")
        guidance.append(f"[SKILL {name}]\n{path.read_text(encoding='utf-8').strip()}")
    cases = [
        {
            "case_id": case.case_id,
            "prompt": case.prompt,
            "route_options": sorted({
                *case.required_routes,
                *case.allowed_routes,
                *case.forbidden_routes,
            }),
            "decision_options": sorted({
                *case.required_decisions,
                *case.allowed_decisions,
                *case.forbidden_decisions,
            }),
        }
        for case in catalog.cases
    ]
    prompt = (
        "Evaluate each text-only request against the supplied skill guidance. Do not use tools, "
        "modify files, or answer the requests. Return only the required JSON. For each case, "
        "select every directly applicable skill route and decision identifier from that case's "
        "candidate options. Options are intentionally unlabeled; do not infer that every option "
        "is correct, and do not reuse choices from another case.\n\n"
        + "\n\n".join(guidance)
        + "\n\n[CASES]\n"
        + json.dumps(cases, indent=2)
    )
    if len(prompt) > MAX_EVALUATION_PROMPT_CHARS:
        raise SkillEvalError(
            f"evaluation prompt exceeds {MAX_EVALUATION_PROMPT_CHARS} characters"
        )
    return prompt


def build_request(
    *,
    catalog: EvalCatalog,
    profile: str,
    reasoning: str,
) -> tuple[dict[str, Any], str]:
    resolved = load_execution_registry().resolve("codex", profile, reasoning)
    if resolved.provider != "ollama_local":
        raise SkillEvalError(
            "manual skill evaluation requires a curated local Ollama profile"
        )
    return (
        {
            "model": resolved.provider_locator,
            "messages": [{"role": "user", "content": build_prompt(catalog)}],
            "stream": False,
            "format": response_schema(catalog),
            "options": {"temperature": 0},
        },
        resolved.canonical_profile,
    )


def score_response(catalog: EvalCatalog, response: Any) -> dict[str, Any]:
    if not isinstance(response, dict) or set(response) != {"schema_version", "cases"}:
        raise SkillEvalError("model response fields must be schema_version and cases")
    if response["schema_version"] != "1.0" or not isinstance(response["cases"], list):
        raise SkillEvalError("model response does not satisfy schema version 1.0")
    observed: dict[str, dict[str, Any]] = {}
    for value in response["cases"]:
        if not isinstance(value, dict) or set(value) != {"case_id", "routes", "decisions"}:
            raise SkillEvalError("model case fields must be case_id, routes, and decisions")
        case_id = value["case_id"]
        if not isinstance(case_id, str) or case_id in observed:
            raise SkillEvalError("model response contains an invalid or duplicate case ID")
        _tokens(value["routes"], f"model case {case_id} routes")
        _tokens(value["decisions"], f"model case {case_id} decisions")
        observed[case_id] = value
    expected_ids = {case.case_id for case in catalog.cases}
    if set(observed) != expected_ids:
        raise SkillEvalError("model response case IDs do not match the catalog")

    results = []
    for case in catalog.cases:
        value = observed[case.case_id]
        route_result = _score_values(
            value["routes"], case.required_routes, case.allowed_routes, case.forbidden_routes,
        )
        decision_result = _score_values(
            value["decisions"], case.required_decisions, case.allowed_decisions,
            case.forbidden_decisions,
        )
        results.append({
            "case_id": case.case_id,
            "passed": route_result["passed"] and decision_result["passed"],
            "routes": route_result,
            "decisions": decision_result,
        })
    score = sum(result["passed"] for result in results) / len(results)
    return {
        "threshold": PASS_THRESHOLD,
        "score": score,
        "passed": score >= PASS_THRESHOLD,
        "cases": results,
    }


def _score_values(
    observed: list[str],
    required: tuple[str, ...],
    allowed: tuple[str, ...],
    forbidden: tuple[str, ...],
) -> dict[str, Any]:
    selected = set(observed)
    required_set = set(required)
    allowed_set = set(allowed)
    forbidden_set = set(forbidden)
    missing = sorted(required_set - selected)
    forbidden_selected = sorted(selected & forbidden_set)
    unexpected = sorted(selected - required_set - allowed_set - forbidden_set)
    return {
        "passed": not missing and not forbidden_selected and not unexpected,
        "selected": list(observed),
        "missing_required": missing,
        "forbidden_selected": forbidden_selected,
        "unexpected": unexpected,
    }


def run_evaluation(
    catalog: EvalCatalog,
    *,
    profile: str,
    reasoning: str,
    output_path: str | Path,
    timeout_seconds: int,
    runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    output = Path(output_path).expanduser().resolve(strict=False)
    if output.exists() or output.is_symlink():
        raise SkillEvalError(f"refusing to replace evaluation output: {output}")
    if not output.parent.is_dir():
        raise SkillEvalError(f"evaluation output parent does not exist: {output.parent}")
    request, canonical_profile = build_request(
        catalog=catalog,
        profile=profile,
        reasoning=reasoning,
    )
    provider_response = (runner or _post_ollama)(
        request,
        timeout_seconds=timeout_seconds,
    )
    response, usage = _parse_ollama_response(provider_response)
    scoring = score_response(catalog, response)
    report = {
        "schema_version": "1.0",
        "catalog": str(catalog.source_path),
        "profile": canonical_profile,
        "reasoning": reasoning,
        "provider": "ollama_local",
        "usage": usage,
        **scoring,
        "response": response,
    }
    try:
        create_json(output, report)
    except FileExistsError as exc:
        raise SkillEvalError(
            f"refusing to replace evaluation output: {output}"
        ) from exc
    return report


def _post_ollama(
    payload: dict[str, Any],
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    request = urllib.request.Request(
        OLLAMA_CHAT_URL,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout_seconds) as response:
            body = response.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
    except (OSError, urllib.error.URLError) as exc:
        raise SkillEvalError(f"local Ollama evaluation failed: {exc}") from exc
    if len(body) > MAX_PROVIDER_RESPONSE_BYTES:
        raise SkillEvalError(
            f"Ollama response exceeds {MAX_PROVIDER_RESPONSE_BYTES} bytes"
        )
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillEvalError(f"Ollama response is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SkillEvalError("Ollama response must be a JSON object")
    return value


def _parse_ollama_response(value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    message = value.get("message")
    if not isinstance(message, dict):
        raise SkillEvalError("Ollama response is missing the assistant message")
    tool_calls = message.get("tool_calls")
    if tool_calls not in (None, []):
        raise SkillEvalError("text-only skill evaluation returned tool calls")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise SkillEvalError("Ollama response has no assistant JSON content")
    if len(content.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise SkillEvalError(f"model response exceeds {MAX_RESPONSE_BYTES} bytes")
    try:
        response = json.loads(content)
    except json.JSONDecodeError as exc:
        raise SkillEvalError(f"model response is not valid JSON: {exc}") from exc
    usage: dict[str, int] = {}
    for name in ("prompt_eval_count", "eval_count"):
        count = value.get(name)
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            usage[name] = count
    return response, usage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or run one bounded, tool-free local Ollama skill evaluation."
    )
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--profile", required=True, help="Curated enabled Codex profile")
    parser.add_argument("--reasoning", default="medium")
    parser.add_argument("--output", required=True, help="New path for the JSON evaluation report")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not 1 <= args.timeout_seconds <= 900:
            raise SkillEvalError("timeout-seconds must be between 1 and 900")
        catalog = load_catalog(args.catalog)
        if args.dry_run:
            request, canonical_profile = build_request(
                catalog=catalog,
                profile=args.profile,
                reasoning=args.reasoning,
            )
            print(json.dumps({
                "catalog": str(catalog.source_path),
                "cases": len(catalog.cases),
                "profile": canonical_profile,
                "provider": "ollama_local",
                "endpoint": OLLAMA_CHAT_URL,
                "model": request["model"],
                "tool_count": 0,
                "output": str(Path(args.output).expanduser().resolve(strict=False)),
                "mutates": False,
            }, indent=2))
            return 0
        report = run_evaluation(
            catalog,
            profile=args.profile,
            reasoning=args.reasoning,
            output_path=args.output,
            timeout_seconds=args.timeout_seconds,
        )
        return 0 if report["passed"] else 1
    except (FileNotFoundError, OSError, SkillEvalError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
