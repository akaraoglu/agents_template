from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from .canonical import canonical_sha256
from .catalog import Catalog, load_catalog
from .compiler import compile_pipeline
from .evidence import compose_change_sets, workspace_manifest
from .mailbox import Mailbox
from .models import (
    AcceptanceCriterion,
    ActorRef,
    AssuranceDomain,
    CandidateReport,
    ChangeSet,
    ContextItem,
    EvidenceType,
    LeadDecision,
    MailboxMessage,
    MachineVerificationSpec,
    PipelineDefinition,
    PipelineRevision,
    VerificationCriterion,
    VerificationPlan,
    WorkItem,
)
from .pipeline_runtime import PipelineRuntime
from .runtime import (
    OpenCodeRuntimeAdapter,
    DEFAULT_OPENCODE_EXECUTABLE,
    DEFAULT_OPENCODE_MODEL,
    DefectPacket,
    FakeRuntimeAdapter,
    StageExecution,
    StageRunner,
)
from .sealing import close_candidate, seal_candidate
from .storage import V2ProjectStore
from .verification import VerificationExecutor, receipt_is_fresh
from .views import render_assurance, render_candidate, render_pipeline, render_status, write_view


FIXED_TIME = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
STAGE_NAMES = {
    "discovery": "Discovery",
    "architecture": "Architect",
    "ux": "UX",
    "implementation": "Developer",
    "verification": "Test",
    "assurance": "Assurance",
    "review": "Review",
}


@dataclass(frozen=True)
class CanaryResult:
    scenario: str
    workspace: str
    stage_order: tuple[str, ...]
    sessions: dict[str, str]
    revision: int
    defect_loop_count: int
    seal: str | None
    closure: str
    checks: dict[str, bool]
    plan: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "workspace": self.workspace,
            "stage_order": list(self.stage_order),
            "sessions": dict(sorted(self.sessions.items())),
            "revision": self.revision,
            "defect_loop_count": self.defect_loop_count,
            "seal": self.seal,
            "closure": self.closure,
            "checks": dict(sorted(self.checks.items())),
            **({"plan": self.plan} if self.plan is not None else {}),
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _work_item() -> WorkItem:
    return WorkItem(
        schema_version="2.0",
        kind="work_item",
        work_item_id="canary-fibonacci-cli",
        title="Deterministic Fibonacci CLI",
        objective="Deliver a stdlib-only CLI that prints fibonacci(7) as 13.",
        acceptance_criteria=(
            AcceptanceCriterion(
                id="cli-output",
                statement="The CLI prints exactly 13 followed by a newline for input 7.",
                required_evidence_types=(EvidenceType.TEST_OUTPUT,),
                verification=MachineVerificationSpec(
                    verifier_argv=("/usr/bin/python3", "project/tests/integration/test_cli.py"),
                    argv=("/usr/bin/python3", "project/src/fib.py", "7"),
                    expected_stdout="13\n",
                ),
            ),
        ),
        approved_scope=("project/**",),
    )


def _lead_decision(identifier: str, subject, rationale: str) -> LeadDecision:
    return LeadDecision(
        schema_version="2.0",
        kind="lead_decision",
        decision_id=identifier,
        decision="approve",
        subject=subject,
        rationale=rationale,
        decided_by=ActorRef(actor_id="canary-lead", kind="project_lead"),
        decided_at=FIXED_TIME,
    )


