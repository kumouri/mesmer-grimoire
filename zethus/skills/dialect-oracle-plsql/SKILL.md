---
name: dialect-oracle-plsql
description: Recover business rules from Oracle 12c-era PL/SQL — packages, triggers, autonomous transactions, %TYPE/%ROWTYPE, bulk collect/FORALL, WHEN OTHERS handlers, sequences, materialized views — from a source-controlled DDL repo or DDL extracted from a live database, and record a keep/wrap/port disposition per procedure against the target HLA's default. Use as the dialect/oracle-plsql reader within recover-business-rules whenever a batch job calls Oracle stored procedures.
---

# Dialect reader: Oracle PL/SQL

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

The first SQL-dialect reader `recover-business-rules` ships with (see
[`../../docs/batch-modernization.md`](../../docs/batch-modernization.md#pluggable-axis-2--db-backend-and-sql-dialect-skill-family)
— DB2/SQL PL, T-SQL and PL/pgSQL are named seams, not built yet). It reads packages, triggers and
procedures rather than the shell or framework code that calls them; combine it with
[`batch-type-ksh-scripts`](../batch-type-ksh-scripts/SKILL.md) or
[`batch-type-spring-jpa-jdbc`](../batch-type-spring-jpa-jdbc/SKILL.md) for the calling side of a job.

## HLA required

**Before this reader may record any disposition,** the target High-Level Architecture (HLA) document
must be configured (`modernization.hlaDoc` in the Zethus config) and declare a default
stored-procedure disposition. Check it first:

```bash
python <kit root>/scripts/hla-input-check.py
```

Exit 0 prints the default (`keep`, `wrap`, or `port`). Exit 1 means **don't assume a disposition**:
never `wrap` or `port` on your own, and never fall back to "port everything" or "keep everything."
A missing or moved HLA is yours to find first, from the candidates the message lists; fix
`modernization.hlaDoc` and re-run. Ask the person only for an HLA the repo doesn't have, or for the
disposition itself, then write their answer into the HLA as the
`Default stored-procedure disposition:` line and re-run. A recovered rule can still override the default for one specific procedure; record that
override as its own ADR (`write-adr`), because a blanket policy hides exactly the
behaviour-preservation risk the constitution exists to name.

## Procedure

1. **Run the DDL intake:**

   ```bash
   python <kit root>/scripts/plsql-ddl-intake.py \
     --repo-source path/to/ddl-repo \
     [--extract-source path/to/live-extract --extract-date YYYY-MM-DD] \
     --out rules/plsql-intake.json
   ```

   Prefer `--repo-source` (a source-controlled DDL repo) when one exists. `--extract-source` is DDL
   pulled from a live database — pair it with `--extract-date`, the day it was pulled, not "as of
   the repo's history." Giving both turns the extract into a **drift cross-check**: the same object
   with a different body in each is reported as DRIFT, never silently resolved one way.
2. **Also run intake over the DDL repo even when a job's caller lives elsewhere.** Some batch jobs
   are defined only as a `DBMS_SCHEDULER` job or a legacy `DBMS_JOB.SUBMIT` call with no
   application-side trigger — the intake's batch discovery finds these, and they belong in the same
   rule ledger as any `ksh`- or crontab-discovered job.
3. **Read the intake's report before writing a single rule.** `INVISIBLE BODY` entries — a package
   spec with no body found anywhere, or a body Oracle's `wrap` utility obfuscated — are a gap in
   what this pipeline can recover, **not a no-op**: name each one as an open question in the ledger,
   don't silently skip the procedure. A `DRIFT` entry means the repo and the live database disagree;
   record which one the rule ledger cites and why, as a rule in its own right if the reason matters
   (a hotfix applied live and never backported, say).
4. **Turn each visible object into ledger rows,** following
   [`recover-business-rules`](../recover-business-rules/SKILL.md)'s procedure and kind vocabulary.
   PL/SQL specifics worth a rule on sight: `WHEN OTHERS THEN NULL` (error-handling — a swallowed
   exception is almost always worth a High-confidence row), autonomous transactions
   (`PRAGMA AUTONOMOUS_TRANSACTION` — a commit-boundary rule), bulk collect/`FORALL` batch sizes
   (a performance-shaped rule that may also be a correctness one, if a partial-batch failure's
   handling differs from a row-at-a-time loop's), and any use of `%TYPE`/`%ROWTYPE` tied to a
   specific table shape a ported version must preserve.
5. **Record a disposition per procedure:** `keep` (call it from the modernized service, unchanged),
   `wrap` (a typed service method with no logic change), or `port` (rewrite its logic). Start from
   the HLA's default (step 0); override per procedure only when a recovered rule shows the default
   can't be preserved that way, and write the override as an ADR naming the rule that forced it.
6. **Access is scriptable only.** `recover-business-rules` and the characterization-test runner use
   JDBC, SQLcl, `sqlplus`, or an equivalent CLI — never a GUI database tool. A step that genuinely
   has no scripted path (a vendor console with no CLI equivalent) becomes an explicit manual handoff
   to a person, recorded the same way any other overseer gap is — never silently skipped.

## Output

- The rule ledger rows this reader contributes (Markdown table + `rules/<unit>.json`), each PL/SQL
  object's provenance from the intake JSON, and the disposition table (procedure → keep/wrap/port →
  ADR id, where overridden).
- **Not covered:** every `INVISIBLE BODY` object from the intake, named individually, not summarized
  away.

## Anti-patterns

- **Assuming a disposition instead of reading the HLA.** There is no pipeline-level default; guessing
  one is exactly the unreviewed choice the constitution exists to prevent.
- **Treating an invisible body as "no rules here."** It's a gap this pipeline can't yet close, not
  evidence the procedure does nothing interesting.
- **Reading the DDL repo's full git history for context.** Provenance is one commit per file; the
  repo may carry old secrets in its history that don't belong in a rule ledger or a chat transcript.
- **Skipping the drift check because the repo copy "should" be current.** That's exactly the
  assumption a live extract exists to test.

## Next

Rules in hand → back to
[`recover-business-rules`](../recover-business-rules/SKILL.md#output) to assemble the constitution.
