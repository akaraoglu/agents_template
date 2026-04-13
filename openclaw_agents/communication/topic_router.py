"""Topic routing helpers for the Zulip gateway."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class RouteContext:
    stream_key: str | None
    stream_name: str
    topic_name: str
    topic_key: str | None
    project_id: str | None
    task_id: str | None
    matched: bool


class TopicRouter:
    """Resolve configured Zulip topics into project and task routing context."""

    _TASK_TOPIC_MAP = {
        "FRAME_PROJECT": ("projects", "project_intake"),
        "CLARIFY_GOAL": ("projects", "project_main"),
        "ORCHESTRATE_PROJECT": ("projects", "project_main"),
        "CLOSE_PROJECT": ("projects", "project_main"),
        "DESIGN_ARCHITECTURE": ("projects", "project_design"),
        "REQUEST_ARCHITECTURE_CLARIFICATION": ("projects", "project_design"),
        "ORCHESTRATE_SOFTWARE": ("software", "software_main"),
        "PLAN_SOFTWARE_TASK": ("software", "software_task"),
        "IMPLEMENT_SOFTWARE_TASK": ("software", "software_task"),
        "TEST_SOFTWARE_TASK": ("software", "software_task"),
        "VERIFY_PROJECT": ("verification", "verification_task"),
        "RESOLVE_ESCALATION": ("escalations", "escalation_task"),
        "APPROVE_PRIORITY": ("escalations", "escalation_task"),
    }

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.streams = config.get("streams", {})
        self.topics = config.get("topics", {})
        self._stream_name_to_key = {name: key for key, name in self.streams.items()}
        self._compiled_patterns = self._compile_patterns()

    @classmethod
    def from_file(cls, path: str | Path) -> "TopicRouter":
        config = yaml.safe_load(Path(path).read_text())
        return cls(config)

    def _compile_patterns(self) -> list[tuple[str, re.Pattern[str]]]:
        compiled: list[tuple[str, re.Pattern[str], int, int]] = []
        for topic_key, template in self.topics.items():
            pattern_text = re.escape(template)
            pattern_text = pattern_text.replace(r"\{project_id\}", r"(?P<project_id>[^/]+)")
            pattern_text = pattern_text.replace(r"\{task_id\}", r"(?P<task_id>[^/]+)")
            pattern = re.compile(rf"^{pattern_text}$")
            compiled.append(
                (
                    topic_key,
                    pattern,
                    template.count("{"),
                    len(template),
                )
            )
        compiled.sort(key=lambda item: (-item[2], -item[3], item[0]))
        return [(topic_key, pattern) for topic_key, pattern, _, _ in compiled]

    def render(self, topic_key: str, **kwargs: str) -> str:
        template = self.topics[topic_key]
        return template.format(**kwargs)

    def resolve(self, stream_name: str, topic_name: str) -> RouteContext:
        stream_key = self._stream_name_to_key.get(stream_name)
        for topic_key, pattern in self._compiled_patterns:
            match = pattern.match(topic_name)
            if match:
                return RouteContext(
                    stream_key=stream_key,
                    stream_name=stream_name,
                    topic_name=topic_name,
                    topic_key=topic_key,
                    project_id=match.groupdict().get("project_id"),
                    task_id=match.groupdict().get("task_id"),
                    matched=True,
                )
        return RouteContext(
            stream_key=stream_key,
            stream_name=stream_name,
            topic_name=topic_name,
            topic_key=None,
            project_id=None,
            task_id=None,
            matched=False,
        )

    def reply_address_for_task(self, project_id: str, task_id: str, task_type: str) -> tuple[str, str]:
        stream_key, topic_key = self._TASK_TOPIC_MAP.get(task_type, ("projects", "project_main"))
        stream_name = self.streams[stream_key]
        topic_name = self.render(topic_key, project_id=project_id, task_id=task_id)
        return stream_name, topic_name

    def control_event_topic(self, project_id: str) -> tuple[str, str]:
        stream_name = self.streams["projects"]
        template = self.config.get("control_event_mirroring", {}).get("topic", "project/{project_id}/decisions")
        return stream_name, template.format(project_id=project_id)
