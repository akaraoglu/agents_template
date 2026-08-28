# Skill Evaluation

CodexTeam has a small manual evaluation layer for checking root skill routing and
selected CodexTeam authority decisions. It is separate from project lifecycle,
worker spawning, role selection, and generated guidance. Deterministic structural
tests remain the required first check and make no model or network calls.

## Deterministic Checks

`tests/test_skill_structure.py` verifies:

- Root `.agents/skills/*/SKILL.md` frontmatter names, common required sections,
  and referenced repository files.
- CodexTeam role skill references in their declared order.
- Byte-identical project skill guidance projection.
- AgentSpec guidance containment and declared order.

Run the focused suite from the CodexTeam root:

```bash
PYTHONDONTWRITEBYTECODE=1 ../env-python/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_skill_structure.py tests/test_skill_evals.py tests/test_docs.py
```

## Manual Evaluation

The strict root-skill TOML catalog at
`tests/fixtures/skill_evals/cases.toml` contains eight text-only cases, one for
each added domain workflow. The separate bounded
`tests/fixtures/skill_evals/codexteam-cases.toml` catalog covers five CodexTeam
authority decisions. Each invocation evaluates at most eight cases. Every case
declares disjoint required, allowed, and forbidden route and decision
identifiers. Unknown fields, duplicate identifiers, overlaps, invalid
identifiers, and catalogs over eight cases fail before execution.
The model receives each case's candidate identifiers without their required,
allowed, or forbidden classification. This bounds the vocabulary and prevents
cross-case label leakage while preserving the behavioral choice under test.

Preview the fixed local-provider request without creating the output path,
session, or lifecycle state:

```bash
./scripts/run-skill-evals.py --profile qwen38-27b \
  --output /tmp/codexteam-skill-eval.json --dry-run
```

Run one schema-constrained, tool-free request against a curated local Ollama
profile:

```bash
./scripts/run-skill-evals.py --profile qwen38-27b --reasoning medium \
  --output /tmp/codexteam-skill-eval.json
```

Select `--catalog tests/fixtures/skill_evals/codexteam-cases.toml` for the
CodexTeam authority cases.

There is no default output path. Live execution refuses cloud profiles and
existing output paths, posts only one user message plus a response schema to the
fixed loopback Ollama endpoint, supplies no tools, has a bounded timeout of 300
seconds by default and 900 seconds maximum, caps provider and model response
sizes, rejects returned tool calls, and never retries. One scored report is
created exclusively at the requested path. The evaluator has no filesystem,
shell, MCP, lifecycle, or project-state capability.

## Scoring

A route or decision group passes only when every required identifier is selected,
no forbidden identifier is selected, and every other selected identifier is in
the allowed set. A case passes when both groups pass. The initial acceptance
threshold is `1.0`: every case in the selected catalog must pass. Exit status is `0` for acceptance,
`1` for a scored result below threshold, and `2` for catalog, profile, execution,
or response errors. The explicit output file contains the model response and all
missing-required, forbidden-selected, and unexpected findings.
