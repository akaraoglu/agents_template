from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1] / "AgenticTeam" / "scripts"
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from canaries.phase_canaries import CANARY_RUNNERS, terminal_result_file_for_worker_state


class PhaseCanaryTests(unittest.TestCase):
    def test_terminal_result_file_for_worker_state_uses_state_file_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            state_file = Path(tmp_dir) / "run" / "state.json"
            expected = state_file.parent / "result.json"
            self.assertEqual(
                terminal_result_file_for_worker_state({"state_file": str(state_file)}),
                expected,
            )

    def test_terminal_result_file_for_worker_state_handles_missing_state_file(self) -> None:
        self.assertIsNone(terminal_result_file_for_worker_state({}))
        self.assertIsNone(terminal_result_file_for_worker_state(None))

    def test_architect_live_session_protocol_canary_is_registered(self) -> None:
        self.assertIn("architect_live_session_protocol", CANARY_RUNNERS)
        self.assertNotEqual(
            CANARY_RUNNERS["architect_live_session_protocol"],
            CANARY_RUNNERS["architect_worker_runtime"],
        )


if __name__ == "__main__":
    unittest.main()
