# Python Async and Concurrency

## Principles

- Preserve the application's established synchronous or asynchronous execution
  model; do not convert APIs to async without a concrete need.
- Never perform predictably blocking network, database, subprocess, or large
  filesystem work directly on a latency-sensitive event-loop path.
- Prefer a native async client when the repository already uses one. Otherwise
  isolate blocking calls with the project's established executor or thread
  mechanism when justified.
- Keep task ownership explicit. Await or supervise spawned tasks and define how
  exceptions, cancellation, and shutdown propagate.
- Protect shared mutable state with an appropriate ownership, locking, queueing,
  transaction, or immutability strategy.

## Resource Lifetime

- Close clients, streams, subprocesses, files, executors, and task groups on
  success, error, and cancellation paths.
- Do not catch cancellation as an ordinary failure unless cleanup requires it;
  preserve cancellation semantics afterward.
- Avoid orphan background tasks and unbounded fan-out.
- Use bounded concurrency when external services, memory, file descriptors, or
  rate limits can be exhausted.

## Verification

- Test concurrent ordering assumptions and cancellation where material.
- Prefer deterministic synchronization primitives over timing sleeps.
- Check for deadlocks, race conditions, leaked tasks, and blocking calls.
- Use timeouts to bound tests, not to mask nondeterministic coordination.
