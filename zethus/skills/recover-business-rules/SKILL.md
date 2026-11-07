---
name: recover-business-rules
description: Recover implicit business rules from legacy source before a modernization touches it, in the shape of research-existing-code but aimed at legacy code instead of a live-codebase question. Turns a magic number, an unexplained null check, a swallowed exception, or a commented-out branch into an explicit, numbered, file:line-cited rule with a confidence level. Use at Stage 1 (Research) of any modernization engagement, before writing the constitution, and before any legacy source is rewritten, wrapped, or ported.
---

# Recover business rules

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

Legacy code encodes decisions nobody wrote down: a threshold, a retry count, a day it skips, an
error it silently ignores. Rewriting it without recovering those decisions first loses them exactly
once, permanently. This skill turns each one into a citable, numbered row before any of it changes.
See [`../../docs/modernization-shared.md`](../../docs/modernization-shared.md#1-business-rule-recovery-skill-recover-business-rules)
for the full design this skill implements.

This is the generic shape. A consuming engagement installs the per-source-shape readers it needs
alongside it — batch: [`batch-type-spring-jpa-jdbc`](../batch-type-spring-jpa-jdbc/SKILL.md),
[`batch-type-ksh-scripts`](../batch-type-ksh-scripts/SKILL.md),
[`batch-type-cron-scheduler-wrappers`](../batch-type-cron-scheduler-wrappers/SKILL.md),
[`dialect-oracle-plsql`](../dialect-oracle-plsql/SKILL.md); web app:
[`webapp-target-struts`](../webapp-target-struts/SKILL.md),
[`webapp-target-spring-mvc-jsp`](../webapp-target-spring-mvc-jsp/SKILL.md),
[`webapp-target-plain-jsp-servlets`](../webapp-target-plain-jsp-servlets/SKILL.md) — each following
this shape but reading one kind of legacy source. A job is usually more than one row: a `ksh`
wrapper calling a Spring JAR calling stored procedures composes all four batch readers into one rule
ledger; a hybrid web app composes the three web-app readers the same way (see
[`webapp-target-struts`](../webapp-target-struts/SKILL.md) for the Struts-wrapped-in-Spring-MVC
shape this build's web-app readers are built for).

## Procedure

1. **Write down the unit under study in one line.** One job, one package, one script — not "the
   batch estate." If you can't name the unit, you aren't ready to recover rules from it.
2. **Read the code, not a description of it.** A ticket, an old design doc, or a colleague's summary
   is a lead, not a rule. A doc and the code disagreeing is itself a fact worth a row.
3. **For every place behaviour isn't obvious from a name, write a rule.** A magic number, a
   `WHEN OTHERS THEN NULL` handler, a commented-out branch, a hard-coded holiday list, a retry loop,
   an exit code nobody explains — each becomes one ledger row:

   | # | Rule | Kind | Where (`file:line`) | Confidence | Why |
   |---|---|---|---|---|---|
   | R1 | Orders over $10,000 require a second approval | validation | `OrderValidator.java:142` | High | explicit `if` with a named constant |
   | R2 | Retry a failed remote call up to 3 times, 5 s apart | error-handling | `retry.ksh:31-38` | High | explicit loop and `sleep 5` |
   | R3 | The nightly run skips weekends | scheduling | `CRONTAB:4` | Medium | inferred from `0 2 * * 1-5`; no comment confirms intent |

   **Kind** is one of: `validation`, `calculation`, `orchestration`, `side-effect`,
   `error-handling`, `scheduling`, `formatting`. Add a new one only when none of these fit.
4. **Grade confidence honestly, three levels:**
   - **High** — the code states the rule outright (an explicit condition, a named constant, a
     documented format).
   - **Medium** — inferred from behaviour with more than one plausible reading (a schedule
     expression with no comment, a default that might be intentional).
   - **Low** — a guess from naming or structure alone, no behavioural evidence.
5. **Every row needs a citation.** A row with no `file:line` is a hypothesis, not a recovered rule —
   leave it out of the ledger, or mark it explicitly as an open question instead.
6. **Write the companion ledger file** alongside the Markdown table, one entry per row, same fields,
   as `rules/<unit>.json`:

   ```json
   {"unit": "OrderValidator.java", "rules": [
     {"id": "R1", "rule": "Orders over $10,000 require a second approval", "kind": "validation",
      "where": "OrderValidator.java:142", "confidence": "High",
      "why": "explicit if with a named constant"}
   ]}
   ```

   This is what the overseer's `constitution` and `golden-master` gates
   (`scripts/overseer-gate.py`) and this repo's own `_ledger.py` read — a Markdown table alone can't
   be checked mechanically, and this pipeline's whole point is that coverage is checked, not
   eyeballed.
7. **Say what you did not cover.** Same discipline as `research-existing-code`: name the files,
   modules or environments you didn't read. An empty "not covered" section is a claim to have read
   everything.

## Reading a PL/SQL disposition

When a row's unit is a stored procedure (via `dialect-oracle-plsql`), record one extra field: a
**disposition recommendation** — `keep`, `wrap`, or `port` — per procedure. The *default* disposition
comes from the target HLA document, never from this skill (see
[`dialect-oracle-plsql`](../dialect-oracle-plsql/SKILL.md#hla-required)); a recovered rule can
override that default for one procedure, recorded as its own ADR.

## Reading web-app session state and the auth strategy

When a row's unit is a `HttpSession`/ActionForm-scope/`@SessionAttributes` attribute (via
[`webapp-target-struts`](../webapp-target-struts/SKILL.md),
[`webapp-target-spring-mvc-jsp`](../webapp-target-spring-mvc-jsp/SKILL.md), or
[`webapp-target-plain-jsp-servlets`](../webapp-target-plain-jsp-servlets/SKILL.md)), classification
into one of five stateless destinations is a separate, first-class step — see
[`webapp-session-state-to-stateless`](../webapp-session-state-to-stateless/SKILL.md) — never left
`unclassified` past sign-off. Grouping recovered routes into a cutover plan is
[`webapp-strangler-planner`](../webapp-strangler-planner/SKILL.md)'s job, once the readers above have
run.

## Output

- The rule ledger, as a Markdown table and the companion `rules/<unit>.json`.
- **Not covered**, same discipline as `research-existing-code`.
- **Open questions** the source can't answer — a person, or the estate's own docs, has to.

## Anti-patterns

- **A rule with no citation.** It's a hypothesis; label it as one.
- **Inventing a new `kind` per rule.** Seven kinds is the vocabulary; stretch one before adding an
  eighth.
- **Grading everything High.** If the code merely suggests the behaviour, it's Medium or Low —
  optimistic grading defeats the waiver mechanism the constitution relies on.
- **Recovering rules from a description of the legacy system instead of the system itself.** The
  ask, a runbook, or a wiki page is where to start looking, never where the citation points.

## Next

Rule ledger in hand → author the constitution
([`../../templates/constitution.md`](../../templates/constitution.md)) as part of the spec's "What
is true today," per [`write-spec-full`](../write-spec-full/SKILL.md). Before Stage 3 (Implement)
opens, `python <kit root>/scripts/overseer-gate.py constitution --constitution <path>` must
exit 0.
