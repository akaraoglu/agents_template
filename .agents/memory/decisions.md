# Decisions Memory

## Purpose

Record concise rationale for durable repository-wide guidance decisions. The
root guidance remains authoritative if wording later diverges.

## Entries

- Provider-neutral lifecycle guidance is separated from explicitly named
  provider playbooks so agents can share engineering standards without erasing
  necessary platform procedures.
- Language-specific rules live in separate skills because language ecosystems
  evolve independently and future languages should not expand the core prompt.
- Authorization is documented separately from runtime capability because agents
  may receive broad filesystem or tool access for inspection while the user's
  requested mutation remains narrow.
