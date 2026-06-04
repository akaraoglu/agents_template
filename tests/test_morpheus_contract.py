from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTIC_ROOT = REPO_ROOT / "AgenticTeam"
MORPHEUS_DOCS = (
    AGENTIC_ROOT / "agents" / "morpheus" / "AGENT.md",
    AGENTIC_ROOT / "agents" / "morpheus" / "AGENTS.md",
    AGENTIC_ROOT / "agents" / "morpheus" / "SKILLS.md",
    AGENTIC_ROOT / "agents" / "morpheus" / "TOOLS.md",
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def morpheus_agent_config() -> dict:
    config = load_json(AGENTIC_ROOT / "config" / "openclaw.json")
    for agent in config["agents"]["list"]:
        if agent.get("id") == "morpheus":
            return agent
    raise AssertionError("morpheus agent config not found")


class MorpheusContractTests(unittest.TestCase):
    def test_morpheus_policy_denies_outbound_session_tools(self) -> None:
        tools = morpheus_agent_config()["tools"]
        denied = set(tools["deny"])
        allowed = set(tools["allow"])
        outbound_tools = {
            "sessions_send",
            "sessions_spawn",
            "sessions_list",
            "sessions_history",
            "sessions_yield",
            "subagents",
        }

        self.assertEqual(allowed, {"exec", "read", "write"})
        self.assertTrue(outbound_tools.issubset(denied))
        self.assertTrue(outbound_tools.isdisjoint(allowed))

    def test_live_sync_covers_openclaw_policy_and_morpheus_docs(self) -> None:
        manifest = load_json(AGENTIC_ROOT / "config" / "live_openclaw_sync_manifest.json")

        self.assertEqual(manifest["managed_config"]["openclaw"]["source"], "config/openclaw.json")
        self.assertEqual(manifest["managed_config"]["openclaw"]["strategy"], "deep-merge")
        self.assertIn("morpheus", manifest["agents"])
        self.assertIn("AGENTS.md", manifest["agents"]["morpheus"]["workspace_files"])
        self.assertIn("TOOLS.md", manifest["agents"]["morpheus"]["workspace_files"])
        self.assertIn("AGENT.md", manifest["agents"]["morpheus"]["agent_dir_files"])
        self.assertIn("SKILLS.md", manifest["agents"]["morpheus"]["agent_dir_files"])

    def test_morpheus_docs_describe_allowed_actions_not_generic_raw_tools(self) -> None:
        docs = {path.name: path.read_text(encoding="utf-8") for path in MORPHEUS_DOCS}
        combined = "\n".join(docs.values())

        self.assertNotIn("standard tools", combined)
        self.assertNotIn("read, write, exec", combined)
        self.assertNotIn("exec:", combined)
        self.assertIn("allowed actions", docs["TOOLS.md"])
        self.assertIn("write_draft_file", combined)
        self.assertIn("write_manifest", combined)
        self.assertIn("python_claw", combined)
        self.assertIn("morpheus_report", combined)
        self.assertIn("morpheus_block", combined)
        self.assertIn("Morpheus must not call", docs["AGENTS.md"])
        self.assertIn("outbound session routing tools", docs["AGENTS.md"])

    def test_morpheus_docs_preserve_runtime_owned_validation_invariants(self) -> None:
        combined = "\n".join(path.read_text(encoding="utf-8") for path in MORPHEUS_DOCS)
        normalized = " ".join(combined.split())

        for token in (
            "DRAFT_WRITE_ROOT",
            "MANIFEST_WRITE_FILE",
            "REPORT_COMMAND",
            "BLOCK_COMMAND",
            "RUN_DIR",
            "project_exec",
        ):
            self.assertIn(token, combined)
        self.assertIn("never pass", combined.lower())
        self.assertIn("DRAFT_WRITE_ROOT", combined)
        self.assertIn("Its output is never DONE evidence", normalized)
        self.assertIn("final acceptance still requires", normalized)


if __name__ == "__main__":
    unittest.main()