def _scenario(name: str, workspace: Path, catalog: Catalog, work: WorkItem) -> dict[str, Any]:
    correct = (
        "import sys\n\n"
        "def fibonacci(n: int) -> int:\n"
        "    a, b = 0, 1\n"
        "    for _ in range(n):\n"
        "        a, b = b, a + b\n"
        "    return a\n\n"
        "if __name__ == '__main__':\n"
        "    print(fibonacci(int(sys.argv[1])))\n"
    )
    broken = "import sys\n\nif __name__ == '__main__':\n    print(int(sys.argv[1]))\n"
    verification = cast(MachineVerificationSpec, work.acceptance_criteria[0].verification)
    command = tuple("/workspace/" + item if item.startswith("project/") else item for item in verification.argv)
    test = (
        "import subprocess\n\n"
        f"run = subprocess.run({command!r}, check=False, capture_output=True, text=True)\n"
        "assert run.returncode == 0, run.stderr\n"
        f"assert run.stdout == {verification.expected_stdout!r}, run.stdout\n"
        f"print({verification.expected_stdout!r}, end='')\n"
    )
    stages: dict[str, Any] = {
        "discovery": {"session_id": "session-discovery"},
        "architecture": {
            "session_id": "session-architect",
            "draft_writes": [{"path": "project/docs/architecture/CLI.md", "content": "# CLI Architecture\n\nOne stdlib module and one smoke test.\n"}],
        },
        "ux": {
            "session_id": "session-ux",
            "draft_writes": [{"path": "project/docs/design/CLI.md", "content": "# CLI Contract\n\n`fib.py 7` prints `13`.\n"}],
        },
        "implementation": {
            "session_id": "session-developer",
            "draft_writes": [
                {"path": "project/src/fib.py", "content": broken if name == "defect-loop" else correct},
                {"path": "project/tests/test_fib_unit.py", "content": "from project.src.fib import fibonacci\n\nassert fibonacci(7) == 13\n"},
            ],
            "feedback_writes": [{"path": "project/src/fib.py", "content": correct}],
        },
        "verification": {
            "session_id": "session-test",
            "draft_writes": [{"path": "project/tests/integration/test_cli.py", "content": test}],
        },
        "assurance": {"session_id": "session-assurance"},
        "review": {"session_id": "session-review"},
    }
    if name == "defect-loop":
        stages["verification"]["candidates"] = [
            {
                "outcome": "correction_needed",
                "findings": ["Input 7 prints 7 instead of 13."],
                "evidence": [{"evidence_type": "test_output", "content": "expected 13, observed 7\n"}],
            },
            {
                "outcome": "succeeded",
                "evidence": [{"evidence_type": "test_output", "content": "corrected CLI passed\n"}],
            },
        ]
    if name == "malformed":
        stages["discovery"]["inject"] = "malformed:candidate"
    if name == "forbidden-write":
        stages["discovery"]["draft_writes"] = [{"path": "project/src/forbidden.py", "content": "bad = True\n"}]
    if name == "assurance-fail":
        stages["assurance"]["candidates"] = [{
            "stage": "assurance", "outcome": "succeeded",
            "dispositions": [{"domain": "security_privacy", "disposition": "fail", "findings": [{
                "summary": "risk", "severity": "high", "blocking": True,
            }]}],
            "evidence": [{"evidence_type": "review", "content": "assurance failed\n"}],
        }]
    if name == "review-return":
        stages["review"]["candidates"] = [{
            "stage": "review", "outcome": "succeeded", "decision": "RETURN",
            "rationale": "Acceptance evidence is incomplete.",
            "evidence": [{"evidence_type": "review", "content": "returned\n"}],
        }]
    if name == "assurance-blocking":
        stages["assurance"]["candidates"] = [{
            "stage": "assurance", "outcome": "succeeded",
            "dispositions": [{"domain": "security_privacy", "disposition": "pass", "findings": [{
                "summary": "Unresolved critical risk", "severity": "critical", "blocking": True,
            }]}],
        }]
    if name == "review-blocking":
        stages["review"]["candidates"] = [{
            "stage": "review", "outcome": "succeeded", "decision": "ACCEPT",
            "rationale": "Contradictory structured acceptance.", "findings": [{
                "summary": "Unresolved high defect", "severity": "high", "blocking": False,
            }],
        }]
    if name == "missing-capability":
        stages["discovery"]["missing_operation"] = "read"
    if name == "context-mismatch":
        stages["discovery"]["context_mismatch"] = True
    if name == "external-workspace":
        stages["implementation"]["draft_writes"] = [{"path": "../external.txt", "content": "escape\n"}]
    return {
        "name": name,
        "workspace": str(workspace.resolve()),
        "catalog_digest": catalog.catalog_lock()["catalog_digest"],
        "stages": stages,
    }


