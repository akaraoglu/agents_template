"""Local Ollama backend for prompt-aware runtime execution."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from openclaw_agents.runtime.dispatcher import ContractValidator


ALLOWED_STATUSES = {"PENDING", "RUNNING", "SUCCESS", "NEEDS_CLARIFICATION", "BLOCKED", "FAILED", "CANCELLED"}
ALLOWED_NEXT_ACTIONS = {
    "RETURN_TO_REQUESTER",
    "RETRY_SAME_AGENT",
    "REPLAN",
    "ESCALATE",
    "WAIT_FOR_EXTERNAL",
    "CLOSE_TASK",
    "CLOSE_PROJECT",
}
VISIBLE_TARGETS = {
    "master",
    "neo",
    "agent_smith",
    "niobe",
    "architect",
    "morpheus",
    "oracle",
    "planner",
    "implementer",
    "tester",
}
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


class OllamaPromptRunner:
    """Turn an execution context into a locally-executed Ollama response envelope."""

    def __init__(
        self,
        *,
        schema_dir: str | Path | None = None,
        ollama_bin: str = "ollama",
        ollama_host: str = "http://127.0.0.1:11434",
        transport: str = "http",
    ) -> None:
        base = Path(__file__).resolve().parents[1]
        self.validator = ContractValidator(schema_dir or base / "schemas")
        self.ollama_bin = ollama_bin
        self.ollama_host = ollama_host if "://" in ollama_host else f"http://{ollama_host}"
        self.transport = transport

    def load_context(self, path: str | Path) -> dict[str, Any]:
        payload = json.loads(Path(path).read_text())
        if not isinstance(payload, dict):
            raise ValueError("execution context must decode to an object")
        return payload

    def determine_model(self, context: dict[str, Any], explicit_model: str | None = None) -> str:
        candidates = [
            explicit_model,
            os.environ.get("OPENCLAW_MODEL_HINT"),
            ((context.get("model") or {}).get("model_hint")),
        ]
        for candidate in candidates:
            if candidate and str(candidate).strip():
                return str(candidate).strip()
        raise ValueError("no Ollama model configured for prompt runner")

    def infer_artifact_type(self, context: dict[str, Any]) -> str:
        expected = ((context.get("task_envelope") or {}).get("expected_output") or {}).get("artifact_type")
        if expected:
            return str(expected)
        agent_primary = ((context.get("agent") or {}).get("primary_artifact"))
        if agent_primary:
            return str(agent_primary)
        return "project_status_report"

    def _target_agent_for_return(self, context: dict[str, Any]) -> str | None:
        packet = context.get("task_envelope") or {}
        return_to = packet.get("return_to")
        if return_to and return_to != "requesting_agent" and return_to in VISIBLE_TARGETS:
            return str(return_to)
        requester = packet.get("from_agent")
        if requester in VISIBLE_TARGETS:
            return str(requester)
        return None

    @staticmethod
    def _compact_record(record: dict[str, Any] | None, keys: list[str]) -> dict[str, Any] | None:
        if not record:
            return None
        return {key: record.get(key) for key in keys if key in record}

    def _legacy_prompt_context(self, context: dict[str, Any]) -> dict[str, Any]:
        packet = context["task_envelope"]
        project_record = self._compact_record(
            context.get("project_record"),
            [
                "project_id",
                "goal",
                "project_status",
                "runtime_status",
                "priority",
                "current_phase",
                "current_owner_agent",
                "workspace_ref",
            ],
        )
        parent_record = self._compact_record(
            context.get("parent_task_record"),
            [
                "task_id",
                "task_type",
                "title",
                "goal",
                "status",
                "from_agent",
                "to_agent",
            ],
        )
        workspace_state = self._compact_record(
            context.get("workspace_state"),
            [
                "workspace_ref",
                "repo_root",
                "branch_or_worktree_id",
                "last_clean_commit_or_checkpoint",
                "is_consistent",
            ],
        )
        child_tasks = []
        for child in context.get("child_tasks") or []:
            child_tasks.append(
                {
                    "task_id": child.get("task_id"),
                    "task_type": child.get("task_type"),
                    "title": child.get("title"),
                    "status": child.get("status"),
                    "to_agent": child.get("to_agent"),
                }
            )
        return {
            "task": {
                "task_id": packet.get("task_id"),
                "task_type": packet.get("task_type"),
                "title": packet.get("title"),
                "goal": packet.get("goal"),
                "priority": packet.get("priority"),
                "from_agent": packet.get("from_agent"),
                "to_agent": packet.get("to_agent"),
                "context": packet.get("context") or {},
                "expected_output": packet.get("expected_output") or {},
            },
            "project": project_record,
            "parent_task": parent_record,
            "workspace": workspace_state,
            "input_artifacts": context.get("input_artifacts") or [],
            "relevant_artifacts": context.get("relevant_artifacts") or context.get("recent_artifacts") or [],
            "child_tasks": child_tasks,
        }

    def build_prompt(self, context: dict[str, Any], *, model: str) -> str:
        packet = context["task_envelope"]
        artifact_type = self.infer_artifact_type(context)
        target_agent = self._target_agent_for_return(context)
        prompt_context = context.get("context_payload")
        if not isinstance(prompt_context, dict):
            prompt_context = self._legacy_prompt_context(context)
        prompt_context_wrapper = {
            "scope": context.get("context_scope"),
            "root": context.get("context_root"),
            "payload": prompt_context,
        }
        target_line = f'Include `next_action.target_agent` set to "{target_agent}".' if target_agent else "Omit `next_action.target_agent` unless you are explicitly routing to another agent."
        return "\n".join(
            [
                f"You are {context['agent']['display_name']} acting within the OpenClaw control plane.",
                f"Use the installed local Ollama model `{model}` to complete the assigned task.",
                "Follow the role instructions below, but the response format rules in this prompt take precedence.",
                "",
                "Role instructions:",
                context["agent"].get("prompt_text") or "",
                "",
                "Response rules:",
                "- Return exactly one JSON object and no markdown fences.",
                "- The JSON must satisfy the OpenClaw response envelope contract.",
                f'- Set `task_id` to "{packet["task_id"]}", `project_id` to "{packet["project_id"]}", `agent` to "{packet["to_agent"]}", and `trace.run_id` to "{packet["metadata"]["run_id"]}".',
                "- Choose `status` from: SUCCESS, NEEDS_CLARIFICATION, BLOCKED, FAILED.",
                f'- Include at least one artifact in `artifacts_out`. The primary artifact type should be "{artifact_type}" and should normally use ref `inline://{packet["task_id"]}-{artifact_type}`.',
                "- Each artifact may include an inline `payload` object. Prefer concise structured payloads over prose blobs.",
                "- `findings` and `risks` must be arrays.",
                f"- If the work is completed, use `next_action.type` = `RETURN_TO_REQUESTER`. {target_line}",
                "- If critical context is missing, use `status` = `NEEDS_CLARIFICATION` or `BLOCKED` instead of inventing facts.",
                "- Never claim code was changed, tests were run, or artifacts exist unless the provided context supports that claim.",
                "",
                "Execution context:",
                json.dumps(prompt_context_wrapper, indent=2, sort_keys=True),
            ]
        )

    @staticmethod
    def _strip_code_fence(payload: str) -> str:
        stripped = payload.strip()
        if not stripped.startswith("```"):
            return stripped
        match = re.search(r"```(?:json|yaml)?\s*(.*?)```", stripped, flags=re.DOTALL)
        return match.group(1).strip() if match else stripped

    @staticmethod
    def _strip_terminal_noise(payload: str) -> str:
        without_ansi = ANSI_ESCAPE_RE.sub("", payload)
        return CONTROL_CHAR_RE.sub("", without_ansi)

    @staticmethod
    def _extract_json_fragment(payload: str) -> str | None:
        start = payload.find("{")
        end = payload.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        return payload[start : end + 1]

    def parse_output(self, payload: str) -> dict[str, Any]:
        cleaned = self._strip_terminal_noise(self._strip_code_fence(payload))
        candidates = [cleaned]
        fragment = self._extract_json_fragment(cleaned)
        if fragment and fragment not in candidates:
            candidates.append(fragment)
        last_error: Exception | None = None
        for candidate in candidates:
            if not candidate.strip():
                continue
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError as exc:
                last_error = exc
            else:
                if isinstance(parsed, dict):
                    return parsed
            try:
                parsed = yaml.safe_load(candidate)
            except Exception as exc:
                last_error = exc
                continue
            if isinstance(parsed, dict):
                return parsed
        raise ValueError(f"Ollama output did not decode to an object: {last_error}")

    @staticmethod
    def _ensure_string_list(value: Any, *, fallback: str | None = None) -> list[str]:
        if value is None:
            return [fallback] if fallback else []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            result: list[str] = []
            for item in value:
                if isinstance(item, str):
                    result.append(item)
                elif item is not None:
                    result.append(json.dumps(item, sort_keys=True))
            if result:
                return result
        return [fallback] if fallback else []

    def normalize_response(self, raw: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        packet = context["task_envelope"]
        status = str(raw.get("status") or "SUCCESS").upper()
        if status not in ALLOWED_STATUSES:
            status = "SUCCESS"
        summary = str(raw.get("summary") or raw.get("message") or f"{packet['to_agent']} completed {packet['task_type']}.").strip()
        artifact_type = self.infer_artifact_type(context)
        artifact_items = raw.get("artifacts_out")
        if not isinstance(artifact_items, list) or not artifact_items:
            artifact_items = [
                {
                    "artifact_type": artifact_type,
                    "ref": f"inline://{packet['task_id']}-{artifact_type}",
                    "payload": {
                        "summary": summary,
                        "task_id": packet["task_id"],
                        "project_id": packet["project_id"],
                        "agent": packet["to_agent"],
                    },
                }
            ]
        normalized_artifacts: list[dict[str, Any] | str] = []
        for index, item in enumerate(artifact_items):
            if isinstance(item, str):
                normalized_artifacts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            item_artifact_type = str(item.get("artifact_type") or artifact_type)
            ref = str(item.get("ref") or f"inline://{packet['task_id']}-{item_artifact_type}-{index + 1}")
            normalized_item = {"artifact_type": item_artifact_type, "ref": ref}
            if "payload" in item:
                normalized_item["payload"] = item["payload"]
            else:
                payload_fields = {key: value for key, value in item.items() if key not in {"artifact_type", "ref"}}
                if payload_fields:
                    normalized_item["payload"] = payload_fields
            normalized_artifacts.append(normalized_item)
        if not normalized_artifacts:
            normalized_artifacts = [
                {
                    "artifact_type": artifact_type,
                    "ref": f"inline://{packet['task_id']}-{artifact_type}",
                    "payload": {"summary": summary},
                }
            ]

        next_action = raw.get("next_action") if isinstance(raw.get("next_action"), dict) else {}
        action_type = str(next_action.get("type") or "RETURN_TO_REQUESTER").upper()
        if action_type not in ALLOWED_NEXT_ACTIONS:
            action_type = "RETURN_TO_REQUESTER"
        normalized_next_action = {
            "type": action_type,
            "reason": str(next_action.get("reason") or summary),
        }
        target_agent = next_action.get("target_agent") or self._target_agent_for_return(context)
        if target_agent in VISIBLE_TARGETS:
            normalized_next_action["target_agent"] = target_agent

        response = {
            "task_id": packet["task_id"],
            "project_id": packet["project_id"],
            "agent": packet["to_agent"],
            "status": status,
            "summary": summary,
            "artifacts_out": normalized_artifacts,
            "findings": self._ensure_string_list(raw.get("findings"), fallback=summary),
            "next_action": normalized_next_action,
            "risks": self._ensure_string_list(raw.get("risks")),
            "trace": {"run_id": packet["metadata"]["run_id"]},
        }
        self.validator.validate("response_envelope", response)
        return response

    def _run_ollama_http(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: int = 1800,
        keepalive: str = "5m",
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "keep_alive": keepalive,
        }
        request = urllib.request.Request(
            f"{self.ollama_host.rstrip('/')}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Ollama HTTP request failed: {exc}") from exc
        if not isinstance(raw, dict) or "response" not in raw:
            raise ValueError("Ollama HTTP API returned an unexpected payload")
        return self.parse_output(str(raw["response"]))

    def _run_ollama_cli(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: int = 1800,
        keepalive: str = "5m",
    ) -> dict[str, Any]:
        command = [self.ollama_bin, "run", model, prompt, "--format", "json", "--hidethinking"]
        if keepalive:
            command.extend(["--keepalive", keepalive])
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or f"Ollama returned {completed.returncode}")
        return self.parse_output(completed.stdout)

    def run_ollama(
        self,
        *,
        model: str,
        prompt: str,
        timeout_seconds: int = 1800,
        keepalive: str = "5m",
    ) -> dict[str, Any]:
        if self.transport == "http":
            return self._run_ollama_http(
                model=model,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
                keepalive=keepalive,
            )
        if self.transport == "cli":
            return self._run_ollama_cli(
                model=model,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
                keepalive=keepalive,
            )
        raise ValueError(f"unsupported Ollama transport {self.transport}")

    def execute(
        self,
        *,
        context_path: str | Path,
        response_path: str | Path,
        explicit_model: str | None = None,
        timeout_seconds: int = 1800,
        keepalive: str = "5m",
    ) -> dict[str, Any]:
        context = self.load_context(context_path)
        model = self.determine_model(context, explicit_model)
        prompt = self.build_prompt(context, model=model)
        raw = self.run_ollama(model=model, prompt=prompt, timeout_seconds=timeout_seconds, keepalive=keepalive)
        response = self.normalize_response(raw, context)
        response_file = Path(response_path)
        response_file.parent.mkdir(parents=True, exist_ok=True)
        response_file.write_text(yaml.safe_dump(response, sort_keys=False))
        return response


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a prompt-aware OpenClaw task through local Ollama")
    parser.add_argument("--context", default=os.environ.get("OPENCLAW_EXECUTION_CONTEXT"))
    parser.add_argument("--response-file", default=os.environ.get("OPENCLAW_RESPONSE_FILE"))
    parser.add_argument("--model", default=os.environ.get("OPENCLAW_MODEL_HINT"))
    parser.add_argument("--ollama-bin", default=os.environ.get("OPENCLAW_OLLAMA_BIN", "ollama"))
    parser.add_argument("--ollama-host", default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    parser.add_argument("--transport", choices=["http", "cli"], default=os.environ.get("OPENCLAW_OLLAMA_TRANSPORT", "http"))
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--keepalive", default="5m")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.context:
        raise SystemExit("--context or OPENCLAW_EXECUTION_CONTEXT is required")
    if not args.response_file:
        raise SystemExit("--response-file or OPENCLAW_RESPONSE_FILE is required")
    runner = OllamaPromptRunner(
        ollama_bin=args.ollama_bin,
        ollama_host=args.ollama_host,
        transport=args.transport,
    )
    runner.execute(
        context_path=args.context,
        response_path=args.response_file,
        explicit_model=args.model,
        timeout_seconds=args.timeout_seconds,
        keepalive=args.keepalive,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
