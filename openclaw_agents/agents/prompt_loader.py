"""Prompt loading helpers for visible runtime agents."""

from __future__ import annotations

from pathlib import Path


_PROMPT_FILES = {
    "neo": "neo.md",
    "agent_smith": "agent_smith.md",
    "niaobe": "niaobe.md",
}


class PromptLoader:
    def __init__(self, prompts_dir: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parents[1]
        self.prompts_dir = prompts_dir or (base_dir / "prompts")

    def load(self, agent_id: str) -> str:
        filename = _PROMPT_FILES.get(agent_id, f"{agent_id}.md")
        path = self.prompts_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Prompt file not found for agent '{agent_id}': {path}")
        return path.read_text(encoding="utf-8").strip()
