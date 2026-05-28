from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "AgenticTeam" / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import canaries.common as common
from canaries.common import classify_failure, first_failed_invariant, parse_state_field, token_from_paths
from canaries.common import build_delivery_evidence, detect_empty_stop, extract_inbound_project_ids


class CanaryCommonTests(unittest.TestCase):
    def test_parse_state_field_reads_bullet_style_fields(self) -> None:
        text = "- **owner**: smith\n- **phase**: PLANNING\n"
        self.assertEqual(parse_state_field(text, "owner"), "smith")
        self.assertEqual(parse_state_field(text, "phase"), "PLANNING")

    def test_first_failed_invariant_returns_first_failure(self) -> None:
        items = [
            {"name": "a", "passed": True, "detail": "ok"},
            {"name": "b", "passed": False, "detail": "broken"},
            {"name": "c", "passed": False, "detail": "later"},
        ]
        self.assertEqual(first_failed_invariant(items)["name"], "b")

    def test_token_from_paths_changes_with_file_presence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.txt"
            missing = token_from_paths([path])
            path.write_text("hello\n", encoding="utf-8")
            present = token_from_paths([path])
            self.assertNotEqual(missing, present)

    def test_classify_failure_prefers_session_staleness(self) -> None:
        self.assertEqual(
            classify_failure(
                "management/PLAN.md is missing",
                sync_drift="yes",
                session_freshness_value="stale",
                latest_worker_state=None,
                session_detail=None,
                delivery_evidence=None,
            ),
            "session_staleness",
        )

    def test_classify_failure_detects_empty_model_stop(self) -> None:
        self.assertEqual(
            classify_failure(
                "Run stalled before terminal completion.",
                sync_drift="no",
                session_freshness_value="fresh",
                latest_worker_state=None,
                session_detail={"raw_text": '"content":[],"stopReason":"stop"', "empty_stop": True},
                delivery_evidence=None,
            ),
            "model_empty_or_malformed",
        )

    def test_classify_failure_prefers_session_contamination(self) -> None:
        self.assertEqual(
            classify_failure(
                "README.md is missing",
                sync_drift="no",
                session_freshness_value="fresh",
                latest_worker_state=None,
                session_detail={
                    "raw_text": "",
                    "empty_stop": True,
                    "contaminated": True,
                    "unexpected_project_ids_seen": ["canary-other-project"],
                },
                delivery_evidence={"envelope_sent": "yes", "target_session_responded": "yes"},
            ),
            "session_contamination",
        )

    def test_extract_inbound_project_ids_reads_only_user_messages(self) -> None:
        raw_lines = [
            '{"type":"message","message":{"role":"assistant","content":[{"type":"text","text":"{\\"project_id\\":\\"assistant-project\\"}"}]}}',
            '{"type":"message","message":{"role":"user","content":[{"type":"text","text":"{\\"project_id\\":\\"canary-alpha\\"}"}]}}',
            '{"type":"message","message":{"role":"user","content":[{"type":"text","text":"{\\"project_id\\":\\"canary-beta\\"}"}]}}',
        ]
        self.assertEqual(extract_inbound_project_ids(raw_lines), ["canary-alpha", "canary-beta"])

    def test_detect_empty_stop_uses_last_assistant_turn(self) -> None:
        raw_lines = [
            '{"type":"message","message":{"role":"assistant","content":[],"stopReason":"stop"}}',
            '{"type":"message","message":{"role":"assistant","content":[{"type":"text","text":"done"}],"stopReason":"stop"}}',
        ]
        self.assertFalse(detect_empty_stop(raw_lines))

    def test_build_delivery_evidence_includes_unexpected_project_ids(self) -> None:
        evidence = build_delivery_evidence(
            "SEND_READY",
            {
                "line_count_delta": 4,
                "started": True,
                "responded": True,
                "stopped": True,
                "empty_stop": False,
                "contaminated": True,
                "delta_envelope_project_ids": ["canary-a", "canary-b"],
                "unexpected_project_ids_seen": ["canary-b"],
            },
        )
        self.assertEqual(evidence["contaminated"], "yes")
        self.assertEqual(evidence["unexpected_project_ids_seen"], ["canary-b"])

    def test_rotate_main_session_archives_registry_and_keeps_transcripts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sessions_dir = root / "agents" / "morpheus" / "sessions"
            sessions_dir.mkdir(parents=True)
            session_file = sessions_dir / "session-1.jsonl"
            trajectory_file = sessions_dir / "session-1.trajectory.jsonl"
            session_file.write_text('{"type":"message"}\n', encoding="utf-8")
            trajectory_file.write_text('{"type":"trace"}\n', encoding="utf-8")
            sessions_json = sessions_dir / "sessions.json"
            sessions_json.write_text(
                '{"agent:morpheus:main":{"sessionId":"session-1","sessionFile":"'
                + str(session_file)
                + '","status":"done","sessionStartedAt":1,"updatedAt":2}}\n',
                encoding="utf-8",
            )
            original_root = common.OPENCLAW_ROOT
            common.OPENCLAW_ROOT = root
            try:
                result = common.rotate_main_session("morpheus", reason="canary-test")
            finally:
                common.OPENCLAW_ROOT = original_root

            self.assertTrue(result["rotated"])
            updated = common.load_json(sessions_json)
            self.assertIn("agent:morpheus:main", updated)
            self.assertNotEqual(updated["agent:morpheus:main"]["sessionId"], "session-1")
            self.assertEqual(updated["agent:morpheus:main"]["status"], "done")
            self.assertTrue(Path(updated["agent:morpheus:main"]["sessionFile"]).exists())
            self.assertTrue(session_file.exists())
            self.assertTrue(trajectory_file.exists())
            archive_dir = Path(result["archive_dir"])
            self.assertTrue((archive_dir / "sessions.json").exists())
            self.assertTrue((archive_dir / "session-1.jsonl").exists())
            self.assertTrue((archive_dir / "session-1.trajectory.jsonl").exists())
            self.assertTrue((archive_dir / "rotation.json").exists())


if __name__ == "__main__":
    unittest.main()
