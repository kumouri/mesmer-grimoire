---
name: webapp-target-plain-jsp-servlets
description: Recover routes, container-managed authz, session lifetime, inline scriptlet/JSTL business logic, and raw HttpSession usage from web.xml and plain JSP/servlet source — the third (ranked) and most rule-dense legacy web-app target, since business logic routinely lives inline in the page. Use as the webapp-target/plain-jsp-servlets reader within recover-business-rules whenever a target estate has JSP pages with scriptlets or JSTL, or servlets with no framework, and as the shared HttpSession scan for any other reader's Java sources.
---

# Web-app target reader: plain JSP + scriptlets/JSTL + servlets

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

Rank 3 of the ranked legacy web-app targets
([`../../docs/webapp-modernization.md`](../../docs/webapp-modernization.md#ranked-legacy-targets)),
named in the ask as "anything using JSP still." The ranked list calls this "the most rule-dense
case: business logic routinely lives inline in the page" — read every scriptlet like a Java class,
not like markup.

This reader also owns the **raw `HttpSession` scan** (`session.getAttribute`/`setAttribute` by
name), which isn't specific to this target: it's what a Struts Action or a Spring controller falls
back to when it isn't going through either framework's own session sugar (ActionForm scope,
`@SessionAttributes`). [`webapp-target-struts`](../webapp-target-struts/SKILL.md) and
[`webapp-target-spring-mvc-jsp`](../webapp-target-spring-mvc-jsp/SKILL.md) recover their frameworks'
mechanisms directly; run this reader over their Java sources too if you suspect a raw session call
alongside the framework one.

## Procedure

1. **Run the reader over `web.xml` and every `.jsp`/`.jspx`/`.java` file:**

   ```bash
   python <kit root>/scripts/jsp-servlet-reader.py path/to/web.xml path/to/*.jsp \
     --out rules/jsp-servlet.json --session-out session-state/jsp-servlet.json \
     --routes-out routes/jsp-servlet.json
   ```

2. **`<servlet-mapping>`/`<servlet>` pairs are routes, `kind: orchestration`.**
   `<security-constraint>` is a container-managed authz rule, `kind: validation` — cite it under
   the constitution's Auth shim section, same as a Struts `roles` attribute or a Spring
   `@PreAuthorize`. `<session-timeout>` is the session lifetime contract; record it even though it
   isn't tied to one specific attribute.
3. **A scriptlet (`<% ... %>`) with a conditional, loop, or JDBC call is a `kind: calculation` row,
   `confidence: Medium`.** The reader flags *presence* of logic reliably; its exact behaviour needs
   a person reading the block — don't paraphrase the scriptlet from its shape alone.
4. **JSTL `<c:if>`/`<c:choose>` gate page content — read them as validation rules,** not "just
   markup." A `<c:if test="${user.role == 'ADMIN'}">` block hiding a form section is an authz rule
   in disguise; cite it accordingly rather than under a generic view-logic bucket.
5. **Every `session.getAttribute`/`setAttribute("name", ...)` call becomes a
   [`_session_state.py`](../../scripts/_session_state.py) row**, `destination: unclassified`,
   merging a read and a write of the same name in one file into a single row with both citations.
   See [`webapp-session-state-to-stateless`](../webapp-session-state-to-stateless/SKILL.md) for the
   classification step — first-class in this build, not deferred.

## Output

- The rule ledger (Markdown table + `rules/<unit>.json`): routes, container authz, session
  lifetime, scriptlet/JSTL logic.
- The session-state ledger (`session-state/<unit>.json`) for every raw `HttpSession` attribute
  found.
- A route manifest (`routes/<unit>.json`, `_routes.py`) for
  [`webapp-strangler-planner`](../webapp-strangler-planner/SKILL.md).
- **Not covered:** JSP tag files and custom tag libraries' own logic (only the JSTL core tags and
  raw scriptlets in the page itself are read); `web.xml` filters and listeners aren't read by this
  version.

## Anti-patterns

- **Paraphrasing a scriptlet's behaviour from its control-flow shape alone.** "Contains an `if`" is
  a High-confidence *finding*; what the `if` actually decides is a separate, lower-confidence claim
  unless you read the condition.
- **Treating JSTL conditionals as presentation-only.** They routinely encode authz and business
  rules a modernized frontend has to reproduce.
- **Skipping `web.xml` because "the routes are obvious from the JSPs."** `<url-pattern>` is the
  actual route; a JSP's file name is not a reliable substitute for it.

## Next

Rules in hand → back to
[`recover-business-rules`](../recover-business-rules/SKILL.md#output) to assemble the constitution;
routes in hand → [`webapp-strangler-planner`](../webapp-strangler-planner/SKILL.md) to plan the
cutover.
