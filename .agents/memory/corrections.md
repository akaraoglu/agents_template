# Corrections Memory

## Purpose
Record mistakes, outdated assumptions, and corrected guidance that future agents should not repeat.

## Entries
- Do not inspect, restore, merge, or infer current behavior from `codexteam_20260618.zip`; it represents the obsolete system.
- Do not describe CodexTeam as having a controller, board, leader runtime service, HTTP API, or MCP implementation unless those capabilities are added to the current source later.
- Do not treat a worker result as completion. Validate artifacts and run independent verification before updating project state.
- Keep improvement plans minimal and ordered around the single highest-impact problem. Do not present a broad backlog as one implementation proposal.
- End every plan with a criticism section that questions its assumptions, complexity, risks, and evidence. Discuss the plan and its criticism with the user before implementation.
- Do not duplicate changing CodexTeam paths, role defaults, or model routing in root memory. Use the current toolkit code and role manifests as execution authority and keep subsystem rationale in CodexTeam memory.
- Do not pair a long-running worker poll with a shorter outer tool yield. Use one 60-120 second blocking poll and inspect evidence only after terminal status unless a concrete failure requires diagnosis.
