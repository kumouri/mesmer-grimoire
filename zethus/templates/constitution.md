# Constitution: {{unit}}

| Field | Value |
|---|---|
| Status | {{status}} |
| Date | {{date}} |
| Owner | {{owner}} |
| Rule ledger(s) | {{ruleLedgers}} |
| Fixture manifest | {{fixtureManifest}} |
| HLA reference | {{hlaDoc}} |

*Owner* names a person or team as they write it: by default the person Zethus works for
(`identity.py`), never a placeholder, and never the agent.

Each row below cites a rule id from the ledger(s) above: `- [R1] <checkable statement> —
confidence: High|Medium|Low`. A `Low`-confidence row needs a recorded waiver:
`- [R7] <statement> — confidence: Low (waiver: <adr-id>)`. A section with nothing recovered says
so explicitly: `- No rule found — <reason>`, never left blank. See
[`../docs/modernization-shared.md`](../docs/modernization-shared.md#2-the-behaviour-constitution-template-templatesconstitutionmd).

Before Stage 3 (Implement): `python .github/zethus/scripts/overseer-gate.py constitution
--constitution <this file>` must exit 0. Before Stage 4 (Tests) reports done: every rule id cited
below needs a fixture in the manifest named in "Fixture manifest" above, captured by running the
*legacy* system — see [`fixture-manifest.example.json`](fixture-manifest.example.json) for the
shape — checked with `overseer-gate.py golden-master --constitution <this file>`.

## Inputs

- No rule found — not yet recovered.

## Outputs

- No rule found — not yet recovered.

## Side effects

- No rule found — not yet recovered.

## Ordering

- No rule found — not yet recovered.

## Error & restart semantics

- No rule found — not yet recovered.

## Commit / transaction boundaries

- No rule found — not yet recovered.

## File / message formats

- No rule found — not yet recovered.

## Exit / status contract

- No rule found — not yet recovered.

## Scheduling / invocation contract

- No rule found — not yet recovered.

## Session / state

Every `HttpSession` / Struts `ActionForm` session-scope / Spring `@SessionAttributes` /
session-scoped bean attribute goes here, with its stateless destination — see
[`../docs/webapp-modernization.md`](../docs/webapp-modernization.md)'s SESSION STATE -> STATELESS
design: (1) derivable per request, (2) an identity/authz claim (behind the Auth shim below),
(3) client-held UI/flow state, (4) server-side durable state, or (5) explicit workflow state. A
target with no clean HTTP request/response boundary (a portlet, or a JSF/Wicket/Vaadin component
tree) records its component-state transitions here too, with the HTTP-level fixture still covering
the outer render/action/event boundary — the constitution convention decided in
[`../docs/webapp-modernization.md`](../docs/webapp-modernization.md#open-questions) rather than a
dedicated skill family. A flow can't be marked migrated while any attribute here is unclassified or
still read from `HttpSession` by the new code —
`python .github/zethus/scripts/overseer-gate.py session-state --session-ledger <path>` must exit 0.

- No rule found — not yet recovered.

## Auth shim

The legacy authz mechanism this modernization must preserve exactly before any replacement is
considered — roles, realms, session timeout, every check a rule recovers. Preserving it behind an
interface first, with OAuth2/OIDC (or any other replacement) as a later, separately decided phase,
is the default; see [`../docs/webapp-modernization.md`](../docs/webapp-modernization.md#open-questions).
The target HLA names the auth strategy (`webapp-hla-input-check.py`); a missing HLA answer stops
the pipeline and asks rather than assuming either shim or replace.

- No rule found — not yet recovered.
