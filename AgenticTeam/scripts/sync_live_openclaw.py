#!/usr/bin/env python3
"""Sync AgenticTeam canonical files into the live OpenClaw control surface."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


WORKSPACE_REFERENCE_RE = re.compile(r"\*\*([A-Z_]+\.md)\*\*:")
SCRIPT_REFERENCE_RE = re.compile(r"/home/alik/workspace/clawspace/bin/[A-Za-z0-9_.-]+\.sh")

DOC_FILES = ("AGENT.md", "AGENTS.md", "SKILLS.md", "TOOLS.md")
FORBIDDEN_DOC_TOKENS = (
    "read_file",
    "write_file",
    "timeoutSeconds",
    "full absolute path",
    "Folder: /home/alik/workspace/clawspace/projects/active/",
    "Project folder: /home/alik/workspace/clawspace/projects/active/",
    "/home/alik/workspace/clawspace/projects/active/<",
)


@dataclass
class Action:
    kind: str
    destination: Path
    detail: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Write changes to live files")
    parser.add_argument("--agent", action="append", dest="agents", default=[], help="Sync only one agent (repeatable)")
    parser.add_argument("--agents-only", action="store_true", help="Sync agent files only")
    parser.add_argument("--config-only", action="store_true", help="Sync config files only")
    parser.add_argument("--skip-compat-check", action="store_true", help="Skip canonical prompt/tool compatibility validation")
    return parser.parse_args()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_bytes_atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def ensure_presync_backup(path: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.presync.{timestamp}")
    write_bytes_atomic(backup, path.read_bytes())
    return backup


def deep_merge(live: object, overlay: object) -> object:
    if isinstance(live, dict) and isinstance(overlay, dict):
        merged = dict(live)
        for key, value in overlay.items():
            if key in merged:
                merged[key] = deep_merge(merged[key], value)
            else:
                merged[key] = value
        return merged
    return overlay


def json_bytes(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=False) + "\n").encode("utf-8")


def relative_repo_path(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def sync_file(actions: list[Action], source: Path, destination: Path, *, apply: bool, mode: int | None = None) -> None:
    content = source.read_bytes()
    if destination.exists() and destination.read_bytes() == content:
        actions.append(Action("unchanged", destination, f"matches {source}"))
        return
    action_kind = "update" if destination.exists() else "create"
    actions.append(Action(action_kind, destination, f"from {source}"))
    if apply:
        write_bytes_atomic(destination, content)
        if mode is not None:
            destination.chmod(mode)


def validate_agent_dir_targets(agent: str, files: Iterable[str], manifest: dict) -> None:
    allowed = set(manifest["agent_dir_managed_files"])
    requested = set(files)
    if not requested.issubset(allowed):
        invalid = ", ".join(sorted(requested - allowed))
        raise RuntimeError(f"{agent}: requested unmanaged agentDir files: {invalid}")


def validate_workspace_references(agent: str, agent_md: Path, workspace_files: Iterable[str]) -> None:
    referenced = set(WORKSPACE_REFERENCE_RE.findall(agent_md.read_text(encoding="utf-8")))
    declared = set(workspace_files)
    missing = sorted(name for name in referenced if name not in declared)
    if missing:
        raise RuntimeError(f"{agent}: AGENT.md references undeployed workspace files: {', '.join(missing)}")


def load_agent_docs(repo_root: Path, agent: str) -> dict[str, str]:
    agent_root = repo_root / "agents" / agent
    docs: dict[str, str] = {}
    for name in DOC_FILES:
        path = agent_root / name
        if path.exists():
            docs[name] = path.read_text(encoding="utf-8")
    return docs


def extract_scripts(text: str) -> set[str]:
    return set(SCRIPT_REFERENCE_RE.findall(text))


def managed_helper_destinations(repo_root: Path, manifest: dict) -> dict[str, Path]:
    live_bin_root = Path(manifest["paths"]["live_bin_root"])
    destinations: dict[str, Path] = {}
    for agent, names in manifest.get("helper_scripts", {}).items():
        for name in names:
            source = repo_root / "scripts" / name
            if not source.exists():
                raise RuntimeError(f"{agent}: missing managed helper source: {source}")
            destinations[str(live_bin_root / name)] = source
    return destinations


def validate_prompt_contracts(repo_root: Path, manifest: dict) -> None:
    approvals = load_json(repo_root / "config" / "exec-approvals.json")
    baseline_agents = approvals.get("agents", {})
    configured_agents = manifest["agents"]
    managed_helpers = managed_helper_destinations(repo_root, manifest)

    for agent in configured_agents:
        docs = load_agent_docs(repo_root, agent)
        workspace_text = "\n".join(docs.get(name, "") for name in ("AGENTS.md", "TOOLS.md"))
        agent_dir_text = "\n".join(docs.get(name, "") for name in ("AGENT.md", "SKILLS.md"))
        workspace_scripts = extract_scripts(workspace_text)
        agent_dir_scripts = extract_scripts(agent_dir_text)
        if workspace_scripts != agent_dir_scripts:
            missing_in_workspace = sorted(agent_dir_scripts - workspace_scripts)
            missing_in_agent_dir = sorted(workspace_scripts - agent_dir_scripts)
            parts = []
            if missing_in_workspace:
                parts.append(f"missing from AGENTS/TOOLS: {', '.join(missing_in_workspace)}")
            if missing_in_agent_dir:
                parts.append(f"missing from AGENT/SKILLS: {', '.join(missing_in_agent_dir)}")
            raise RuntimeError(f"{agent}: canonical prompt surfaces drifted; {'; '.join(parts)}")

        all_scripts = workspace_scripts | agent_dir_scripts
        for script in sorted(all_scripts):
            if Path(script).exists():
                continue
            if script in managed_helpers:
                continue
            raise RuntimeError(f"{agent}: referenced helper does not exist: {script}")

        baseline = baseline_agents.get(agent, {})
        if baseline.get("security") == "allowlist":
            allowed = set(baseline.get("allow_patterns", []))
            missing = sorted(script for script in all_scripts if script not in allowed)
            if missing:
                raise RuntimeError(f"{agent}: referenced helper not allowlisted: {', '.join(missing)}")

        for doc_name, text in docs.items():
            for token in FORBIDDEN_DOC_TOKENS:
                if token in text:
                    raise RuntimeError(f"{agent}: {doc_name} still contains legacy prompt token: {token}")


def sync_agent_files(repo_root: Path, manifest: dict, *, selected_agents: list[str], apply: bool) -> list[Action]:
    actions: list[Action] = []
    workspace_root = Path(manifest["paths"]["workspace_root"])
    openclaw_root = Path(manifest["paths"]["openclaw_root"])
    configured_agents = manifest["agents"]
    agent_names = selected_agents or list(configured_agents.keys())

    for agent in agent_names:
        if agent not in configured_agents:
            raise RuntimeError(f"unknown agent in manifest: {agent}")
        agent_conf = configured_agents[agent]
        repo_agent_dir = repo_root / "agents" / agent
        workspace_files = agent_conf["workspace_files"]
        agent_dir_files = agent_conf["agent_dir_files"]

        validate_agent_dir_targets(agent, agent_dir_files, manifest)
        validate_workspace_references(agent, repo_agent_dir / "AGENT.md", workspace_files)

        for name in workspace_files:
            source = repo_agent_dir / name
            if not source.exists():
                raise RuntimeError(f"{agent}: missing workspace source file {source}")
            destination = workspace_root / agent / name
            sync_file(actions, source, destination, apply=apply)

        agent_dir = openclaw_root / "agents" / agent / "agent"
        for name in agent_dir_files:
            source = repo_agent_dir / name
            if not source.exists():
                raise RuntimeError(f"{agent}: missing agentDir source file {source}")
            destination = agent_dir / name
            sync_file(actions, source, destination, apply=apply)

    return actions


def sync_helper_scripts(repo_root: Path, manifest: dict, *, selected_agents: list[str], apply: bool) -> list[Action]:
    actions: list[Action] = []
    configured_agents = manifest["agents"]
    helper_scripts = manifest.get("helper_scripts", {})
    live_bin_root = Path(manifest["paths"]["live_bin_root"])
    agent_names = selected_agents or list(configured_agents.keys())
    synced_destinations: set[Path] = set()

    for agent in agent_names:
        for name in helper_scripts.get(agent, []):
            source = repo_root / "scripts" / name
            destination = live_bin_root / name
            if destination in synced_destinations:
                continue
            synced_destinations.add(destination)
            sync_file(actions, source, destination, apply=apply, mode=0o755)
    return actions


def merge_openclaw_config(live_path: Path, overlay_path: Path) -> tuple[dict, bool]:
    live = load_json(live_path)
    overlay = load_json(overlay_path)
    merged = deep_merge(live, overlay)
    changed = merged != live
    if set(live.keys()) - set(merged.keys()):
        missing = ", ".join(sorted(set(live.keys()) - set(merged.keys())))
        raise RuntimeError(f"openclaw merge dropped live top-level keys: {missing}")
    return merged, changed


def merge_exec_approvals(live_path: Path, baseline_path: Path) -> tuple[dict, bool]:
    live = load_json(live_path)
    baseline = load_json(baseline_path)
    merged = json.loads(json.dumps(live))

    merged["defaults"] = baseline["defaults"]
    agents = merged.setdefault("agents", {})
    for agent, base_conf in baseline["agents"].items():
        target = agents.setdefault(agent, {})
        for key in ("security", "ask", "askFallback"):
            if key in base_conf:
                target[key] = base_conf[key]
        patterns = []
        seen = set()
        for pattern in base_conf.get("allow_patterns", []):
            if pattern not in seen:
                seen.add(pattern)
                patterns.append(pattern)
        if patterns:
            existing = target.setdefault("allowlist", [])
            existing_by_pattern = {item.get("pattern"): item for item in existing if item.get("pattern")}
            for pattern in patterns:
                if pattern in existing_by_pattern:
                    continue
                existing.append(
                    {
                        "id": str(uuid.uuid4()),
                        "pattern": pattern,
                        "source": "agenticteam-baseline"
                    }
                )
    return merged, merged != live


def sync_managed_config(repo_root: Path, manifest: dict, *, apply: bool) -> list[Action]:
    actions: list[Action] = []
    managed = manifest["managed_config"]

    openclaw_path = Path(managed["openclaw"]["destination"])
    openclaw_source = repo_root / managed["openclaw"]["source"]
    merged_openclaw, changed_openclaw = merge_openclaw_config(openclaw_path, openclaw_source)
    actions.append(
        Action(
            "update" if changed_openclaw else "unchanged",
            openclaw_path,
            f"{managed['openclaw']['strategy']} from {relative_repo_path(openclaw_source, repo_root)}"
        )
    )
    if apply and changed_openclaw:
        ensure_presync_backup(openclaw_path)
        write_bytes_atomic(openclaw_path, json_bytes(merged_openclaw))

    approvals_path = Path(managed["exec_approvals"]["destination"])
    approvals_source = repo_root / managed["exec_approvals"]["source"]
    merged_approvals, changed_approvals = merge_exec_approvals(approvals_path, approvals_source)
    actions.append(
        Action(
            "update" if changed_approvals else "unchanged",
            approvals_path,
            f"{managed['exec_approvals']['strategy']} from {relative_repo_path(approvals_source, repo_root)}"
        )
    )
    if apply and changed_approvals:
        ensure_presync_backup(approvals_path)
        write_bytes_atomic(approvals_path, json_bytes(merged_approvals))

    return actions


def main() -> int:
    args = parse_args()
    if args.agents_only and args.config_only:
        raise SystemExit("--agents-only and --config-only are mutually exclusive")

    repo_root = Path(__file__).resolve().parents[1]
    manifest_path = repo_root / "config" / "live_openclaw_sync_manifest.json"
    manifest = load_json(manifest_path)
    if not args.skip_compat_check:
        validate_prompt_contracts(repo_root, manifest)

    actions: list[Action] = []
    if not args.config_only:
        actions.extend(sync_agent_files(repo_root, manifest, selected_agents=args.agents, apply=args.apply))
        actions.extend(sync_helper_scripts(repo_root, manifest, selected_agents=args.agents, apply=args.apply))
    if not args.agents_only:
        actions.extend(sync_managed_config(repo_root, manifest, apply=args.apply))

    print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Manifest: {manifest_path}")
    for deprecated in manifest.get("deprecated_source_paths", []):
        print(f"Note: deprecated source path is intentionally not synced: {deprecated}")
    print("")
    for action in actions:
        print(f"[{action.kind.upper():9}] {action.destination} :: {action.detail}")

    creates = sum(1 for action in actions if action.kind == "create")
    updates = sum(1 for action in actions if action.kind == "update")
    unchanged = sum(1 for action in actions if action.kind == "unchanged")
    print("")
    print(f"Summary: {creates} create, {updates} update, {unchanged} unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
