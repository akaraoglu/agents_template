from __future__ import annotations

from datetime import datetime, timezone
import hashlib

import pytest

from codexteam_tools.v2 import (
    AcceptanceCriterion,
    ActorRef,
    ContextItem,
    DefectPacket,
    EvidenceType,
    FakeRuntimeAdapter,
    LeadDecision,
    PipelineRuntime,
    RuntimeOutputError,
    RuntimePreflightError,
    RuntimeSessionError,
    StageRunner,
    V2ProjectStore,
    WorkItem,
    compile_pipeline,
    load_catalog,
)


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


def _setup(tmp_path, stage_name="discovery"):
    (tmp_path / "project").mkdir()
    catalog = load_catalog("v2")
    work = WorkItem(
        schema_version="2.0", kind="work_item", work_item_id="runtime-work", title="Runtime",
        objective="Exercise runtime", acceptance_criteria=(
            AcceptanceCriterion(id="criterion", statement="Pass", required_evidence_types=(EvidenceType.TEST_OUTPUT,)),
        ), approved_scope=("project/**",),
    )
    selected = ("architecture",) if stage_name == "architecture" else ()
    lead = ActorRef(actor_id="lead", kind="project_lead")
    compiled = compile_pipeline(catalog, work, selected, lead, NOW)
    store = V2ProjectStore(tmp_path)
    store.write_immutable(work, work.work_item_id)
    decision = LeadDecision(
        schema_version="2.0", kind="lead_decision", decision_id="runtime-decision", decision="approve",
        subject=compiled.refs.plan, rationale="Approve", decided_by=lead, decided_at=NOW,
    )
    projection = PipelineRuntime(store, catalog=catalog).initialize("runtime-run", compiled.plan, decision, created_at=NOW)
    revision = store.resolve(projection.pipeline_revision)
    stage = next(item for item in revision.stages if item.stage_id == stage_name)
    return catalog, work, store, revision, stage


def test_stage_starts_only_after_preflight_and_candidate_is_authoritative(tmp_path) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": {"session_id": "session-1"}},
    }, workspace=tmp_path)
    execution = StageRunner(
        store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
        stage=stage, run_id="runtime-run", now=NOW,
    ).run()
    assert [call["turn"] for call in adapter.calls] == ["preflight", "draft", "candidate"]
    assert execution.candidate.report.stage_id == stage.stage_id
    assert PipelineRuntime(store).replay("runtime-run").stages[0].status == "succeeded"


def test_backend_mismatch_blocks_before_stage_start(tmp_path) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": {"backend_mismatch": True}},
    }, workspace=tmp_path)
    runner = StageRunner(
        store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
        stage=stage, run_id="runtime-run", now=NOW,
    )
    with pytest.raises(RuntimePreflightError, match="backend mismatch"):
        runner.prepare()
    assert PipelineRuntime(store).replay("runtime-run").stages[0].status == "ready"


def test_malformed_candidate_and_forbidden_write_do_not_succeed(tmp_path) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    malformed = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": {"inject": "malformed:candidate"}},
    }, workspace=tmp_path)
    runner = StageRunner(
        store=store, catalog=catalog, adapter=malformed, work_item=work, pipeline_revision=revision,
        stage=stage, run_id="runtime-run", now=NOW,
    )
    runner.draft()
    with pytest.raises(RuntimeOutputError, match="malformed runtime"):
        runner.candidate()
    assert PipelineRuntime(store).replay("runtime-run").stages[0].status == "active"


def test_correction_needed_and_session_mismatch_cannot_succeed(tmp_path) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": {
            "session_id": "session-1",
            "candidates": [{
                "outcome": "correction_needed", "findings": ["fix required"],
                "evidence": [{"evidence_type": "analysis", "content": "failed\n"}],
            }],
        }},
    }, workspace=tmp_path)
    runner = StageRunner(
        store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
        stage=stage, run_id="runtime-run", now=NOW,
    )
    runner.draft()
    with pytest.raises(RuntimeOutputError, match="cannot succeed"):
        runner.candidate()
    with pytest.raises(RuntimeSessionError, match="unknown"):
        adapter.candidate("wrong-session", read_only=True)
    assert PipelineRuntime(store).replay("runtime-run").stages[0].status == "active"


def test_backend_reported_session_mismatch_blocks_candidate(tmp_path) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": {"session_id": "session-1", "session_mismatch": True}},
    }, workspace=tmp_path)
    runner = StageRunner(
        store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
        stage=stage, run_id="runtime-run", now=NOW,
    )
    runner.draft()
    with pytest.raises(RuntimeSessionError, match="session mismatch"):
        runner.candidate()