def _copy_fixture(destination: Path) -> None:
    template = _repo_root() / "tests/e2e/codexteam-v2-canary/template"
    shutil.copytree(template, destination, dirs_exist_ok=True)


def _require_active_opencode_model(catalog: Catalog, model: str) -> None:
    active_models = {
        catalog.resolve_agent_spec(agent_spec_id).model_profile.model
        for agent_spec_id in catalog.ids("agent_spec")
    }
    if active_models != {model}:
        raise ValueError(
            f"OpenCode model {model!r} does not match all active AgentSpecs: {sorted(active_models)}"
        )


def _candidate(execution: StageExecution) -> CandidateReport:
    if execution.candidate is None:
        raise RuntimeError("stage did not produce a candidate")
    return execution.candidate.report


def _dependency_order(stages) -> tuple:
    remaining = {stage.stage_id: stage for stage in stages}
    ordered = []
    completed: set[str] = set()
    while remaining:
        ready = [stage for stage in remaining.values() if set(stage.dependencies) <= completed]
        if not ready:
            raise ValueError("pipeline stages contain an unresolved dependency cycle")
        for stage in ready:
            ordered.append(stage)
            completed.add(stage.stage_id)
            del remaining[stage.stage_id]
    return tuple(ordered)


def run_fake_canary(
    *,
    scenario: str = "happy",
    workspace: str | Path | None = None,
    dry_run: bool = False,
) -> CanaryResult:
    return _run_canary(
        scenario=scenario,
        workspace=workspace,
        dry_run=dry_run,
        live=False,
    )


def run_live_opencode_canary(
    *,
    model: str = DEFAULT_OPENCODE_MODEL,
    workspace: str | Path | None = None,
    dry_run: bool = False,
    timeout_seconds: int = 600,
    overall_timeout_seconds: int | None = 3600,
    executable: str | Path = DEFAULT_OPENCODE_EXECUTABLE,
) -> CanaryResult:
    return _run_canary(
        scenario="live-opencode",
        workspace=workspace,
        dry_run=dry_run,
        live=True,
        model=model,
        timeout_seconds=timeout_seconds,
        overall_timeout_seconds=overall_timeout_seconds,
        executable=executable,
    )


