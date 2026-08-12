from __future__ import annotations

import json

import pytest

from codexteam_tools.v2 import (
    ActorRef, compile_pipeline, load_catalog, run_fake_canary,
    run_live_opencode_canary,
)
from codexteam_tools.v2.runtime.opencode import OpenCodeRuntimeAdapter
from tests.v2.test_opencode_adapter import FAKE_OPENCODE
from codexteam_tools.v2.canary import FIXED_TIME, _dependency_order, _work_item
from codexteam_tools.v2.cli import main


ORDER = ("Discovery", "Architect", "UX", "Developer", "Test", "Assurance", "Review")


def test_happy_adaptive_canary_and_deterministic_seal(tmp_path) -> None:
    first = run_fake_canary(workspace=tmp_path / "first")
    second = run_fake_canary(workspace=tmp_path / "second")
    assert first.stage_order == ORDER
    assert first.revision == 2
    assert first.closure == "closed"
    assert all(first.checks.values())
    assert first.seal == second.seal
    catalog = load_catalog("v2")
    lead = ActorRef(actor_id="lead", kind="project_lead")
    assert compile_pipeline(catalog, _work_item(), ("architecture", "ux"), lead, FIXED_TIME).plan == compile_pipeline(
        catalog, _work_item(), ("architecture", "ux"), lead, FIXED_TIME
    ).plan


@pytest.mark.parametrize("selected", ((), ("architecture",), ("ux",), ("architecture", "ux")))
def test_canary_dependency_traversal_supports_every_optional_stage_variant(selected) -> None:
    compiled = compile_pipeline(
        load_catalog("v2"), _work_item(), selected,
        ActorRef(actor_id="lead", kind="project_lead"), FIXED_TIME,
    )
    ordered = _dependency_order(compiled.plan.stages)
    assert tuple(stage.stage for stage in ordered) == (
        "discovery", *selected, "implementation", "verification", "assurance", "review"
    )
    assert all(not stage.dependencies or stage.dependencies == (ordered[index - 1].stage_id,) for index, stage in enumerate(ordered))


def test_defect_loop_reuses_sessions_and_reruns_stale_evidence(tmp_path) -> None:
    result = run_fake_canary(scenario="defect-loop", workspace=tmp_path / "canary")
    assert result.defect_loop_count == 1
    assert result.sessions["implementation"] == "session-developer"
    assert result.sessions["verification"] == "session-test"
    assert result.checks["stale_evidence_rerun"]


@pytest.mark.parametrize("scenario", [
    "malformed", "forbidden-write", "assurance-fail", "review-return", "assurance-blocking", "review-blocking",
    "missing-capability", "context-mismatch", "external-workspace",
])
def test_bad_fake_scenarios_block(scenario, tmp_path) -> None:
    with pytest.raises(Exception):
        run_fake_canary(scenario=scenario, workspace=tmp_path / scenario)
    assert not list((tmp_path / scenario / ".codexteam/v2/seals").glob("*.json"))
    assert not list((tmp_path / scenario / ".codexteam/v2/events").glob("closure-*.jsonl"))
    if scenario == "external-workspace":
        assert not (tmp_path / "external.txt").exists()


def test_dry_run_is_nonmutating(tmp_path) -> None:
    workspace = tmp_path / "absent"
    result = run_fake_canary(workspace=workspace, dry_run=True)
    assert result.closure == "dry-run"
    assert not workspace.exists()


