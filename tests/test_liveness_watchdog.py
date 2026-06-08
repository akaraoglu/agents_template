from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "AgenticTeam" / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import liveness_watchdog as lw
from liveness_watchdog import (
    DEFAULT_IDLE_SECONDS,
    classify_liveness,
    niaobe_ack_terminal_pending,
    parse_project_id,
    process_project,
    reap_niaobe_ack,
    reap_project,
    worker_terminal_pending,
)
from transition_guard import read_ledger
import worker_runtime


def _state(
    *,
    owner: str = "niaobe",
    active_task: str = "T001",
    task_phase: str = "IMPLEMENT",
    task_status: str = "IN_PROGRESS",
    waiting_for: str = "morpheus",
) -> dict[str, str]:
    return {
        "owner": owner,
        "active_task": active_task,
        "task_phase": task_phase,
        "task_status": task_status,
        "waiting_for": waiting_for,
        "last_completed_task": "none",
        "last_task_result": "none",
    }


def helper_ok_output(action: str) -> str:
    return f"STATUS: OK\nACTION: {action}\n"


def _ack_state(
    *,
    owner: str = "smith",
    active_task: str = "T002",
    task_phase: str = "TASK_HANDOFF",
    task_status: str = "READY",
    waiting_for: str = "niaobe",
) -> dict[str, str]:
    return _state(
        owner=owner,
        active_task=active_task,
        task_phase=task_phase,
        task_status=task_status,
        waiting_for=waiting_for,
    )


class ClassifyLivenessTests(unittest.TestCase):
    """Pure decision logic — no IO."""

    NOW = 10_000.0

    def _classify(self, state, *, idle, threshold=DEFAULT_IDLE_SECONDS, terminal=False):
        return classify_liveness(
            state,
            now_epoch=self.NOW,
            last_activity_epoch=self.NOW - idle,
            idle_threshold=threshold,
            terminal_pending=terminal,
        )

    def test_skip_when_not_niaobe_owned(self) -> None:
        d = self._classify(_state(owner="smith"), idle=9999)
        self.assertEqual(d.action, "skip")
        self.assertIn("not niaobe", d.reason)

    def test_skip_when_waiting_for_not_worker(self) -> None:
        d = self._classify(_state(waiting_for="niaobe"), idle=9999)
        self.assertEqual(d.action, "skip")
        self.assertIn("not a worker", d.reason)

    def test_skip_when_status_not_in_progress(self) -> None:
        d = self._classify(_state(task_status="BLOCKED"), idle=9999)
        self.assertEqual(d.action, "skip")
        self.assertIn("not IN_PROGRESS", d.reason)

    def test_skip_when_phase_mismatch(self) -> None:
        # morpheus is awaited but phase says DESIGN (architect's phase)
        d = self._classify(_state(waiting_for="morpheus", task_phase="DESIGN"), idle=9999)
        self.assertEqual(d.action, "skip")
        self.assertIn("expected IMPLEMENT", d.reason)

    def test_skip_when_within_idle_budget(self) -> None:
        d = self._classify(_state(), idle=10, threshold=1800)
        self.assertEqual(d.action, "skip")
        self.assertIn("< threshold", d.reason)

    def test_reap_when_stale_no_terminal(self) -> None:
        d = self._classify(_state(), idle=3600, threshold=1800)
        self.assertEqual(d.action, "reap")
        self.assertEqual(d.role, "morpheus")
        self.assertEqual(d.phase, "IMPLEMENT")
        self.assertEqual(d.task_id, "T001")

    def test_terminal_pending_guard_blocks_reap(self) -> None:
        # 1502-class: worker produced a terminal result -> do NOT reap.
        d = self._classify(_state(), idle=3600, threshold=1800, terminal=True)
        self.assertEqual(d.action, "worker_terminal_pending")

    def test_architect_and_oracle_expected_phases(self) -> None:
        arch = self._classify(_state(waiting_for="architect", task_phase="DESIGN"), idle=9999)
        oracle = self._classify(_state(waiting_for="oracle", task_phase="VERIFY"), idle=9999)
        self.assertEqual(arch.action, "reap")
        self.assertEqual(oracle.action, "reap")

    def test_missing_activity_treated_as_infinitely_stale(self) -> None:
        d = classify_liveness(
            _state(),
            now_epoch=self.NOW,
            last_activity_epoch=None,
            idle_threshold=1800,
            terminal_pending=False,
        )
        self.assertEqual(d.action, "reap")


