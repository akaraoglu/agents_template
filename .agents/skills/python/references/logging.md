# Python Logging

## Principles

- Use the repository's logging framework and structured context conventions.
- With standard `logging`, prefer lazy parameter interpolation such as
  `logger.info("Processed item %s", item_id)` when constructing the message has
  non-trivial cost.
- Include context that helps correlate an operation, such as request, job, trace,
  or resource identifiers, when safe and available.
- Never log credentials, authentication material, private payloads, or sensitive
  personal data.
- Avoid duplicate logging at multiple layers for the same exception.

## Levels

- `DEBUG`: diagnostic detail useful during investigation
- `INFO`: meaningful lifecycle or operational state changes
- `WARNING`: unexpected or degraded behavior that is recoverable
- `ERROR`: an operation failed and requires attention or propagation

Follow repository conventions when they define different semantics.

## Exceptions

- Log where useful context is available and the error is actually handled or
  translated.
- If an exception will propagate to a boundary that already logs it, enrich the
  exception or attach structured context instead of logging it repeatedly.
- Include stack traces when they aid diagnosis, but avoid exposing sensitive
  local variables or payloads.
