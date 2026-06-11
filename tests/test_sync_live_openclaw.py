from __future__ import annotations

import json

from AgenticTeam.scripts.sync_live_openclaw import merge_openclaw_config, replace_exec_approvals


def test_replace_exec_approvals_preserves_socket_and_drops_legacy_agents(tmp_path):
    live_path = tmp_path / "live-exec-approvals.json"
    baseline_path = tmp_path / "exec-approvals.json"

    live_path.write_text(
        json.dumps(
            {
                "version": 1,
                "socket": {"path": "/tmp/openclaw.sock", "token": "secret"},
                "defaults": {"security": "full"},
                "agents": {
                    "smith": {
                        "security": "allowlist",
                        "allowlist": [
                            {
                                "id": "old",
                                "pattern": "/home/alik/workspace/clawspace/bin/smith_plan_project.sh",
                                "source": "old",
                            }
                        ],
                    },
                    "niaobe": {"security": "allowlist", "allowlist": []},
                },
            }
        ),
        encoding="utf-8",
    )
    baseline_path.write_text(
        json.dumps(
            {
                "defaults": {"security": "allowlist", "ask": "off", "askFallback": "deny"},
                "agents": {
                    "neo": {
                        "security": "allowlist",
                        "ask": "off",
                        "askFallback": "deny",
                        "allow_patterns": ["/home/alik/workspace/clawspace/bin/run_team.sh"],
                    },
                    "smith": {
                        "security": "allowlist",
                        "ask": "off",
                        "askFallback": "deny",
                        "allow_patterns": [],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    replaced, changed = replace_exec_approvals(live_path, baseline_path)

    assert changed is True
    assert replaced["socket"] == {"path": "/tmp/openclaw.sock", "token": "secret"}
    assert set(replaced["agents"]) == {"neo", "smith"}
    assert replaced["agents"]["neo"]["allowlist"][0]["pattern"].endswith("run_team.sh")
    assert replaced["agents"]["smith"]["allowlist"] == []


def test_merge_openclaw_config_prunes_legacy_defaults_flag(tmp_path):
    live_path = tmp_path / "live-openclaw.json"
    overlay_path = tmp_path / "openclaw.json"

    live_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "workspace": "/tmp/openclaw-workspace",
                        "v4_enabled": True,
                    },
                    "list": [{"id": "main"}],
                },
                "bindings": [
                    {"match": {"accountId": "neo"}, "agentId": "neo"},
                    {"match": {"accountId": "niaobe"}, "agentId": "niaobe"},
                ],
                "gateway": {"port": 18789},
            }
        ),
        encoding="utf-8",
    )
    overlay_path.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "workspace": "/tmp/openclaw-workspace",
                    },
                    "list": [{"id": "main"}, {"id": "neo"}],
                },
                "bindings": [
                    {"match": {"accountId": "neo"}, "agentId": "neo"},
                ],
            }
        ),
        encoding="utf-8",
    )

    merged, changed = merge_openclaw_config(live_path, overlay_path)

    assert changed is True
    assert "v4_enabled" not in merged["agents"]["defaults"]
    assert merged["gateway"] == {"port": 18789}
    assert merged["agents"]["list"] == [{"id": "main"}, {"id": "neo"}]
    assert merged["bindings"] == [{"match": {"accountId": "neo"}, "agentId": "neo"}]
