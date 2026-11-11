---
name: webapp-strangler-planner
description: Group recovered routes into strangler-fig cutover units — per-screen-flow where routes share session state, per-route otherwise — exclude routes already migrated to REST/a new frontend, and order session-state extraction before cutover for any unit that depends on it. Use once the webapp-target readers have emitted route manifests for a target, before Stage 3 (Implement) plans which route or flow to build next.
---

# Strangler-fig cutover planner

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

Turns the route manifests [`webapp-target-struts`](../webapp-target-struts/SKILL.md),
[`webapp-target-spring-mvc-jsp`](../webapp-target-spring-mvc-jsp/SKILL.md) and
[`webapp-target-plain-jsp-servlets`](../webapp-target-plain-jsp-servlets/SKILL.md) emit
(`_routes.py`) into a cutover plan, implementing
[`../../docs/webapp-modernization.md`](../../docs/webapp-modernization.md#strangler-fig-migration-path)'s
migration path.

## HLA required

The target frontend and the auth strategy are both required pipeline inputs, read from the HLA, with
no hardcoded default for either — check before Stage 2 closes:

```bash
python <kit root>/scripts/webapp-hla-input-check.py
```

Exit 0 prints both. Exit 1 means **don't assume** — never React+Vite, never Next.js, never `shim`
or `replace` for auth (the auth ask *recommends* shim, but doesn't assume it). What is yours first:
a missing or moved HLA, which you find in the repo from the candidates the message lists, then fix
`modernization.hlaDoc` and re-run. Only a missing frontend or auth answer is the person's: ask it
with the question tool, write the line into the HLA yourself, and re-run.
A recovered rule can still override the auth default for one specific check, recorded as its own
ADR. See [`webapp-session-state-to-stateless`](../webapp-session-state-to-stateless/SKILL.md) for
how the auth strategy interacts with session-state classification (an identity/authz claim lives
behind the shim named here).

## Procedure

1. **Run the planner over every route manifest for the target:**

   ```bash
   python <kit root>/scripts/strangler-planner.py \
     --routes routes/struts.json routes/spring-mvc.json routes/jsp-servlet.json \
     --session-ledger session-state/struts.json session-state/spring-mvc.json \
     --out routes/cutover-plan.json
   ```

   `--session-ledger` is optional but recommended: it annotates each unit's session attributes with
   their current classification status (`unclassified` until a person decides), so the plan itself
   shows what's blocking a unit's cutover, not just which routes it holds.
2. **Grouping is mechanical, not a judgment call:** two routes land in the same unit iff they share
   a session-attribute name or an explicit shared flow id — **decided (2026-09-28, Telegram
   picker):** per-screen-flow where routes share session state, per-route otherwise. Don't
   hand-group routes that don't actually share state just because they "feel like" one flow; don't
   split routes that do share state across two units either — a flow with shared state can't safely
   cut over one route at a time without temporarily splitting session state across old and new.
3. **A route the reader flagged `alreadyMigrated` is excluded and reported separately**, never
   silently re-planned — this is the FIRST REAL TARGET SHAPE's defining property: parts of the
   estate are already on REST/a new frontend, and the plan should cover only the remainder.
4. **Every unit with a session attribute gets an explicit "extract session state" step ordered
   before "cut over router,"** regardless of whether that attribute is classified yet — the
   ordering is structural. Classification itself is a separate, first-class step
   ([`webapp-session-state-to-stateless`](../webapp-session-state-to-stateless/SKILL.md)); a unit
   whose attributes are still `unclassified` can be planned, but
   `overseer-gate.py session-state` refuses to let it be marked migrated until they aren't.
5. **Each unit's remaining steps follow
   [`../../docs/webapp-modernization.md`](../../docs/webapp-modernization.md#strangler-fig-migration-path):**
   build the modernized route(s), replay golden masters against the new path, then cut the router
   over — feature-flagged, reversible by flipping the route back.

## Output

- The cutover plan (`_routes.py`-shaped units plus the already-migrated list), printed and as JSON.
- For each unit: its routes, its session attributes and their classification status, and its
  ordered steps.

## Anti-patterns

- **Grouping by "this feels like one user journey" instead of by actual shared session state.** The
  decided rule is mechanical for a reason — a human sense of "flow" doesn't always match what the
  code actually shares.
- **Cutting a unit over before its session-state extraction step, because the code "looks stateless
  already."** The overseer's `session-state` gate exists precisely so this isn't a judgment call
  made under deadline pressure.
- **Re-planning an already-migrated route "just to be safe."** If the reader's evidence for
  `alreadyMigrated` is wrong, fix the evidence (confirm the call graph) rather than routing around
  the planner's exclusion.

## Next

Rules and routes come from
[`recover-business-rules`](../recover-business-rules/SKILL.md#output)'s web-app target readers.
Plan in hand → `implement-phase`, one unit per phase, Phase 0 = HTTP-level golden masters for every
constitution row in that unit before any modernized code exists (see
[`../../docs/webapp-modernization.md`](../../docs/webapp-modernization.md#the-shared-artifacts-specialized-for-the-web-app)).
