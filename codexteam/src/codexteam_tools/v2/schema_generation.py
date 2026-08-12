from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .models import TOP_LEVEL_MODELS

SCHEMA_DIRECTORY = Path(__file__).resolve().parents[3] / "schemas" / "v2"
SEMANTIC_COMMENT = (
    "Structural validation is necessary but semantic and cross-record validation MUST use "
    "codexteam_tools.v2.models.validate_wire plus the model named in x-codexteam-semantic-model."
)


def schema_filename(model: type) -> str:
    name = model.__name__
    return "".join(("-" + char.lower()) if char.isupper() else char for char in name).lstrip("-") + ".json"


def rendered_schemas() -> dict[str, str]:
    rendered: dict[str, str] = {}
    for model in TOP_LEVEL_MODELS:
        schema = model.model_json_schema(ref_template="#/$defs/{model}", mode="validation")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$comment"] = SEMANTIC_COMMENT
        schema["x-codexteam-semantic-model"] = model.__name__
        schema["x-codexteam-semantic-module"] = "codexteam_tools.v2.models"
        schema["x-codexteam-contract-version"] = "2.0"
        rendered[schema_filename(model)] = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    return rendered


def write_schemas(directory: Path = SCHEMA_DIRECTORY) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    expected = rendered_schemas()
    for path in directory.glob("*.json"):
        if path.name not in expected:
            path.unlink()
    for filename, content in expected.items():
        (directory / filename).write_text(content, encoding="utf-8")


def check_schemas(directory: Path = SCHEMA_DIRECTORY) -> list[str]:
    expected = rendered_schemas()
    actual_names = {path.name for path in directory.glob("*.json")} if directory.is_dir() else set()
    errors = [f"unexpected schema: {name}" for name in sorted(actual_names - expected.keys())]
    for filename, content in sorted(expected.items()):
        path = directory / filename
        if not path.is_file():
            errors.append(f"missing schema: {filename}")
        elif path.read_text(encoding="utf-8") != content:
            errors.append(f"stale schema: {filename}")
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic CodexTeam v2 JSON schemas.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="fail if committed schemas are stale")
    action.add_argument("--write", action="store_true", help="write the current schemas")
    args = parser.parse_args(argv)
    if args.write:
        write_schemas()
        return 0
    errors = check_schemas()
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
