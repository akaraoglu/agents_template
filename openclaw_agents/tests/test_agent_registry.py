import unittest

from openclaw_agents.agents import AgentRegistryService


class AgentRegistryTest(unittest.TestCase):
    def test_registry_exposes_runtime_and_memory_profiles(self) -> None:
        registry = AgentRegistryService()

        neo = registry.get("neo")
        self.assertIsNotNone(neo)
        assert neo is not None
        self.assertEqual(neo.runtime_mode, "free_conversational")
        self.assertIn("dm", neo.allowed_surfaces)
        self.assertIn("project_registry", neo.allowed_services)

        niaobe = registry.get("niaobe")
        self.assertIsNotNone(niaobe)
        assert niaobe is not None
        self.assertEqual(niaobe.runtime_mode, "bounded_execution")
        self.assertEqual(niaobe.memory_profile["conversational_memory"], "none")
        self.assertIn("agent_smith", niaobe.escalation_targets)
        self.assertIn("execution_state", niaobe.allowed_services)

        morpheus = registry.get("morpheus")
        self.assertIsNotNone(morpheus)
        assert morpheus is not None
        self.assertEqual(morpheus.zulip_visibility, "internal_only")
        self.assertIn("control", morpheus.allowed_surfaces)

        implementer = registry.get("implementer")
        self.assertIsNotNone(implementer)
        assert implementer is not None
        self.assertIn("command_runner", implementer.allowed_services)
        self.assertEqual(implementer.memory_profile["execution_memory"], "read_write")


if __name__ == "__main__":
    unittest.main()