def test_candidate_turn_workspace_mutation_is_blocked(tmp_path) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": {
            "candidate_writes": [{"path": "project/src/mutation.py", "content": "bad = True\n"}],
        }},
    }, workspace=tmp_path)
    runner = StageRunner(
        store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
        stage=stage, run_id="runtime-run", now=NOW,
    )
    runner.draft()
    with pytest.raises(RuntimeOutputError, match="candidate turn mutated"):
        runner.candidate()


def test_failure_injection_leaves_recoverable_store(tmp_path) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": {"inject": "failure:draft"}},
    }, workspace=tmp_path)
    runner = StageRunner(
        store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
        stage=stage, run_id="runtime-run", now=NOW,
    )
    with pytest.raises(Exception, match="injected"):
        runner.draft()
    reopened = V2ProjectStore(tmp_path)
    assert PipelineRuntime(reopened).replay("runtime-run").stages[0].status == "active"


@pytest.mark.parametrize(
    ("stage_name", "path", "content", "forbidden"),
    (
        ("architecture", "project/docs/architecture/partial.md", "allowed\n", False),
        ("discovery", "project/src/forbidden.py", "bad = True\n", True),
    ),
)
def test_failed_draft_writes_are_immediately_attributed_and_forbidden_paths_reported(
    tmp_path, stage_name, path, content, forbidden
) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path, stage_name)
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {
            "discovery": {},
            stage.stage_id: {
                "draft_writes": [{"path": path, "content": content}],
                "inject": "failure_after_write:draft",
            },
        },
    }, workspace=tmp_path)
    if stage_name != "discovery":
        discovery = next(item for item in revision.stages if item.stage == "discovery")
        StageRunner(
            store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
            stage=discovery, run_id="runtime-run", now=NOW,
        ).run()
    runner = StageRunner(
        store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
        stage=stage, run_id="runtime-run", now=NOW,
    )
    message = "forbidden changes" if forbidden else "changes recorded"
    with pytest.raises(RuntimeOutputError, match=message):
        runner.draft()
    changes = [record for record in store.records("change_set") if record.change_set_id.startswith("change-audit-")]
    assert any(entry.path == path for change in changes for entry in change.entries)
    assert (tmp_path / path).read_text(encoding="utf-8") == content


def test_malformed_draft_after_forbidden_write_is_audited_before_output_validation(tmp_path) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": {
            "draft_writes": [{"path": "project/src/forbidden.py", "content": "bad = True\n"}],
            "inject": "malformed:draft",
        }},
    }, workspace=tmp_path)
    with pytest.raises(RuntimeOutputError, match="forbidden changes.*project/src/forbidden.py"):
        StageRunner(
            store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
            stage=stage, run_id="runtime-run", now=NOW,
        ).draft()
    assert any(store.records("change_set"))


def test_context_capability_and_exact_session_recovery(tmp_path) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    scenario = {
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": {"session_id": "recover-session", "inject": "failure:candidate"}},
    }
    adapter = FakeRuntimeAdapter(scenario, workspace=tmp_path)
    first = StageRunner(
        store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
        stage=stage, run_id="runtime-run", now=NOW,
    )
    first.draft()
    with pytest.raises(Exception, match="injected"):
        first.candidate()
    scenario["stages"]["discovery"].pop("inject")
    recovered_adapter = FakeRuntimeAdapter(scenario, workspace=tmp_path)
    recovered = StageRunner(
        store=V2ProjectStore(tmp_path), catalog=catalog, adapter=recovered_adapter, work_item=work,
        pipeline_revision=revision, stage=stage, run_id="runtime-run", now=NOW,
    ).draft()
    assert recovered.session_id == "recover-session"
    assert recovered_adapter.calls[-1]["turn"] == "resume"
    assert PipelineRuntime(store).replay("runtime-run").stages[0].status == "active"


@pytest.mark.parametrize(
    ("field", "message"),
    [("context_mismatch", "exact rendered context"), ("missing_operation", "observed operation")],
)
def test_preflight_observation_and_context_mismatch_fail_closed(tmp_path, field, message) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    stage_scenario = {field: True if field == "context_mismatch" else "read"}
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": stage_scenario},
    }, workspace=tmp_path)
    runner = StageRunner(
        store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
        stage=stage, run_id="runtime-run", now=NOW,
    )
    with pytest.raises(Exception, match=message):
        runner.draft()


def test_fake_rejects_workspace_mismatch_and_never_writes_external_path(tmp_path) -> None:
    external = tmp_path / "external"
    external.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ValueError, match="canonical workspace"):
        FakeRuntimeAdapter({"workspace": str(external), "stages": {}}, workspace=workspace)
    assert not (external / "escape.txt").exists()


