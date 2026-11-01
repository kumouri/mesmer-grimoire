---
name: webapp-target-spring-mvc-jsp
description: Recover routes, JSP view resolution, session attributes, method-security authz, hybrid Struts delegation, and already-migrated-to-REST detection from old Spring MVC controller source — the second (ranked) legacy web-app target. Use as the webapp-target/spring-mvc-jsp reader within recover-business-rules whenever a target estate has @Controller classes rendering JSP views, including a hybrid where the controller wraps or invokes a Struts Action/ActionForm and where some routes are already served by REST.
---

# Web-app target reader: old Spring MVC + JSP

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

Rank 2 of the ranked legacy web-app targets
([`../../docs/webapp-modernization.md`](../../docs/webapp-modernization.md#ranked-legacy-targets)).
Built for the same hybrid shape as
[`webapp-target-struts`](../webapp-target-struts/SKILL.md): a Spring MVC controller that wraps or
invokes a Struts Action/ActionForm, renders JSP views, in an app already part-way onto REST
microservices plus a new frontend (Angular is a supported HLA-named choice — see
[`webapp-strangler-planner`](../webapp-strangler-planner/SKILL.md#hla-required) — not a default).

## Procedure

1. **Run the reader over every controller source file:**

   ```bash
   python <kit root>/scripts/spring-mvc-jsp-reader.py path/to/SomeController.java \
     --struts-classes LoginAction LoginForm \
     --out rules/spring-mvc.json --session-out session-state/spring-mvc.json \
     --routes-out routes/spring-mvc.json
   ```

   `--struts-classes` is optional: pass Struts Action/ActionForm class names (from
   [`webapp-target-struts`](../webapp-target-struts/SKILL.md)'s intake) to cross-reference for
   hybrid delegation. A file that plainly `import`s `org.apache.struts` is flagged without it, at
   High confidence.
2. **Every `@RequestMapping`/`@GetMapping`/`@PostMapping`/`@PutMapping`/`@DeleteMapping`/
   `@PatchMapping` becomes a route rule, `kind: orchestration`.** This is a flat scan — a
   class-level mapping and a method-level mapping are both read the same way, not stitched into one
   combined path; note the two separately in the constitution if the estate nests them.
3. **A bare `return "viewName";` inside the same file is a candidate view resolution,**
   `kind: orchestration`, `confidence: Medium` — the flat scan can't prove which method it belongs
   to, so confirm the pairing by reading the method before citing it as High.
4. **`@SessionAttributes({...})` names session-carried model attributes directly** — one
   [`_session_state.py`](../../scripts/_session_state.py) row per name, `destination: unclassified`.
   See [`webapp-session-state-to-stateless`](../webapp-session-state-to-stateless/SKILL.md) for how
   classification works and why it's first-class, not deferred, in this build.
5. **`@PreAuthorize`/`@PostAuthorize`/`@Secured`/`@RolesAllowed` are authz rules**, `kind:
   validation` — cite them under the constitution's Auth shim section.
6. **Already-migrated detection is structural, read it as a hint, not a fact.** A `@RestController`
   class, or `ResponseEntity`/`@ResponseBody` found near a route's mapping annotation, marks that
   route `alreadyMigrated: true` in the route manifest. Confirm before excluding a route from
   cutover planning — the heuristic looks at proximity in the source text, not the actual call
   graph.

## Output

- The rule ledger (Markdown table + `rules/<unit>.json`): routes, views, session attributes, authz,
  hybrid delegation.
- The session-state ledger (`session-state/<unit>.json`) for every `@SessionAttributes` name.
- A route manifest (`routes/<unit>.json`, `_routes.py`), with `alreadyMigrated` set where the
  reader found REST evidence — [`webapp-strangler-planner`](../webapp-strangler-planner/SKILL.md)
  excludes these from cutover planning and reports them separately.
- **Not covered:** view resolution done through a `ModelAndView` object instead of a bare string
  return; XML-based Spring MVC config (`<mvc:annotation-driven>`-only wiring with no annotated
  classes) isn't read by this version.

## Anti-patterns

- **Trusting the already-migrated flag without checking the route actually reaches a real REST
  service.** A `ResponseEntity` return can still be legacy code that happens to return JSON — read
  the method before excluding the route from planning.
- **Assuming a `return "viewName"` belongs to the mapping directly above it.** In a large controller
  file with several handler methods, verify the pairing.
- **Skipping `--struts-classes` because "this file doesn't look like it calls Struts."** The whole
  point of this target shape is that the delegation is easy to miss on a skim; run the
  cross-reference.

## Next

Rules in hand → back to
[`recover-business-rules`](../recover-business-rules/SKILL.md#output) to assemble the constitution;
routes in hand → [`webapp-strangler-planner`](../webapp-strangler-planner/SKILL.md) to plan the
cutover.
