---
name: webapp-session-state-to-stateless
description: Classify every recovered HttpSession / ActionForm session-scope / @SessionAttributes / session-scoped bean attribute into one of five stateless destinations, and decide the auth strategy (shim vs. replace) the target HLA names. First-class in v1, not deferred — a flow can't be marked migrated while any of its session attributes is unclassified or still read from HttpSession by the new code. Use after the webapp-target readers have recovered session attributes, before a flow's cutover unit may be marked migrated.
---

# Session state → stateless, and the auth shim

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

Ceryce's requirement, first-class in this build: session state isn't a footnote of the constitution,
it's a design decision made explicitly, per attribute, before a flow cuts over. See
[`../../docs/webapp-modernization.md`](../../docs/webapp-modernization.md) for the SESSION STATE ->
STATELESS design this skill implements, and
[`../../scripts/_session_state.py`](../../scripts/_session_state.py) for the ledger shape. The
attributes classified here come from
[`recover-business-rules`](../recover-business-rules/SKILL.md#reading-web-app-session-state-and-the-auth-strategy)'s
web-app target readers.

## The five destinations

Every attribute the [`webapp-target-*`](../webapp-target-struts/SKILL.md) readers recover starts
`unclassified`. Classifying it means picking exactly one of:

1. **`derivable-per-request`** — recompute it from other inputs; drop the session copy entirely.
2. **`identity-claim`** — an identity/authz claim (a user id, a role, a permission). Lives behind
   the **Auth shim** (below), not in application session state.
3. **`client-held-ui-state`** — frontend state, or a URL/route parameter the new frontend owns.
4. **`server-side-durable`** — a keyed store or database a service owns (a cart id keyed to a user,
   say).
5. **`workflow-state`** — an explicit cross-request workflow/resource with its own id (a
   multi-step wizard's in-progress state, modeled as a resource rather than smuggled through
   `HttpSession`).

A guess isn't good enough — same discipline as every other recovered rule: cite the attribute's
`writtenBy`/`readBy` sites, and record a one-line `rationale` for the destination chosen. Flag it for
sign-off rather than silently picking one — see
[`../../docs/webapp-modernization.md`](../../docs/webapp-modernization.md#mapping-onto-zethuss-stages):
"Session/state rows are the ones most likely to need a person's judgment call — flag them for
sign-off explicitly, don't let them default to 'no state.'"

## Auth shim

**Decided (2026-09-28, Telegram picker):** the auth strategy — `shim` (preserve exact legacy authz
behind an interface; replace the mechanism later, as a separate phase) or `replace` (modernize the
mechanism immediately) — is read from the target HLA, with **no hardcoded default**. Check it with
[`webapp-strangler-planner`](../webapp-strangler-planner/SKILL.md#hla-required)'s
`webapp-hla-input-check.py` call; a missing answer stops the pipeline and asks, recommending shim.

Every `identity-claim`-destination session attribute belongs behind this shim, not in a service's own
session state — that's what keeps an authz mistake from becoming a silent behaviour change alongside
everything else the modernization touches.

## Procedure

1. **Gather every session-state ledger for the flow's routes** (one per reader that touched it —
   Struts, Spring MVC, plain JSP/servlet).
2. **For each unclassified attribute, decide its destination** using the five options above,
   writing `destination` and a one-line `rationale` back into the ledger
   (`_session_state.write_session_ledger`).
3. **Record the classification as part of the constitution's Session / state section**
   ([`../../templates/constitution.md`](../../templates/constitution.md)), cited to the attribute's
   `SESSTATE-*` rule row — not just left in the JSON ledger, which the overseer checks mechanically
   but a reviewer reads in prose.
4. **Before the flow may be marked migrated,** run:

   ```bash
   python <kit root>/scripts/overseer-gate.py session-state \
     --session-ledger session-state/struts.json session-state/spring-mvc.json \
     --new-source path/to/NewController.java
   ```

   Exit 0 means every attribute is classified and none of them is still read via
   `session.getAttribute` in the modernized source passed to `--new-source`. Exit 1 lists exactly
   which attribute is unclassified, or which new-code file still touches `HttpSession` for one —
   fix that before claiming the flow is done, don't waive it.

## Anti-patterns

- **Defaulting every attribute to `client-held-ui-state` to move fast.** That's exactly the
  unreviewed choice this skill exists to prevent — an identity claim landing in frontend state is a
  security bug, not a simplification.
- **Marking a flow migrated with an unclassified attribute "because it's probably fine."** The
  overseer gate exists so this isn't a judgment call made under deadline pressure; if it's genuinely
  fine, classify it and say why.
- **Assuming the auth strategy instead of reading the HLA.** Neither `shim` nor `replace` is a
  pipeline-level default; a missing answer is a stop, not a silent pick.

## Next

Classification in hand → the constitution's Session / state and Auth shim sections are complete for
this flow → `overseer-gate.py session-state` clears →
[`webapp-strangler-planner`](../webapp-strangler-planner/SKILL.md)'s "extract session state" step
for this unit is done, and the cutover step may proceed.