def test_rendered_context_delivers_objective_requirement_and_echoes_digest(tmp_path) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    content = f"Objective: {work.objective}\nRequirement: {work.acceptance_criteria[0].statement}"
    context = ContextItem(
        schema_version="2.0", kind="context_item", context_item_id="requirement-context",
        category="requirement", summary=content, digest=hashlib.sha256(content.encode()).hexdigest(),
    )
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": {"expected_context": work.acceptance_criteria[0].statement}},
    }, workspace=tmp_path)
    runner = StageRunner(
        store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
        stage=stage, run_id="runtime-run", now=NOW, context_items=(context,),
    )
    runner.draft()
    draft_call = next(call for call in adapter.calls if call["turn"] == "draft")
    assert content in draft_call["context_content"]
    assert any(
        '"assignment_scope":["project/**"]' in item
        for item in draft_call["context_content"]
    )
    assert len(draft_call["rendered_digest"]) == 64


def test_rendered_context_rejects_tampered_file_and_budgets(tmp_path) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    path = tmp_path / "project/requirement.txt"
    path.write_text("original", encoding="utf-8")
    context = ContextItem(
        schema_version="2.0", kind="context_item", context_item_id="file-context",
        category="requirement", summary="Requirement file", path="project/requirement.txt",
        digest=hashlib.sha256(b"original").hexdigest(),
    )
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"], "stages": {},
    }, workspace=tmp_path)
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(RuntimePreflightError, match="content digest mismatch"):
        StageRunner(
            store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
            stage=stage, run_id="runtime-run", now=NOW, context_items=(context,),
        ).prepare()

    large_root = tmp_path / "large"
    large_root.mkdir()
    catalog, work, store, revision, stage = _setup(large_root)
    content = "x" * (32 * 1024 + 1)
    oversized = context.model_copy(update={
        "context_item_id": "oversized-context", "path": None, "summary": content,
        "digest": hashlib.sha256(content.encode()).hexdigest(),
    })
    adapter = FakeRuntimeAdapter({
        "workspace": str(large_root), "catalog_digest": catalog.catalog_lock()["catalog_digest"], "stages": {},
    }, workspace=large_root)
    with pytest.raises(RuntimePreflightError, match="exceeds 32768 bytes"):
        StageRunner(
            store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
            stage=stage, run_id="runtime-run", now=NOW, context_items=(oversized,),
        ).prepare()


@pytest.mark.parametrize("stage_name", ("assurance", "review"))
def test_downstream_stages_reject_missing_upstream_context_before_adapter_turn(tmp_path, stage_name) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path, stage_name)
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"], "stages": {},
    }, workspace=tmp_path)
    with pytest.raises(RuntimePreflightError, match="implementation candidate context"):
        StageRunner(
            store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
            stage=stage, run_id="runtime-run", now=NOW,
        ).prepare()
    assert not adapter.calls


@pytest.mark.parametrize("probe_field", ("missing_probe", "failed_probe"))
def test_preflight_missing_or_failed_required_probe_blocks(tmp_path, probe_field) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    adapter = FakeRuntimeAdapter({
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": {probe_field: "send:mailbox"}},
    }, workspace=tmp_path)
    with pytest.raises(RuntimePreflightError, match="probe|operation"):
        StageRunner(
            store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
            stage=stage, run_id="runtime-run", now=NOW,
        ).prepare()


def test_restart_recovers_candidate_sequence_then_feedback_creates_candidate_two(tmp_path) -> None:
    catalog, work, store, revision, stage = _setup(tmp_path)
    scenario = {
        "workspace": str(tmp_path), "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": {"discovery": {
            "session_id": "persistent-session",
            "candidates": [
                {"outcome": "correction_needed", "findings": ["fix"], "evidence": [{"evidence_type": "analysis", "content": "failed\n"}]},
                {"outcome": "succeeded", "evidence": [{"evidence_type": "analysis", "content": "passed\n"}]},
            ],
        }},
    }
    first_adapter = FakeRuntimeAdapter(scenario, workspace=tmp_path)
    first = StageRunner(
        store=store, catalog=catalog, adapter=first_adapter, work_item=work, pipeline_revision=revision,
        stage=stage, run_id="runtime-run", now=NOW,
    )
    first.draft()
    assert first.candidate(succeed=False).candidate.report.candidate_report_id.endswith("-1")

    second_adapter = FakeRuntimeAdapter(scenario, workspace=tmp_path)
    second = StageRunner(
        store=V2ProjectStore(tmp_path), catalog=catalog, adapter=second_adapter, work_item=work,
        pipeline_revision=revision, stage=stage, run_id="runtime-run", now=NOW,
    )
    second.draft()
    second.feedback(DefectPacket(
        summary="Correct the candidate", criterion_ids=("criterion",),
    ))
    corrected = second.candidate()
    assert corrected.candidate.report.candidate_report_id.endswith("-2")
    assert second_adapter.calls[1]["turn"] == "resume"
