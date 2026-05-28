#!/usr/bin/env python3
"""LangGraph-backed Smith initial-planning runtime."""

from __future__ import annotations

import contextlib
import io
from pathlib import Path
from typing import Any, TypedDict

try:
    from langgraph.graph import END, StateGraph
except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing.
    raise RuntimeError("langgraph is required for Smith planning runtime") from exc

from worker_contracts import PlanningProjectContract
from worker_runtime import (
    PreparedArtifactRun,
    WorkerRuntimeError,
    append_log,
    complete_planning_run,
    load_state,
    prepare_planning_run,
    update_state,
    write_required_plan_drafts,
)


class SmithPlanningGraphState(TypedDict, total=False):
    envelope_raw: str
    run_dir: str
    prepare_output: str
    result_state: dict[str, Any]


def build_required_plan_graph(contract: PlanningProjectContract, *, output_sink: dict[str, str] | None = None):
    graph = StateGraph(SmithPlanningGraphState)

    def prepare(graph_state: SmithPlanningGraphState) -> dict[str, Any]:
        buffered_output = io.StringIO()
        with contextlib.redirect_stdout(buffered_output):
            prepared = prepare_planning_run(contract, graph_state["envelope_raw"])
        if output_sink is not None:
            output_sink["prepare_output"] = buffered_output.getvalue()
            output_sink["run_dir"] = str(prepared.run_dir)
        update_state(
            prepared.run_dir,
            runtime_engine="langgraph",
            graph_node="prepare",
        )
        append_log(prepared.run_dir, "graph", "smith graph prepare completed")
        return {
            "run_dir": str(prepared.run_dir),
            "prepare_output": buffered_output.getvalue(),
        }

    def draft_required_plan(graph_state: SmithPlanningGraphState) -> dict[str, Any]:
        run_dir = Path(graph_state["run_dir"])
        write_required_plan_drafts(contract, run_dir)
        update_state(
            run_dir,
            runtime_engine="langgraph",
            graph_node="draft_required_plan",
        )
        append_log(run_dir, "graph", "smith graph deterministic drafts written")
        return {}

    def complete(graph_state: SmithPlanningGraphState) -> dict[str, Any]:
        run_dir = Path(graph_state["run_dir"])
        state = complete_planning_run(contract, run_dir)
        update_state(
            run_dir,
            runtime_engine="langgraph",
            graph_node="complete",
        )
        append_log(run_dir, "graph", "smith graph complete succeeded")
        return {"result_state": load_state(run_dir)}

    graph.add_node("prepare", prepare)
    graph.add_node("draft_required_plan", draft_required_plan)
    graph.add_node("complete", complete)
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "draft_required_plan")
    graph.add_edge("draft_required_plan", "complete")
    graph.add_edge("complete", END)
    return graph.compile()


def autoplan_required_planning_project_graph(contract: PlanningProjectContract, envelope_raw: str) -> dict[str, Any]:
    result: dict[str, Any] | None = None
    output_sink: dict[str, str] = {}
    try:
        graph_result = build_required_plan_graph(contract, output_sink=output_sink).invoke({"envelope_raw": envelope_raw})
        result = graph_result.get("result_state")
    except WorkerRuntimeError:
        # Preserve current fallback contract: if deterministic drafting fails after
        # prepare, the model still receives the prepared work order and paths.
        if output_sink.get("prepare_output"):
            print(output_sink["prepare_output"], end="")
        raise
    if not result:
        raise WorkerRuntimeError("Smith graph completed without result state", code="runtime_error")
    return result