def test_cli_help_catalog_compile_and_canary(capsys, tmp_path) -> None:
    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    assert help_exit.value.code == 0
    assert "catalog-check" in capsys.readouterr().out
    with pytest.raises(SystemExit) as qualification_help_exit:
        main(["qualify-muse", "--help"])
    assert qualification_help_exit.value.code == 0
    qualification_help = capsys.readouterr().out
    assert "--direct-only" in qualification_help and "--opencode" in qualification_help
    with pytest.raises(SystemExit) as canary_help_exit:
        main(["canary", "--help"])
    assert canary_help_exit.value.code == 0
    canary_help = capsys.readouterr().out
    assert "Muse" in canary_help and "Glimmer" in canary_help
    assert "ollama/muse-" in canary_help and "glimmer:30b" in canary_help
    assert main(["catalog-check", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ok"
    assert main(["compile", "--optional", "architecture,ux", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["stages"] == [
        "discovery", "architecture", "ux", "implementation", "verification", "assurance", "review"
    ]
    workspace = tmp_path / "dry"
    assert main(["canary", "--fake", "--dry-run", "--workspace", str(workspace), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["closure"] == "dry-run"
    assert not workspace.exists()
    live_workspace = tmp_path / "cli-canary"
    assert main(["canary", "--fake", "--workspace", str(live_workspace), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["closure"] == "closed"


def test_qualification_cli_emits_gate_result(monkeypatch, capsys, tmp_path) -> None:
    from types import SimpleNamespace

    from codexteam_tools.v2 import cli as cli_module

    calls = []

    def qualify(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            verdict="DRY_RUN",
            as_dict=lambda: {"verdict": "DRY_RUN", "dry_run": True},
        )

    monkeypatch.setattr(cli_module, "run_muse_qualification", qualify)
    workspace = tmp_path / "qualification"
    assert main([
        "qualify-muse", "--opencode", "--dry-run", "--timeout", "17",
        "--workspace", str(workspace), "--json",
    ]) == 0
    assert json.loads(capsys.readouterr().out) == {"dry_run": True, "verdict": "DRY_RUN"}
    assert calls == [{
        "workspace": workspace, "include_opencode": True, "dry_run": True,
        "timeout_seconds": 17,
    }]


def test_canary_criterion_contract_drives_test_and_rejects_changed_expectation(tmp_path, monkeypatch) -> None:
    from codexteam_tools.v2 import MachineVerificationSpec
    from codexteam_tools.v2 import canary as canary_module

    original = canary_module._work_item

    def changed():
        item = original()
        criterion = item.acceptance_criteria[0]
        return item.model_copy(update={
            "acceptance_criteria": (criterion.model_copy(update={
                "statement": "The CLI prints exactly 999 followed by a newline for input 7.",
                "verification": MachineVerificationSpec(
                    verifier_argv=("/usr/bin/python3", "project/tests/integration/test_cli.py"),
                    argv=("/usr/bin/python3", "project/src/fib.py", "7"), expected_stdout="999\n",
                ),
            }),),
        })

    monkeypatch.setattr(canary_module, "_work_item", changed)
    with pytest.raises(RuntimeError, match="accepted receipt"):
        run_fake_canary(workspace=tmp_path / "changed")


def test_canary_test_engineer_owns_integration_test(tmp_path) -> None:
    workspace = tmp_path / "ownership"
    run_fake_canary(workspace=workspace)
    reports = list((workspace / ".codexteam/v2/records/candidate_report").glob("*.json"))
    verification = next(
        json.loads(path.read_text())
        for path in reports
        if json.loads(path.read_text())["stage"] == "verification"
        and json.loads(path.read_text())["criterion_dispositions"][0]["disposition"] == "verified"
    )
    implementation = next(json.loads(path.read_text()) for path in reports if json.loads(path.read_text())["stage"] == "implementation")
    discovery = next(json.loads(path.read_text()) for path in reports if json.loads(path.read_text())["stage"] == "discovery")
    assurance_candidate = next(json.loads(path.read_text()) for path in reports if json.loads(path.read_text())["stage"] == "assurance")
    review_candidate = next(json.loads(path.read_text()) for path in reports if json.loads(path.read_text())["stage"] == "review")
    assert implementation["criterion_dispositions"][0]["disposition"] == "claimed_satisfied"
    assert implementation["criterion_dispositions"][0]["evidence_types"] == ["artifact"]
    assert verification["criterion_dispositions"][0]["disposition"] == "verified"
    assert verification["criterion_dispositions"][0]["evidence_types"] == ["test_output"]
    assert discovery["criterion_dispositions"][0]["disposition"] == "not_evaluated"
    assert assurance_candidate["criterion_dispositions"][0]["disposition"] == "not_evaluated"
    assert review_candidate["criterion_dispositions"][0]["disposition"] == "not_evaluated"
    change_path = workspace / ".codexteam/v2/records/change_set" / f"{verification['change_set']['record_id']}.json"
    paths = {entry["path"] for entry in json.loads(change_path.read_text())["entries"]}
    assert paths == {"project/tests/integration/test_cli.py"}
    assurance_path = next((workspace / ".codexteam/v2/records/assurance_report").glob("*.json"))
    assurance = json.loads(assurance_path.read_text())
    assert assurance["dispositions"] == [{
        "disposition": "pass", "domain": "security_privacy", "evidence": assurance["dispositions"][0]["evidence"],
        "findings": [],
    }]
    review_path = next((workspace / ".codexteam/v2/records/review_decision").glob("*.json"))
    review = json.loads(review_path.read_text())
    assert review["decision"] == "ACCEPT"
    assert review["rationale"] == "Independent evidence satisfies acceptance."

    # Persisted ContextItems prove the exact bounded content supplied to downstream adapters.
    context_records = [json.loads(path.read_text()) for path in (workspace / ".codexteam/v2/records/context_item").glob("*.json")]
    combined = "\n".join(item["summary"] for item in context_records)
    assert implementation["candidate_report_id"] in combined
    receipt_path = next((workspace / ".codexteam/v2/records/verification_receipt").glob("*.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["candidate"]["digest"] in combined
    assert implementation["change_set"]["digest"] in combined
    assert receipt["verification_receipt_id"] in combined and '"accepted":true' in combined
    assert assurance["assurance_report_id"] in combined


def test_cli_invalid_input_and_operational_failure_are_structured(capsys, tmp_path) -> None:
    assert main(["compile", "--optional", "bogus", "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid_input"
    assert main(["--json", "--unknown"]) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "invalid_input"
    assert main([
        "canary", "--fake", "--scenario", "assurance-fail", "--workspace", str(tmp_path / "failure"), "--json",
    ]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_live_canary_protocol_through_fake_opencode(tmp_path, monkeypatch) -> None:
    test_bin = tmp_path / "test-bin"
    test_bin.mkdir(mode=0o700)
    executable = test_bin / "opencode"
    executable.write_text(FAKE_OPENCODE, encoding="utf-8")
    executable.chmod(0o700)
    monkeypatch.setattr(OpenCodeRuntimeAdapter, "_ollama_digest", lambda self: "a" * 64)
    original_init = OpenCodeRuntimeAdapter.__init__

    def use_test_home(self, **kwargs):
        original_init(
            self, test_executable_root=test_bin,
            _test_only_allow_executable_root=True,
            _test_only_systemd_root=tmp_path / "systemd-bin", **kwargs,
        )

    systemd_bin = tmp_path / "systemd-bin"
    systemd_bin.mkdir()
    from tests.v2.test_codex_adapter import FAKE_SYSTEMCTL, FAKE_SYSTEMD_RUN
    (systemd_bin / "systemd-run").write_text(FAKE_SYSTEMD_RUN)
    (systemd_bin / "systemctl").write_text(FAKE_SYSTEMCTL)
    (systemd_bin / "systemd-run").chmod(0o700)
    (systemd_bin / "systemctl").chmod(0o700)
    monkeypatch.setattr(OpenCodeRuntimeAdapter, "__init__", use_test_home)
    result = run_live_opencode_canary(
        workspace=tmp_path / "live", executable=executable, timeout_seconds=10,
    )
    assert result.closure == "closed"
    assert result.stage_order == ORDER
    assert set(result.sessions) == {
        "discovery", "architecture", "ux", "implementation", "verification", "assurance", "review"
    }
    product = tmp_path / "live/project"
    assert not (product / "go.mod").exists()
    assert {
        path.relative_to(product).as_posix()
        for path in product.rglob("*")
        if path.is_file()
    } >= {
        "docs/architecture/CLI.md", "docs/design/CLI.md", "src/fib.py",
        "tests/test_fib_unit.py", "tests/integration/test_cli.py",
    }
    expected = {
        "architecture": ("docs/architecture/**",),
        "ux": ("docs/design/**",),
        "implementation": ("src/**", "tests/**"),
        "verification": ("tests/**",),
    }
    objectives = {
        "architecture": "Create docs/architecture/CLI.md.",
        "ux": "Create docs/design/CLI.md.",
        "implementation": "Create src/fib.py and tests/test_fib_unit.py only.",
        "verification": "Create tests/integration/test_cli.py only.",
    }
    runtime_root = tmp_path / "live/.codexteam/v2/runtime"
    for runtime in runtime_root.glob("*/opencode"):
        config = json.loads((runtime / "config/opencode/opencode.json").read_text())
        description = config["agent"]["mutable"]["description"]
        stage = description.removeprefix("CodexTeam ").removesuffix(" worker")
        edit = config["agent"]["mutable"]["permission"]["edit"]
        write = config["agent"]["mutable"]["permission"]["write"]
        if stage in expected:
            assert edit == "allow"
            assert write == "allow"
            prompts = "\n".join(
                json.loads(line)["prompt"]
                for line in (runtime / "calls.jsonl").read_text().splitlines()
            )
            assert f"Allowed write paths: {', '.join(expected[stage])}" in prompts
            assert objectives[stage] in prompts
            assert f"project/{expected[stage][0]}" in prompts
            assert "package manifest" in prompts
        else:
            assert edit == "deny"
            assert write == "deny"
        assert config["agent"]["readonly"]["permission"]["edit"] == "deny"
        assert config["agent"]["readonly"]["permission"]["write"] == "deny"


def test_malicious_fake_bypass_is_audited_and_not_removed(tmp_path, monkeypatch) -> None:
    test_bin = tmp_path / "test-bin"
    test_bin.mkdir(mode=0o700)
    executable = test_bin / "opencode"
    executable.write_text(
        FAKE_OPENCODE.replace(
            'if os.environ.get("FAKE_OPENCODE_BYPASS") == "1":', "if True:"
        ),
        encoding="utf-8",
    )
    executable.chmod(0o700)
    monkeypatch.setattr(OpenCodeRuntimeAdapter, "_ollama_digest", lambda self: "a" * 64)
    original_init = OpenCodeRuntimeAdapter.__init__

    systemd_bin = tmp_path / "systemd-bin"
    systemd_bin.mkdir()
    from tests.v2.test_codex_adapter import FAKE_SYSTEMCTL, FAKE_SYSTEMD_RUN
    (systemd_bin / "systemd-run").write_text(FAKE_SYSTEMD_RUN)
    (systemd_bin / "systemctl").write_text(FAKE_SYSTEMCTL)
    (systemd_bin / "systemd-run").chmod(0o700)
    (systemd_bin / "systemctl").chmod(0o700)

    def use_test_home(self, **kwargs):
        original_init(
            self, test_executable_root=test_bin,
            _test_only_allow_executable_root=True,
            _test_only_systemd_root=systemd_bin, **kwargs,
        )

    monkeypatch.setattr(OpenCodeRuntimeAdapter, "__init__", use_test_home)
    workspace = tmp_path / "bypass"
    with pytest.raises(RuntimeError, match="forbidden changes.*project/go.mod"):
        run_live_opencode_canary(workspace=workspace, executable=executable, timeout_seconds=10)
    assert (workspace / "project/go.mod").read_text() == "module forbidden\n"


def test_failed_live_workspace_cannot_be_reused(tmp_path) -> None:
    workspace = tmp_path / "failed"
    (workspace / "project").mkdir(parents=True)
    (workspace / "project/forbidden.txt").write_text("preserved\n")
    with pytest.raises(ValueError, match="absent or empty"):
        run_live_opencode_canary(workspace=workspace, dry_run=False)
    assert (workspace / "project/forbidden.txt").read_text() == "preserved\n"


def test_live_cli_dry_run_has_no_model_turn_or_workspace_mutation(tmp_path, monkeypatch, capsys) -> None:
    test_bin = tmp_path / "test-bin"
    test_bin.mkdir(mode=0o700)
    executable = test_bin / "opencode"
    executable.write_text(FAKE_OPENCODE, encoding="utf-8")
    executable.chmod(0o700)
    monkeypatch.setattr(OpenCodeRuntimeAdapter, "_ollama_digest", lambda self: "a" * 64)
    original_init = OpenCodeRuntimeAdapter.__init__

    def use_test_home(self, **kwargs):
        original_init(
            self, test_executable_root=test_bin,
            _test_only_allow_executable_root=True,
            _test_only_systemd_root=tmp_path / "systemd-bin", **kwargs,
        )

    systemd_bin = tmp_path / "systemd-bin"
    systemd_bin.mkdir()
    from tests.v2.test_codex_adapter import FAKE_SYSTEMCTL, FAKE_SYSTEMD_RUN
    (systemd_bin / "systemd-run").write_text(FAKE_SYSTEMD_RUN)
    (systemd_bin / "systemctl").write_text(FAKE_SYSTEMCTL)
    (systemd_bin / "systemd-run").chmod(0o700)
    (systemd_bin / "systemctl").chmod(0o700)
    monkeypatch.setattr(OpenCodeRuntimeAdapter, "__init__", use_test_home)
    workspace = tmp_path / "absent"
    assert main([
        "canary", "--live-opencode", "--workspace", str(workspace),
        "--opencode-executable", str(executable), "--dry-run", "--json",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["checks"] == {"model_calls": False, "nonmutating": True}
    assert not workspace.exists()
    assert all("--continue" not in command for command in output["plan"]["command_previews"])
    assert str(workspace) not in json.dumps(output["plan"])
    assert output["plan"]["backend"] == "opencode"
    assert output["plan"]["model"] == "ollama/muse-glimmer:30b"
    assert all("--model ollama/muse-glimmer:30b" in command for command in output["plan"]["command_previews"])


def test_live_cli_rejects_inactive_qwen_model(tmp_path, monkeypatch, capsys) -> None:
    assert main([
        "canary", "--live-opencode", "--dry-run", "--json",
        "--model", "ollama/qwen3.6-27b:latest",
    ]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed"
    assert "active AgentSpecs" in output["error"]
