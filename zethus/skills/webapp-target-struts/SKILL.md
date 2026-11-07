---
name: webapp-target-struts
description: Recover routes, action/form mappings, validation, session-scoped ActionForms, and roles-based authz from Struts 1.x and 2.x config, plus optional Java sources for hybrid Spring-controller-delegates-to-Struts detection — the first (ranked) legacy web-app target. Use as the webapp-target/struts reader within recover-business-rules whenever a target estate has struts-config.xml or a struts.xml, including a hybrid where Spring MVC wraps or invokes a Struts Action/ActionForm.
---

# Web-app target reader: Struts 1.x / 2.x

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

Rank 1 of the ranked legacy web-app targets
([`../../docs/webapp-modernization.md`](../../docs/webapp-modernization.md#ranked-legacy-targets)).
Built for this build's own FIRST REAL TARGET SHAPE — not an edge case, the primary one this reader
is designed around: **Struts actions wrapped in or invoked from a Spring MVC controller, rendering
JSP views, in an app already part-way migrated to REST microservices plus a new frontend.** Combine
with [`webapp-target-spring-mvc-jsp`](../webapp-target-spring-mvc-jsp/SKILL.md) for the Spring side
of that same hybrid, and [`webapp-target-plain-jsp-servlets`](../webapp-target-plain-jsp-servlets/SKILL.md)
for any JSP view either framework renders.

## Procedure

1. **Run the reader over every `struts-config.xml` / `struts.xml`:**

   ```bash
   python <kit root>/scripts/struts-reader.py path/to/struts-config.xml \
     --java path/to/SomeController.java [more java files...] \
     --out rules/struts.json --session-out session-state/struts.json \
     --routes-out routes/struts.json
   ```

   `--java` is optional but matters for this target: pass every Spring controller file you suspect
   delegates to a Struts Action or ActionForm — the reader cross-references class names it collected
   from the XML against each Java file, and separately flags any file that simply `import`s
   `org.apache.struts` on its own (High confidence either way it finds evidence; Medium confidence
   for the class-name cross-reference, since that's a name co-occurring, not a proven call path).
2. **Every `<action>` becomes a route rule, `kind: orchestration`** — path, handler class, bound
   form-bean and its scope. **`validate` defaults to `true` in Struts 1** — a route that never sets
   it still runs ActionForm validation, and the reader records that as its own `kind: validation`
   row rather than folding it into the route row, so it can be cited independently.
3. **`scope` defaults to `session` in Struts 1.** A form-bean an `<action>` doesn't explicitly scope
   to `request` is session-scoped by Struts's own default — the reader writes one
   [`_session_state.py`](../../scripts/_session_state.py) row per session-scoped form-bean,
   `destination: unclassified`, and a matching `SESSTATE-*` rule row citable under the
   constitution's **Session / state** section. Classifying it is not this reader's job — see
   [`webapp-session-state-to-stateless`](../webapp-session-state-to-stateless/SKILL.md).
4. **`roles="..."` on an `<action>` is an authz rule, not metadata.** Cite it under the
   constitution's Auth shim section — see
   [`webapp-session-state-to-stateless`](../webapp-session-state-to-stateless/SKILL.md#auth-shim) for
   how the auth strategy itself (shim vs. replace) is decided.
5. **A `<forward>`/`<result>` is reported on its own line, not nested under its `<action>`.** This is
   a flat scan like every reader in this kit — cross-reference a route to its forwards by path/name
   when writing the constitution, the same discipline `recover-business-rules` already asks for.
6. **Before Stage 2 closes**, the target frontend and auth strategy must both be resolved from the
   HLA — see [`webapp-strangler-planner`](../webapp-strangler-planner/SKILL.md#hla-required). This
   reader's own output doesn't depend on either, but the constitution it feeds into does.

## Output

- The rule ledger (Markdown table + `rules/<unit>.json`): routes, form/validation, authz, hybrid
  delegation.
- The session-state ledger (`session-state/<unit>.json`) for every session-scoped form-bean.
- A route manifest (`routes/<unit>.json`, `_routes.py`) for
  [`webapp-strangler-planner`](../webapp-strangler-planner/SKILL.md).
- **Not covered:** anything not expressed as `<action>`/`<form-bean>`/`<forward>`/`<result>`/
  `<interceptor-ref>` in the config files given — a programmatic Struts 2 action mapping (Convention
  Plugin, annotations) isn't read by this version.

## Anti-patterns

- **Treating the hybrid delegation flag as proof of a call path.** It's a name co-occurring in a
  file; confirm the actual call before relying on it for a phase plan.
- **Skipping the session-scope default because it "should" be request-scoped.** Struts 1's own
  default is session; read what the config actually says, not what a modern app would do.
- **Folding a `roles` attribute into the general route rule.** It needs its own citable row so it
  can be waived, overridden, or cited under Auth shim independently of the route.

## Next

Rules in hand → back to
[`recover-business-rules`](../recover-business-rules/SKILL.md#output) to assemble the constitution;
routes in hand → [`webapp-strangler-planner`](../webapp-strangler-planner/SKILL.md) to plan the
cutover.
