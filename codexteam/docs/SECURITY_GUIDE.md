# Security Guide

CodexTeam defaults to denial for unsafe operations.

## Denied Or Approval-Gated Categories

- Path traversal and symlink escape
- Hidden path access
- Secret-looking paths
- Raw shell execution
- Process execution
- Network access
- Destructive operations
- Merge
- Cleanup

Workers cannot approve their own output. They produce evidence for human review.

