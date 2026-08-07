---
name: releases
description: Prepare, publish, deploy, and verify releases with explicit authorization and rollback planning. Use for versioning, release notes, artifacts, tags, publication, deployment, or post-release checks.
---

# Releases

## Purpose

Make release state, authorization, evidence, rollout, and recovery explicit.

## Inputs

- Exact requested operation: prepare, tag, publish, deploy, or verify
- Repository release policy, versioning, branch, and artifact workflow
- Included commits or changes, required gates, target environment, and approver

## Workflow

1. Confirm the authorized release stage. Preparation does not authorize tagging,
   publication, deployment, or promotion.
2. Inspect repository release documentation, CI, version sources, changelog
   conventions, artifact configuration, and recent release history.
3. Define release scope and ensure it excludes unrelated working-tree changes.
4. Identify compatibility, migration, security, operational, and rollback risks.
5. Run required quality gates and verify version consistency, lockfiles,
   generated metadata, release notes, licenses, and artifact contents.
6. Build artifacts reproducibly through repository-native commands and inspect
   names, versions, checksums, signatures, and provenance where applicable.
7. Before an authorized publication or deployment, confirm target, credentials
   boundary, rollout sequence, monitoring, rollback trigger, and recovery steps.
8. Perform only the authorized operation without bypassing protections.
9. Verify remote state and user-visible health after publication or deployment.
10. Report released scope, artifacts, commands, results, rollback status, and
    unresolved risks.

## Expected Output

For preparation: a release-ready change set and evidence. For publication or
deployment: a verified release in the exact authorized target with recovery
information.

## Validation

- Included changes and release notes match actual history.
- Required checks and artifacts are complete and reproducible.
- Version, tag, package, and deployment targets agree.
- Post-release checks confirm the expected remote state.

## Cautions

- Never infer authorization to tag, publish, deploy, promote, or merge.
- Never replace a tag, overwrite an artifact, or force a deployment without
  explicit approval and repository policy.
- Never expose credentials in command output or reports.
- Do not claim rollback is available unless the procedure and required artifacts
  exist.

## Related Guidance

- `.agents/skills/git-delivery/SKILL.md`
- `.agents/skills/verification/SKILL.md`
- `.agents/capabilities/boundaries.md`