class ClassifyNiaobeAckTests(unittest.TestCase):
    """Pure decision logic for the second (niaobe-ack) liveness class."""

    NOW = 10_000.0

    def _classify(self, state, *, idle, threshold=DEFAULT_IDLE_SECONDS, terminal=False):
        return classify_liveness(
            state,
            now_epoch=self.NOW,
            last_activity_epoch=self.NOW - idle,
            idle_threshold=threshold,
            terminal_pending=terminal,
        )

    def test_reap_when_ack_stale(self) -> None:
        d = self._classify(_ack_state(), idle=4000)
        self.assertEqual(d.action, "reap_niaobe_ack")
        self.assertEqual(d.role, "niaobe")
        self.assertEqual(d.task_id, "T002")

    def test_skip_when_within_budget(self) -> None:
        d = self._classify(_ack_state(), idle=100)
        self.assertEqual(d.action, "skip")
        self.assertIn("< threshold", d.reason)

    def test_terminal_pending_blocks_reap(self) -> None:
        d = self._classify(_ack_state(), idle=4000, terminal=True)
        self.assertEqual(d.action, "niaobe_ack_terminal_pending")

    def test_smith_owner_not_in_handoff_is_plain_skip(self) -> None:
        # owner=smith but task_status not READY -> not the ack class.
        d = self._classify(_ack_state(task_status="IN_PROGRESS"), idle=4000)
        self.assertEqual(d.action, "skip")
        self.assertIn("not niaobe", d.reason)

    def test_smith_owner_wrong_phase_is_plain_skip(self) -> None:
        d = self._classify(_ack_state(task_phase="DESIGN"), idle=4000)
        self.assertEqual(d.action, "skip")
        self.assertIn("not niaobe", d.reason)


class WatchdogIOTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.workspace_root = Path(self.temp_dir.name) / "workspaces"
        self.bin_root = Path(self.temp_dir.name) / "bin"
        self.project_path = Path(self.temp_dir.name) / "projects" / "demo-project"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.bin_root.mkdir(parents=True, exist_ok=True)
        self.project_path.mkdir(parents=True, exist_ok=True)
        self.env_patch = mock.patch.dict(
            os.environ,
            {
                "CLAWSPACE_WORKSPACE_ROOT": str(self.workspace_root),
                "CLAWSPACE_BIN_ROOT": str(self.bin_root),
            },
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.calls: list[list[str]] = []

    def _seed_state(
        self,
        *,
        owner: str = "niaobe",
        active_task: str = "T001",
        task_phase: str = "IMPLEMENT",
        task_status: str = "IN_PROGRESS",
        waiting_for: str = "morpheus",
        project_id: str = "demo-project",
        mtime: float | None = None,
    ) -> None:
        content = "\n".join(
            [
                "# Project State",
                "",
                "## Status",
                f"- **project_id**: {project_id}",
                f"- **owner**: {owner}",
                f"- **active_task**: {active_task}",
                f"- **task_phase**: {task_phase}",
                f"- **task_status**: {task_status}",
                f"- **waiting_for**: {waiting_for}",
                "- **last_completed_task**: none",
                "",
            ]
        )
        state_file = self.project_path / "PROJECT_STATE.md"
        state_file.write_text(content, encoding="utf-8")
        if mtime is not None:
            os.utime(state_file, (mtime, mtime))

    def _write_latest_pointer(
        self, role: str, *, signal: str, task_id: str = "T001", mtime: float | None = None
    ) -> None:
        pointer = worker_runtime.child_latest_pointer_path(role, "demo-project", task_id)
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(
            json.dumps({"task_id": task_id, "from": role, "signal": signal, "run_id": "abc123"}),
            encoding="utf-8",
        )
        if mtime is not None:
            for entry in (pointer, *pointer.parent.rglob("*"), pointer.parent):
                os.utime(entry, (mtime, mtime))

    def _fake_run(self, cmd, capture_output=True, text=True, timeout=120, *args, **kwargs):
        del capture_output, text, timeout, args, kwargs
        self.calls.append(list(cmd))
        if cmd[:2] == ["bash", str(self.bin_root / "write_state.sh")]:
            return mock.Mock(returncode=0, stdout=helper_ok_output("write_state"), stderr="")
        if cmd[:4] == ["openclaw", "gateway", "call", "sessions.send"]:
            return mock.Mock(returncode=0, stdout='{"ok":true}', stderr="")
        raise AssertionError(f"unexpected command: {' '.join(cmd)}")

    # -- parse_project_id ----------------------------------------------------
    def test_parse_project_id_from_state_file(self) -> None:
        self._seed_state(project_id="run-e2e-fibonacci-test-20260605-1430")
        self.assertEqual(
            parse_project_id(self.project_path), "run-e2e-fibonacci-test-20260605-1430"
        )

    def test_parse_project_id_falls_back_to_dir_name(self) -> None:
        (self.project_path / "PROJECT_STATE.md").write_text("# empty\n", encoding="utf-8")
        self.assertEqual(parse_project_id(self.project_path), "demo-project")

    # -- worker_terminal_pending --------------------------------------------
    def test_terminal_pointer_detected(self) -> None:
        self._write_latest_pointer("morpheus", signal="COMPLETE")
        self.assertTrue(worker_terminal_pending("morpheus", "demo-project", "T001"))

    def test_nonterminal_pointer_not_detected(self) -> None:
        self._write_latest_pointer("morpheus", signal="RUNNING")
        self.assertFalse(worker_terminal_pending("morpheus", "demo-project", "T001"))

    def test_pointer_for_other_task_ignored(self) -> None:
        self._write_latest_pointer("morpheus", signal="COMPLETE", task_id="T002")
        self.assertFalse(worker_terminal_pending("morpheus", "demo-project", "T001"))

    def test_oracle_terminal_detected_via_result_json(self) -> None:
        # Oracle writes result.json but NO LATEST.json pointer.
        run_dir = worker_runtime.child_latest_pointer_path("oracle", "demo-project", "T001").parent / "run-1"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "result.json").write_text(
            json.dumps(
                {
                    "status": "sent",
                    "task_id": "T001",
                    "signal": {"from": "oracle", "task_id": "T001", "signal": "COMPLETE"},
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(worker_terminal_pending("oracle", "demo-project", "T001"))

    def test_morpheus_runtime_activity_counts_as_active(self) -> None:
        # Morpheus writes drafts under runtime/<run_id>, not the runs/ tree.
        run_id = "20260605T093000Z-deadbeef"
        runs_run = worker_runtime.child_latest_pointer_path("morpheus", "demo-project", "T001").parent / run_id
        runs_run.mkdir(parents=True, exist_ok=True)
        runtime_dir = lw.workspace_root() / "morpheus" / "runtime" / run_id
        runtime_dir.mkdir(parents=True, exist_ok=True)
        now = time.time()
        # Age the runs/ tree, keep runtime/ fresh.
        for entry in (runs_run, runs_run.parent):
            os.utime(entry, (now - 4000, now - 4000))
        (runtime_dir / "draft.py").write_text("x", encoding="utf-8")
        activity = lw.worker_last_activity_epoch("morpheus", "demo-project", "T001")
        self.assertIsNotNone(activity)
        self.assertGreater(activity, now - 100)

    # -- process_project / reap ---------------------------------------------
    def test_reap_stale_worker_drives_block_and_smith(self) -> None:
        old = time.time() - 4000
        self._seed_state(mtime=old)
        with mock.patch.object(worker_runtime.subprocess, "run", side_effect=self._fake_run):
            result = process_project(self.project_path, idle_threshold=1800)

        self.assertEqual(result.outcome, "reaped")
        write_state_calls = [c for c in self.calls if c[:2] == ["bash", str(self.bin_root / "write_state.sh")]]
        self.assertEqual(len(write_state_calls), 1)
        self.assertIn("BLOCKED", write_state_calls[0])
        self.assertIn("smith", write_state_calls[0])
        send_calls = [c for c in self.calls if c[:4] == ["openclaw", "gateway", "call", "sessions.send"]]
        self.assertEqual(len(send_calls), 1)
        ledger = read_ledger(self.project_path)
        self.assertTrue(any(e.get("outcome") == "reaped_blocked" for e in ledger))

    def test_dry_run_does_not_block(self) -> None:
        old = time.time() - 4000
        self._seed_state(mtime=old)
        with mock.patch.object(worker_runtime.subprocess, "run", side_effect=self._fake_run):
            result = process_project(self.project_path, idle_threshold=1800, dry_run=True)
        self.assertEqual(result.outcome, "would_reap")
        self.assertEqual(self.calls, [])

    def test_terminal_pending_project_is_skipped(self) -> None:
        # 1502-class: worker finished (terminal pointer) but parent hangs.
        old = time.time() - 4000
        self._seed_state(mtime=old)
        self._write_latest_pointer("morpheus", signal="COMPLETE", mtime=old)
        with mock.patch.object(worker_runtime.subprocess, "run", side_effect=self._fake_run):
            result = process_project(self.project_path, idle_threshold=1800)
        self.assertEqual(result.outcome, "skipped")
        self.assertEqual(result.decision.action, "worker_terminal_pending")
        self.assertEqual(self.calls, [])

    def test_fresh_worker_within_budget_is_skipped(self) -> None:
        self._seed_state(mtime=time.time())
        with mock.patch.object(worker_runtime.subprocess, "run", side_effect=self._fake_run):
            result = process_project(self.project_path, idle_threshold=1800)
        self.assertEqual(result.outcome, "skipped")
        self.assertEqual(self.calls, [])

    def test_reap_stands_down_when_state_no_longer_current(self) -> None:
        # Defensive re-check: state already advanced past the worker -> no block.
        self._seed_state(owner="smith", task_status="BLOCKED", waiting_for="niaobe")
        decision = lw.LivenessDecision(
            "reap", "synthetic", role="morpheus", task_id="T001", phase="IMPLEMENT", idle_seconds=4000
        )
        with mock.patch.object(worker_runtime.subprocess, "run", side_effect=self._fake_run):
            result = reap_project(self.project_path, "demo-project", decision)
        self.assertEqual(result.outcome, "superseded")
        self.assertEqual(self.calls, [])

    def test_second_pass_after_reap_is_idempotent(self) -> None:
        # Simulate that the block advanced state (write_state.sh is mocked, so we
        # flip the file by hand to mirror its real effect), then re-run.
        self._seed_state(owner="smith", task_status="BLOCKED", waiting_for="niaobe")
        with mock.patch.object(worker_runtime.subprocess, "run", side_effect=self._fake_run):
            result = process_project(self.project_path, idle_threshold=1800)
        self.assertEqual(result.outcome, "skipped")
        self.assertEqual(self.calls, [])

    # -- niaobe-ack class ----------------------------------------------------
    def _write_niaobe_result(
        self, *, status: str, task_id: str = "T002", mtime: float | None = None
    ) -> None:
        runs_dir = lw.niaobe_runs_dir("demo-project", task_id) / "run-1"
        runs_dir.mkdir(parents=True, exist_ok=True)
        result = runs_dir / "result.json"
        result.write_text(
            json.dumps({"status": status, "task_id": task_id}), encoding="utf-8"
        )
        if mtime is not None:
            os.utime(result, (mtime, mtime))

    def test_niaobe_ack_terminal_pending_mtime_gated(self) -> None:
        old = time.time() - 4000
        self._seed_state(
            owner="smith",
            active_task="T002",
            task_phase="TASK_HANDOFF",
            task_status="READY",
            waiting_for="niaobe",
            mtime=old,
        )
        state_mtime = lw.project_state_mtime(self.project_path)
        # A niaobe result OLDER than the current handoff must NOT count (stale gen).
        self._write_niaobe_result(status="sent", mtime=old - 100)
        self.assertFalse(
            niaobe_ack_terminal_pending("demo-project", "T002", state_mtime)
        )
        # A niaobe result NEWER than the handoff proves this generation was acked.
        self._write_niaobe_result(status="sent", mtime=time.time())
        self.assertTrue(
            niaobe_ack_terminal_pending("demo-project", "T002", state_mtime)
        )

    def test_reap_niaobe_ack_drives_block_and_smith(self) -> None:
        old = time.time() - 4000
        self._seed_state(
            owner="smith",
            active_task="T002",
            task_phase="TASK_HANDOFF",
            task_status="READY",
            waiting_for="niaobe",
            mtime=old,
        )
        with mock.patch.object(worker_runtime.subprocess, "run", side_effect=self._fake_run):
            result = process_project(self.project_path, idle_threshold=1800)

        self.assertEqual(result.outcome, "reaped")
        self.assertEqual(result.decision.action, "reap_niaobe_ack")
        write_state_calls = [
            c for c in self.calls if c[:2] == ["bash", str(self.bin_root / "write_state.sh")]
        ]
        self.assertEqual(len(write_state_calls), 1)
        call = write_state_calls[0]
        self.assertIn("BLOCKED", call)
        # Owner stays smith: expect-owner smith, actor smith, no --set-owner.
        self.assertIn("--expect-owner", call)
        self.assertEqual(call[call.index("--expect-owner") + 1], "smith")
        self.assertIn("--actor", call)
        self.assertEqual(call[call.index("--actor") + 1], "smith")
        self.assertNotIn("--set-owner", call)
        self.assertIn("--increment-blocked", call)
        send_calls = [
            c for c in self.calls if c[:4] == ["openclaw", "gateway", "call", "sessions.send"]
        ]
        self.assertEqual(len(send_calls), 1)
        ledger = read_ledger(self.project_path)
        self.assertTrue(
            any(e.get("outcome") == "niaobe_ack_reaped_blocked" for e in ledger)
        )

    def test_reap_niaobe_ack_dry_run_does_not_block(self) -> None:
        old = time.time() - 4000
        self._seed_state(
            owner="smith",
            active_task="T002",
            task_phase="TASK_HANDOFF",
            task_status="READY",
            waiting_for="niaobe",
            mtime=old,
        )
        with mock.patch.object(worker_runtime.subprocess, "run", side_effect=self._fake_run):
            result = process_project(self.project_path, idle_threshold=1800, dry_run=True)
        self.assertEqual(result.outcome, "would_reap")
        self.assertEqual(result.decision.action, "reap_niaobe_ack")
        self.assertEqual(self.calls, [])

    def test_reap_niaobe_ack_in_lock_idle_recompute_stands_down(self) -> None:
        # Classified as reap, but a FRESH PROJECT_STATE.md (niaobe just started)
        # means idle recomputed under the lock is small -> stand down, no block.
        self._seed_state(
            owner="smith",
            active_task="T002",
            task_phase="TASK_HANDOFF",
            task_status="READY",
            waiting_for="niaobe",
            mtime=time.time(),
        )
        decision = lw.LivenessDecision(
            "reap_niaobe_ack",
            "synthetic",
            role="niaobe",
            task_id="T002",
            phase="TASK_HANDOFF",
            idle_seconds=4000,
        )
        with mock.patch.object(worker_runtime.subprocess, "run", side_effect=self._fake_run):
            result = reap_niaobe_ack(
                self.project_path,
                "demo-project",
                decision,
                idle_threshold=1800,
                now_epoch=time.time(),
            )
        self.assertEqual(result.outcome, "superseded")
        self.assertEqual(self.calls, [])

    def test_reap_niaobe_ack_terminal_under_lock_stands_down(self) -> None:
        old = time.time() - 4000
        self._seed_state(
            owner="smith",
            active_task="T002",
            task_phase="TASK_HANDOFF",
            task_status="READY",
            waiting_for="niaobe",
            mtime=old,
        )
        # Niaobe terminal evidence newer than the handoff appears before the reap.
        self._write_niaobe_result(status="sent", mtime=time.time())
        decision = lw.LivenessDecision(
            "reap_niaobe_ack",
            "synthetic",
            role="niaobe",
            task_id="T002",
            phase="TASK_HANDOFF",
            idle_seconds=4000,
        )
        with mock.patch.object(worker_runtime.subprocess, "run", side_effect=self._fake_run):
            result = reap_niaobe_ack(
                self.project_path,
                "demo-project",
                decision,
                idle_threshold=1800,
                now_epoch=time.time(),
            )
        self.assertEqual(result.outcome, "superseded")
        self.assertEqual(self.calls, [])

    def test_second_pass_after_ack_reap_is_idempotent(self) -> None:
        # After a reap the task_status becomes BLOCKED -> no longer the ack class.
        self._seed_state(
            owner="smith",
            active_task="T002",
            task_phase="TASK_HANDOFF",
            task_status="BLOCKED",
            waiting_for="smith",
        )
        with mock.patch.object(worker_runtime.subprocess, "run", side_effect=self._fake_run):
            result = process_project(self.project_path, idle_threshold=1800)
        self.assertEqual(result.outcome, "skipped")
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