def _run_canary(
    *,
    scenario: str,
    workspace: str | Path | None,
    dry_run: bool,
    live: bool,
    model: str = DEFAULT_OPENCODE_MODEL,
    timeout_seconds: int = 600,
    overall_timeout_seconds: int | None = 3600,
    executable: str | Path = DEFAULT_OPENCODE_EXECUTABLE,
) -> CanaryResult:
    if not live and scenario not in {
        "happy", "defect-loop", "malformed", "forbidden-write", "assurance-fail",
        "review-return", "assurance-blocking", "review-blocking", "missing-capability", "context-mismatch", "external-workspace",
    }:
        raise ValueError(f"unknown fake scenario {scenario!r}")
    requested = Path(workspace).absolute() if workspace is not None else None
    if dry_run:
        plan = None
        if live:
            with tempfile.TemporaryDirectory(prefix="codexteam-v2-live-dry-run-") as temporary:
                root = Path(temporary)
                _copy_fixture(root)
                catalog = load_catalog(_repo_root() / "v2")
                _require_active_opencode_model(catalog, model)
                store = V2ProjectStore(root)
                work = _work_item()
                store.write_immutable(work, work.work_item_id)
                lead = ActorRef(actor_id="canary-lead", kind="project_lead")
                compiled = compile_pipeline(catalog, work, (), lead, FIXED_TIME)
                decision = _lead_decision(
                    "decision-dry-run-plan", compiled.refs.plan, "Authorize ephemeral dry-run preflight."
                )
                projection = PipelineRuntime(store, catalog=catalog).initialize(
                    "canary-dry-run", compiled.plan, decision, created_at=FIXED_TIME
                )
                revision = cast(PipelineRevision, store.resolve(projection.pipeline_revision))
                adapter = OpenCodeRuntimeAdapter(
                    catalog=catalog, executable=executable, model=model,
                    timeout_seconds=timeout_seconds,
                    overall_timeout_seconds=overall_timeout_seconds,
                )
                summary = f"Objective: {work.objective}\nRequirement: {work.acceptance_criteria[0].statement}"
                requirement = ContextItem(
                    schema_version="2.0", kind="context_item",
                    context_item_id="context-dry-run-requirement", category="requirement",
                    summary=summary, digest=hashlib.sha256(summary.encode("utf-8")).hexdigest(),
                )
                StageRunner(
                    store=store, catalog=catalog, adapter=adapter, work_item=work,
                    pipeline_revision=revision,
                    stage=next(stage for stage in revision.stages if stage.stage == "discovery"),
                    run_id="canary-dry-run", now=FIXED_TIME, context_items=(requirement,),
                ).prepare()
                writer_stage = next(stage for stage in revision.stages if stage.stage == "implementation")
                try:
                    StageRunner(
                        store=store, catalog=catalog, adapter=adapter, work_item=work,
                        pipeline_revision=revision, stage=writer_stage,
                        run_id="canary-dry-run", now=FIXED_TIME, context_items=(requirement,),
                    ).prepare()
                except Exception as exc:
                    if "impossible stage transition" not in str(exc):
                        raise
                plan = adapter.dry_run_plan(root)
        return CanaryResult(
            scenario, str(requested or "<temporary>"), (), {}, 0, 0, None,
            "dry-run", {"model_calls": False, "nonmutating": True}, plan,
        )
    temporary = None
    if requested is None:
        if live:
            root = Path(tempfile.mkdtemp(prefix="codexteam-v2-live-canary-"))
        else:
            temporary = tempfile.TemporaryDirectory(prefix="codexteam-v2-canary-")
            root = Path(temporary.name)
    else:
        root = requested
    if requested is not None:
        if root.exists() and any(root.iterdir()):
            raise ValueError("canary workspace must be absent or empty")
        root.mkdir(parents=True, exist_ok=True)
    try:
        _copy_fixture(root)
        catalog = load_catalog(_repo_root() / "v2")
        if live:
            _require_active_opencode_model(catalog, model)
        store = V2ProjectStore(root)
        work = _work_item()
        work_ref = store.write_immutable(work, work.work_item_id)
        lead = ActorRef(actor_id="canary-lead", kind="project_lead")
        compiled = compile_pipeline(catalog, work, (), lead, FIXED_TIME)
        plan_decision = _lead_decision("decision-initial-plan", compiled.refs.plan, "Approve initial required-only plan.")
        runtime = PipelineRuntime(store, catalog=catalog)
        projection = runtime.initialize("canary-run", compiled.plan, plan_decision, created_at=FIXED_TIME)
        revision = cast(PipelineRevision, store.resolve(projection.pipeline_revision))
        adapter = (
            OpenCodeRuntimeAdapter(
                catalog=catalog,
                executable=executable,
                model=model,
                timeout_seconds=timeout_seconds,
                overall_timeout_seconds=overall_timeout_seconds,
            )
            if live
            else FakeRuntimeAdapter(_scenario(scenario, root, catalog, work), workspace=root)
        )
        requirement = ContextItem(
            schema_version="2.0",
            kind="context_item",
            context_item_id="context-requirement",
            category="requirement",
            summary=f"Objective: {work.objective}\nRequirement: {work.acceptance_criteria[0].statement}",
            digest=hashlib.sha256(
                f"Objective: {work.objective}\nRequirement: {work.acceptance_criteria[0].statement}".encode("utf-8")
            ).hexdigest(),
        )
        executions: dict[str, StageExecution] = {}
        runners: dict[str, StageRunner] = {}
        writing_changes: list[ChangeSet] = []

        discovery_stage = next(stage for stage in revision.stages if stage.stage == "discovery")
        discovery_runner = StageRunner(
            store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
            stage=discovery_stage, run_id="canary-run", now=FIXED_TIME, context_items=(requirement,),
        )
        runners[discovery_stage.stage_id] = discovery_runner
        executions[discovery_stage.stage_id] = discovery_runner.run()
        discovery_execution = executions[discovery_stage.stage_id]
        assert discovery_execution.candidate is not None
        initial_base = discovery_execution.candidate.base_manifest

        pipeline = cast(PipelineDefinition, catalog.get("pipeline_definition", "adaptive-verified-delivery"))
        semantic_discovery = discovery_execution.semantic_candidate
        if semantic_discovery is None or semantic_discovery.stage != "discovery":
            raise RuntimeError("Discovery did not return typed selection output")
        optional = tuple(stage for stage in pipeline.stages if stage.stage in semantic_discovery.requested_optional_stages)
        discovery_actor = ActorRef(
            actor_id="agent-discovery", kind="agent",
            role_instance_id=discovery_execution.prepared.role_instance.role_instance_id,
        )
        request = MailboxMessage(
            schema_version="2.0", kind="mailbox_message", message_id="request-architecture-ux",
            sender=discovery_actor, recipient=ActorRef(actor_id="canary-orchestrator", kind="orchestrator"),
            correlation_id="adaptive-selection", idempotency_key="adaptive-selection", created_at=FIXED_TIME,
            body={
                "kind": "pipeline_change_request", "requested_stages": optional,
                "rationale": semantic_discovery.rationale,
                "discovery_candidate": discovery_execution.candidate.report_ref,
            },
        )
        request_ref = Mailbox(
            store, active_role_instance=store.reference(discovery_execution.prepared.role_instance)
        ).submit(request, discovery_actor, submitted_at=FIXED_TIME).message
        change_decision = _lead_decision("decision-adaptive-stages", request_ref, "Architecture and UX are useful and in scope.")
        projection = runtime.approve_change_request(
            "canary-run", request_ref, change_decision, work,
            expected_state_revision=runtime.replay("canary-run").state_revision,
            created_at=FIXED_TIME, catalog=catalog,
        )
        revision = cast(PipelineRevision, store.resolve(projection.pipeline_revision))

        ordered_stages = _dependency_order(revision.stages)
        implementation_stage = next(stage for stage in ordered_stages if stage.stage == "implementation")
        for stage in ordered_stages:
            if stage.stage not in {"architecture", "ux", "implementation"}:
                continue
            runner = StageRunner(
                store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
                stage=stage, run_id="canary-run", now=FIXED_TIME, context_items=(requirement,),
            )
            runners[stage.stage_id] = runner
            executions[stage.stage_id] = runner.run()
            processed = executions[stage.stage_id].candidate
            assert processed is not None
            writing_changes.append(processed.change_set)

        verification_stage = next(stage for stage in ordered_stages if stage.stage == "verification")
        test_runner = StageRunner(
            store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
            stage=verification_stage, run_id="canary-run", now=FIXED_TIME, context_items=(requirement,),
            producer_candidate=_candidate(executions[implementation_stage.stage_id]),
        )
        runners[verification_stage.stage_id] = test_runner
        test_runner.draft()
        defect_count = 0
        stale_rerun = False
        verification_candidate = test_runner.candidate(succeed=scenario != "defect-loop")
        assert verification_candidate.candidate is not None
        writing_changes.append(verification_candidate.candidate.change_set)

        developer_candidate = _candidate(executions[implementation_stage.stage_id])
        cumulative = compose_change_sets(initial_base, writing_changes)
        store.write_immutable(cumulative, cumulative.change_set_id)
        plan = VerificationPlan(
            schema_version="2.0", kind="verification_plan", verification_plan_id="canary-verification-plan",
            work_item=work_ref,
            criteria=tuple(
                VerificationCriterion(
                    criterion_id=item.id, statement=item.statement,
                    required_evidence_types=item.required_evidence_types, verification=item.verification,
                ) for item in work.acceptance_criteria
            ),
            commands=tuple(
                cast(MachineVerificationSpec, item.verification).verifier_argv
                for item in work.acceptance_criteria
            ), created_at=FIXED_TIME,
        )
        verifier = ActorRef(
            actor_id="agent-verification", kind="agent",
            role_instance_id=test_runner.prepare().role_instance.role_instance_id,
        )
        first_receipt = VerificationExecutor(store).execute(
            plan, developer_candidate, cumulative, issued_by=verifier,
            criterion_commands={"cli-output": (0,)}, timeout_seconds=10,
            issued_at=FIXED_TIME, recorded_at=FIXED_TIME,
        )

        if scenario == "defect-loop":
            defect_count = 1
            if first_receipt.accepted:
                raise RuntimeError("defect-loop verification unexpectedly passed")
            defect_message = MailboxMessage(
                schema_version="2.0", kind="mailbox_message", message_id="verification-defect-1",
                sender=verifier, recipient=ActorRef(actor_id="canary-orchestrator", kind="orchestrator"),
                correlation_id="verification-defect", idempotency_key="verification-defect-1", created_at=FIXED_TIME,
                body={
                    "kind": "verification_defect", "summary": "CLI output differs from the acceptance criterion.",
                    "criterion_ids": ("cli-output",), "evidence": (store.reference(first_receipt),),
                },
            )
            Mailbox(store).submit(defect_message, verifier, submitted_at=FIXED_TIME)
            developer_runner = runners[implementation_stage.stage_id]
            developer_runner.refresh_baseline()
            developer_runner.feedback(DefectPacket(summary="Make input 7 print exactly 13.", criterion_ids=("cli-output",)))
            executions[implementation_stage.stage_id] = developer_runner.candidate()
            corrected_candidate = executions[implementation_stage.stage_id].candidate
            assert corrected_candidate is not None
            writing_changes.append(corrected_candidate.change_set)
            developer_candidate = _candidate(executions[implementation_stage.stage_id])
            cumulative = compose_change_sets(initial_base, writing_changes)
            store.write_immutable(cumulative, cumulative.change_set_id)
            stale_rerun = not receipt_is_fresh(
                first_receipt, developer_candidate, cumulative, workspace_manifest(root, created_at=FIXED_TIME)
            )
            test_runner.refresh_baseline()
            verification_candidate = test_runner.candidate()
            assert verification_candidate.candidate is not None
            writing_changes.append(verification_candidate.candidate.change_set)
            cumulative = compose_change_sets(initial_base, writing_changes)
            store.write_immutable(cumulative, cumulative.change_set_id)
            receipt = VerificationExecutor(store).execute(
                plan, developer_candidate, cumulative, issued_by=verifier,
                criterion_commands={"cli-output": (0,)}, timeout_seconds=10,
                issued_at=FIXED_TIME, recorded_at=FIXED_TIME,
            )
        else:
            receipt = first_receipt
        if not receipt.accepted:
            raise RuntimeError("canary verification did not produce an accepted receipt")
        test_runner.producer_candidate = developer_candidate
        test_runner.accept_verification(store.reference(receipt))
        accepted_verification = test_runner.accepted_verification_candidate
        if accepted_verification is None:
            raise RuntimeError("accepted receipt did not produce a verified candidate")
        executions[verification_stage.stage_id] = StageExecution(
            verification_candidate.prepared,
            verification_candidate.session_id,
            verification_candidate.response,
            accepted_verification,
            verification_candidate.semantic_candidate,
        )

        assurance_record = None
        for stage in ordered_stages:
            if stage.stage not in {"assurance", "review"}:
                continue
            runner = StageRunner(
                store=store, catalog=catalog, adapter=adapter, work_item=work, pipeline_revision=revision,
                stage=stage, run_id="canary-run", now=FIXED_TIME, context_items=(requirement,),
                producer_candidate=developer_candidate,
                verification_receipts=(receipt,),
                assurance_report=assurance_record if stage.stage == "review" else None,
            )
            runners[stage.stage_id] = runner
            executions[stage.stage_id] = runner.run()
            if stage.stage == "assurance" and any(
                item.disposition != "pass"
                for item in cast(Any, executions[stage.stage_id].assurance_report).dispositions
            ):
                raise RuntimeError("canary assurance did not pass")
            if stage.stage == "assurance":
                assurance_record = executions[stage.stage_id].assurance_report
            if stage.stage == "review" and cast(Any, executions[stage.stage_id].review_decision).decision != "ACCEPT":
                raise RuntimeError("canary review did not accept")

        assurance_stage = next(stage for stage in ordered_stages if stage.stage == "assurance")
        review_stage = next(stage for stage in ordered_stages if stage.stage == "review")
        implementation = _candidate(executions[implementation_stage.stage_id])
        assurance = executions[assurance_stage.stage_id].assurance_report
        if assurance is None:
            raise RuntimeError("Assurance stage did not produce an authoritative report")
        assurance_ref = store.reference(assurance)
        review = executions[review_stage.stage_id].review_decision
        if review is None:
            raise RuntimeError("Review stage did not produce an authoritative decision")
        review_ref = store.reference(review)
        final_decision = _lead_decision("decision-accept-candidate", review_ref, "Accept independently verified candidate.")
        store.write_immutable(final_decision, final_decision.decision_id)
        final_projection = runtime.replay("canary-run")
        ordered_executions = [executions[stage.stage_id] for stage in ordered_stages]
        seal = seal_candidate(
            store, project_id="codexteam-v2-canary", runtime=final_projection, work_item=work,
            pipeline_revision=revision,
            role_instances=tuple(item.prepared.role_instance for item in ordered_executions),
            context_packs=tuple(item.prepared.context_pack for item in ordered_executions),
            stage_candidates=tuple(_candidate(item) for item in ordered_executions),
            base_manifest=initial_base, cumulative_change_set=cumulative,
            verification_receipts=(receipt,), assurance_report=assurance,
            review_decision=review, lead_decision=final_decision, sealed_by=lead,
            required_assurance_domains=(AssuranceDomain.SECURITY_PRIVACY,), sealed_at=FIXED_TIME,
        )
        closure = close_candidate(store, seal, closed_by=lead)
        write_view(store, "pipeline", render_pipeline(final_projection))
        write_view(store, "status", render_status(final_projection))
        write_view(store, "assurance", render_assurance(assurance, (receipt,)))
        write_view(store, "candidate", render_candidate(seal))
        order = tuple(STAGE_NAMES[stage.stage] for stage in ordered_stages)
        upstream_context_delivered = True
        if isinstance(adapter, FakeRuntimeAdapter):
            draft_context = {
                call["stage"]: "\n".join(call["context_content"])
                for call in adapter.calls
                if call["turn"] in {"draft", "resume"} and "context_content" in call
            }
            producer_ref = store.reference(implementation)
            upstream_context_delivered = (
                producer_ref.record_id in draft_context[assurance_stage.stage_id]
                and producer_ref.digest in draft_context[assurance_stage.stage_id]
                and receipt.verification_receipt_id in draft_context[assurance_stage.stage_id]
                and '"accepted":true' in draft_context[assurance_stage.stage_id]
                and assurance.assurance_report_id in draft_context[review_stage.stage_id]
            )
        return CanaryResult(
            scenario=scenario, workspace=str(root), stage_order=order, sessions=adapter.sessions,
            revision=revision.revision_number, defect_loop_count=defect_count,
            seal=seal.seal_id, closure=closure.status,
            checks={
                "adaptive_both_stages": order == ("Discovery", "Architect", "UX", "Developer", "Test", "Assurance", "Review"),
                "accepted_receipt": receipt.accepted,
                "all_runtime_stages_succeeded": final_projection.complete,
                "closed": closure.status == "closed",
                "same_sessions": all(adapter.sessions.get(stage.stage_id) for stage in ordered_stages),
                "stale_evidence_rerun": stale_rerun if scenario == "defect-loop" else True,
                "upstream_context_delivered": upstream_context_delivered,
            },
        )
    except Exception as exc:
        if live:
            raise RuntimeError(f"live canary failed; workspace preserved at {root}: {exc}") from exc
        raise
    finally:
        if temporary is not None:
            temporary.cleanup()


__all__ = [
    "CanaryResult", "FIXED_TIME", "_dependency_order", "run_fake_canary", "run_live_opencode_canary"
]
