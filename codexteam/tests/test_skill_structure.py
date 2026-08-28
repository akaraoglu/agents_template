from __future__ import annotations

import re
from pathlib import Path

from codexteam_tools import spawn
from codexteam_tools.agent_specs import guidance_paths, load_agent_spec
from codexteam_tools.project_guidance import PROJECT_SKILLS, expected_project_guidance
from codexteam_tools.roles import load_all_role_policies


CODEXTEAM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CODEXTEAM_ROOT.parent
ROOT_SKILLS = REPO_ROOT / ".agents" / "skills"
REQUIRED_SECTIONS = (
    "## Purpose", "## Inputs", "## Workflow", "## Expected Output",
    "## Validation", "## Cautions", "## Related Guidance",
)


def test_root_skills_have_frontmatter_matching_names_sections_and_valid_references():
    paths = sorted(ROOT_SKILLS.glob("*/SKILL.md"))
    assert paths
    for path in paths:
        content = path.read_text(encoding="utf-8")
        match = re.match(r"---\n(?P<header>.*?)\n---\n", content, re.DOTALL)
        assert match, f"missing frontmatter: {path}"
        fields = {}
        for line in match.group("header").splitlines():
            key, separator, value = line.partition(":")
            assert separator and key not in fields, f"invalid frontmatter: {path}"
            fields[key] = value.strip()
        assert set(fields) == {"name", "description"}
        assert fields["name"] == path.parent.name
        assert fields["description"]
        for section in REQUIRED_SECTIONS:
            assert section in content, f"missing {section!r}: {path}"
        references = re.findall(r"`(\.agents/[^`]+)`", content)
        assert references, f"missing references: {path}"
        for reference in references:
            assert (REPO_ROOT / reference).is_file(), f"missing reference {reference}: {path}"


def test_role_skill_references_exist_and_resolve_in_declared_order():
    for policy in load_all_role_policies():
        paths = spawn._skill_files(policy, [])
        assert tuple(path.name for path in paths) == policy.skill_files
        assert all(path.is_file() and not path.is_symlink() for path in paths)


def test_project_skill_guidance_is_a_byte_projection_of_toolkit_sources():
    projected = expected_project_guidance()
    for name in PROJECT_SKILLS:
        source = CODEXTEAM_ROOT / ".agents" / "skills" / name
        assert projected[f".codexteam/skills/{name}"].encode("utf-8") == source.read_bytes()


def test_agent_spec_guidance_is_contained_and_preserves_declared_order():
    guidance_root = (CODEXTEAM_ROOT / "agent_specs" / "guidance").resolve()
    for source in sorted((CODEXTEAM_ROOT / "agent_specs").glob("*.toml")):
        spec = load_agent_spec(source.stem)
        paths = guidance_paths(spec)
        assert tuple(path.name for path in paths) == spec.guidance_files
        for path in paths:
            assert path.is_file() and not path.is_symlink()
            path.relative_to(guidance_root)


def test_all_role_guidance_bundles_preserve_base_then_specialization_order():
    for policy in load_all_role_policies():
        base = spawn._skill_files(policy, [])
        assert tuple(path.name for path in base) == policy.skill_files
        for source in sorted((CODEXTEAM_ROOT / "agent_specs").glob("*.toml")):
            spec = load_agent_spec(source.stem)
            if spec.base_role != policy.role:
                continue
            combined = (*base, *guidance_paths(spec))
            assert combined[:len(base)] == base
            assert tuple(path.name for path in combined[len(base):]) == spec.guidance_files
