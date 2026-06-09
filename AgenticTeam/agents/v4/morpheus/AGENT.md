# AGENT.md - Morpheus (V4)

## Execution Protocol

1. **Understand Task**: Read task objectives and required deliverables from inputs (like `management/tasks/T###.md`).
2. **Explore Workspace**: Use `fs_read` or `fs_list` to inspect existing implementation or tests.
3. **Implement Changes**: Use `fs_write` or `fs_patch` to create or update implementation files.
4. **Execute Tests**: Discover test files using `tests_discover`, then run tests using `tests_run`.
5. **Iterate & Repair**: If tests fail, read traceback, edit files, and rerun tests until passing.
6. **Submit**: Once all tests pass and required deliverables are complete, submit using `work_submit`. If blocked, submit a block reason using `work_block`.
