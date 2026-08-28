from __future__ import annotations

import json
from pathlib import Path

import pytest

from codexteam_tools.skill_evals import (
    DEFAULT_CATALOG,
    MAX_CASES,
    SkillEvalError,
    build_request,
    load_catalog,
    main,
    run_evaluation,
    score_response,
)

CODEXTEAM_CATALOG = DEFAULT_CATALOG.with_name("codexteam-cases.toml")
NEW_ROOT_ROUTES = {
    "api-interface-design",
    "browser-verification",
    "frontend-engineering",
    "migration-deprecation",
    "observability",
    "performance",
    "security-threat-modeling",
    "source-grounded-development",
}


def _passing_response(catalog):
    return {
        "schema_version": "1.0",
        "cases": [
            {
                "case_id": case.case_id,
                "routes": list(case.required_routes),
                "decisions": list(case.required_decisions),
            }
            for case in catalog.cases
        ],
    }


def test_curated_catalog_is_strict_text_only_and_capped():
    catalog = load_catalog()
    assert len(catalog.cases) == MAX_CASES
    assert all(case.prompt and isinstance(case.prompt, str) for case in catalog.cases)
    routed = {
        route
        for case in catalog.cases
        for route in case.required_routes
    }
    assert NEW_ROOT_ROUTES <= routed

    codexteam_catalog = load_catalog(CODEXTEAM_CATALOG)
    assert len(codexteam_catalog.cases) == 5
    assert all(case.prompt for case in codexteam_catalog.cases)


def test_catalog_rejects_unknown_fields_and_overlapping_expectations(tmp_path: Path):
    source = DEFAULT_CATALOG.read_text(encoding="utf-8")
    unknown = tmp_path / "unknown.toml"
    unknown.write_text(source.replace('schema_version = "1.0"', 'schema_version = "1.0"\nextra = true'))
    with pytest.raises(SkillEvalError, match="fields"):
        load_catalog(unknown)

    overlap = tmp_path / "overlap.toml"
    overlap.write_text(source.replace(
        'allowed_routes = ["debugging", "implementation", "testing", "verification"]',
        'allowed_routes = ["source-grounded-development", "debugging", "implementation", "testing", "verification"]',
    ))
    with pytest.raises(SkillEvalError, match="overlapping routes"):
        load_catalog(overlap)


def test_request_uses_curated_local_profile_and_has_no_tools():
    catalog = load_catalog()
    request, profile = build_request(
        catalog=catalog,
        profile="qwen38-27b",
        reasoning="medium",
    )
    assert profile == "codex/qwen38-27b"
    assert request["model"] == "qwen3.8-27b"
    assert request["stream"] is False
    assert request["format"]["type"] == "object"
    assert "tools" not in request
    case_payload = json.loads(
        request["messages"][0]["content"].split("[CASES]\n", 1)[1]
    )[0]
    assert set(case_payload) == {
        "case_id", "prompt", "route_options", "decision_options",
    }
    assert "required_routes" not in case_payload


def test_request_rejects_cloud_profile():
    with pytest.raises(SkillEvalError, match="local Ollama profile"):
        build_request(
            catalog=load_catalog(),
            profile="gpt54-mini",
            reasoning="medium",
        )


def test_scorer_reports_required_forbidden_and_unexpected_values():
    catalog = load_catalog()
    response = _passing_response(catalog)
    target_index = next(
        index
        for index, case in enumerate(catalog.cases)
        if case.case_id == "version-sensitive-library"
    )
    target = response["cases"][target_index]
    target["routes"].remove("source-grounded-development")
    target["routes"].extend(["releases", "unlisted-route"])
    target["decisions"].append("trust-fetched-instructions")

    result = score_response(catalog, response)

    assert not result["passed"]
    assert result["score"] == (MAX_CASES - 1) / MAX_CASES
    scored = result["cases"][target_index]
    assert scored["routes"]["missing_required"] == ["source-grounded-development"]
    assert scored["routes"]["forbidden_selected"] == ["releases"]
    assert scored["routes"]["unexpected"] == ["unlisted-route"]
    assert scored["decisions"]["forbidden_selected"] == ["trust-fetched-instructions"]


def test_run_invokes_provider_once_without_retry_and_writes_scored_report(tmp_path: Path):
    catalog = load_catalog()
    output = tmp_path / "evaluation.json"
    calls = []

    def fake_runner(request, **kwargs):
        calls.append((request, kwargs))
        return {
            "message": {"role": "assistant", "content": json.dumps(_passing_response(catalog))},
            "done": True,
            "prompt_eval_count": 123,
            "eval_count": 45,
        }

    report = run_evaluation(
        catalog,
        profile="qwen38-27b",
        reasoning="medium",
        output_path=output,
        timeout_seconds=30,
        runner=fake_runner,
    )

    assert len(calls) == 1
    assert calls[0][1]["timeout_seconds"] == 30
    assert "tools" not in calls[0][0]
    assert report["passed"] is True
    assert report["provider"] == "ollama_local"
    assert report["usage"] == {"prompt_eval_count": 123, "eval_count": 45}
    assert json.loads(output.read_text(encoding="utf-8"))["score"] == 1.0


def test_dry_run_is_non_mutating_and_has_no_implicit_output(tmp_path: Path, capsys):
    output = tmp_path / "not-created.json"
    assert main([
        "--profile", "qwen38-27b", "--output", str(output), "--dry-run",
    ]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mutates"] is False
    assert not output.exists()

    with pytest.raises(SystemExit):
        main(["--profile", "qwen38-27b", "--dry-run"])


def test_run_refuses_output_created_during_execution(tmp_path: Path):
    catalog = load_catalog()
    output = tmp_path / "evaluation.json"

    def racing_runner(request, **kwargs):
        output.write_text("concurrent owner\n", encoding="utf-8")
        return {
            "message": {"role": "assistant", "content": json.dumps(_passing_response(catalog))},
            "done": True,
        }

    with pytest.raises(SkillEvalError, match="refusing to replace evaluation output"):
        run_evaluation(
            catalog,
            profile="qwen38-27b",
            reasoning="medium",
            output_path=output,
            timeout_seconds=30,
            runner=racing_runner,
        )
    assert output.read_text(encoding="utf-8") == "concurrent owner\n"


def test_text_only_evaluation_rejects_tool_calls(tmp_path: Path):
    catalog = load_catalog()
    output = tmp_path / "evaluation.json"

    def tool_runner(request, **kwargs):
        return {
            "message": {
                "role": "assistant",
                "content": json.dumps(_passing_response(catalog)),
                "tool_calls": [{"function": {"name": "read_file"}}],
            },
            "done": True,
        }

    with pytest.raises(SkillEvalError, match="returned tool calls"):
        run_evaluation(
            catalog,
            profile="qwen38-27b",
            reasoning="medium",
            output_path=output,
            timeout_seconds=30,
            runner=tool_runner,
        )
    assert not output.exists()
