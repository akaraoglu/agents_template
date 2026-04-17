import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from openclaw_agents.communication.zulip_gateway import ZulipGateway


class PolicyEngineTest(unittest.TestCase):
    def test_profiles_enforce_expected_runtime_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gateway = ZulipGateway(base_dir=Path(temp_dir) / "runtime")
            request = SimpleNamespace(conversation_surface="dm")

            neo = gateway.agent_registry.get("neo")
            smith = gateway.agent_registry.get("agent_smith")
            niaobe = gateway.agent_registry.get("niaobe")
            morpheus = gateway.agent_registry.get("morpheus")
            implementer = gateway.agent_registry.get("implementer")
            tester = gateway.agent_registry.get("tester")
            assert neo is not None and smith is not None and niaobe is not None and morpheus is not None and implementer is not None and tester is not None

            neo_command = gateway.policy_service.evaluate_tool_call(
                profile=neo,
                tool_name="run_workspace_command",
                arguments={"command": "echo hello"},
                surface="dm",
            )
            self.assertEqual(neo_command.disposition, "allow")

            smith_direct = gateway.policy_service.evaluate_tool_call(
                profile=smith,
                tool_name="update_project_state",
                arguments={"summary": "new"},
                surface="dm",
            )
            self.assertEqual(smith_direct.disposition, "deny")

            smith_mutation = gateway.policy_service.evaluate_action_intent(
                profile=smith,
                intent_kind="project_mutation_request",
                request=request,
                payload={"action": "update_project"},
            )
            self.assertTrue(smith_mutation.requires_confirmation)

            niaobe_mutation = gateway.policy_service.evaluate_action(
                profile=niaobe,
                action_kind="direct_project_mutation",
                payload={},
                surface="project_topic",
            )
            self.assertEqual(niaobe_mutation.disposition, "deny")

            niaobe_escalation = gateway.policy_service.evaluate_action_intent(
                profile=niaobe,
                intent_kind="escalate_to_agent_smith",
                request=SimpleNamespace(conversation_surface="project_topic"),
                payload={"blocker": "Missing credentials"},
            )
            self.assertEqual(niaobe_escalation.disposition, "escalate")
            self.assertEqual(niaobe_escalation.escalation_target, "agent_smith")

            morpheus_write = gateway.policy_service.evaluate_action(
                profile=morpheus,
                action_kind="workspace_write",
                payload={},
                surface="control",
            )
            self.assertEqual(morpheus_write.disposition, "deny")

            implementer_command = gateway.policy_service.evaluate_action(
                profile=implementer,
                action_kind="workspace_command",
                payload={},
                surface="control",
            )
            self.assertEqual(implementer_command.disposition, "allow")

            tester_verification = gateway.policy_service.evaluate_action(
                profile=tester,
                action_kind="verification_report",
                payload={},
                surface="control",
            )
            self.assertEqual(tester_verification.disposition, "allow")
