# {{id}}: {{title}}

| Field | Value |
|---|---|
| Status | {{status}} |
| Date | {{date}} |
| Deciders | {{deciders}} |
| Recorded by | {{recordedBy}} |
| Source | the spec section, ticket, PR or meeting where this was decided |
| Enforced where | a file and symbol, a CI check, a branch rule — or "convention only" |
| Supersedes | — |
| Superseded by | — |

> *Deciders* are the people who made the decision, named as they write their names: by default
> the person Zethus works for (`identity.py`). *Recorded by* is the agent that wrote this text, never
> a decider. Never a placeholder such as TBD or "Requester". Delete this note.

## Decision

One imperative sentence, with no reasoning in it. *Example: "Publish order events through the
transactional outbox; never from the request handler."*

## Context

The forces at play: what is true today, what constraint or incident made this a decision, and what
happens if nobody decides. Cite facts with `file:line` or a link.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — … | … | … | **Chosen** |
| B — … | … | … | |
| C — do nothing | … | … | |

## Consequences

- **Easier:** …
- **Harder:** …
- **New obligations:** anything that must now be maintained, checked or remembered. If "Enforced
  where" says "convention only", say here what will catch a violation — or accept that nothing will.

## Why not the others

One line per rejected option, so it is not re-proposed as a new idea later.

## Revisit when

The condition that would reopen this decision: a volume threshold, a dependency's end of life, a
failed measurement.
