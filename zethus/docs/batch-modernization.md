# Zethus extension: legacy batch modernization

**Status:** PARTIAL (v1 built) · **Owner:** Ceryce Armstrong · **Date:** 2026-09-27 · **Related:**
[`modernization-shared.md`](modernization-shared.md), [`../README.md`](../README.md)

> Client-specific detail (what one real estate actually looks like) does not belong in this public
> repo. Those questions are tracked privately; see [Open questions](#open-questions) for the
> generic ones this spec needs answered regardless of estate.

## Implementation status (v1, 2026-09-28)

**Built:** the overseer as three script-gates (`scripts/overseer-gate.py`); the HLA input-contract
gate (`scripts/hla-input-check.py`); PL/SQL DDL intake with provenance, drift and
`DBMS_SCHEDULER`/`DBMS_JOB` batch discovery (`scripts/plsql-ddl-intake.py`); a Control-M
job-definition reader mapping onto a Spring Batch flow or Step Functions
(`scripts/control-m-reader.py`); a `ksh` wrapper reader (`scripts/ksh-wrapper-reader.py`); the
`recover-business-rules` skill plus four readers —
[`dialect-oracle-plsql`](../skills/dialect-oracle-plsql/SKILL.md),
[`batch-type-ksh-scripts`](../skills/batch-type-ksh-scripts/SKILL.md),
[`batch-type-cron-scheduler-wrappers`](../skills/batch-type-cron-scheduler-wrappers/SKILL.md), and
[`batch-type-spring-jpa-jdbc`](../skills/batch-type-spring-jpa-jdbc/SKILL.md) (a reading guide, no
dedicated script — see that skill for why); the `constitution.md` template and an example fixture
manifest. All of it targets the Copilot CLI, per this doc's own decided scope. See
[`../README.md`](../README.md#v1--batch-modernization-copilot-cli) for the installable piece list.

**Deferred**, per Open question 5's own recommendation to ship the ask's named first target rather
than every reader at once: `batch-type-spring-batch-xml`, `batch-type-stored-procedure-heavy`, and
the `dialect-db2-sql-pl` / `dialect-tsql` / `dialect-postgres-plpgsql` named seams. Open questions 2
(golden-master granularity), 3 (where fixtures run), and 4 (a stricter confidence bar for
restart/commit rows) are **left open, on purpose** — none was marked DECIDED before this build, and
nothing in v1 hardcodes an answer to any of them; each is still a call for whoever specs a real
consuming engagement's characterization-test implementation. Reporting a flagged credential to
security, and rotating it, stay manual steps — the overseer's job stops at detection.

## The ask

Ceryce, Telegram, 2026-09-27 01:10 CT:

> "let's start speccing the missing pieces of the zethus batch modernization extension; this one's
> first target are old spring-based JPA/JDBC batches and shell scripts (specifically ksh) that use
> stored procedures, etc; first target DB and SQL Dialect are Oracle and PL/SQL."

And from the todo behind it (2026-09-26, due 2026-10-02, priority critical — shared verbatim in
[`modernization-shared.md`](modernization-shared.md#the-ask)): specialized skills per DB backend,
batch job type and SQL dialect; business-rule recovery from code; a behaviour constitution; an
overseer.

- **Answers:** the pluggable axes for batch work, the default target architecture and why,
  Oracle/PL-SQL as the first dialect with named seams for the others, and how the shared artifacts
  ([`modernization-shared.md`](modernization-shared.md)) specialize for batch.
- **Does not answer:** any one real batch estate's specifics (scheduler product, Oracle version,
  how procedures are deployed) — those are open questions a person answers per engagement, not
  facts this spec can assert.

## What is true today

See [`modernization-shared.md`](modernization-shared.md#what-is-true-today) (F1–F8) for the
Zethus-pipeline facts this spec builds on; not repeated here. Batch-specific facts:

| # | Fact | Where | How verified |
|---|---|---|---|
| F9 | `run-local-gates.py` already resolves a Maven/Gradle wrapper, including the Windows `PATHEXT` case | `README.md:58` | read the scripts table row |
| F10 | Nothing in the kit today reads PL/SQL, `ksh`, Spring Batch config, or a scheduler's crontab/config, and no gate step type exists for "run a batch job against a fixture database" | — | `grep -ri "plsql\|ksh\|spring.batch\|crontab"` across `zethus/` → 0 hits |

**What this did not cover:** any specific organization's batch estate — no such code was read for
this spec; the axes and defaults below are a design, not an observation. That gap is exactly what
the private, client-specific open questions (noted below, not reproduced here) exist to close
before implementation starts on a real estate.

## Design

### Pluggable axis 1 — legacy batch type (skill family)

Each is a `recover-business-rules` reader ([shared spec](modernization-shared.md#1-business-rule-recovery-skill-recover-business-rules))
specialized to one shape of legacy batch code, so a consuming engagement installs only the readers
its estate needs:

| Skill | Reads | What it adds to the rule ledger that a generic reader would miss |
|---|---|---|
| `batch-type/spring-batch-xml` | Spring Batch XML job/step config, listeners | Step/chunk boundaries, skip/retry policies, and job-parameter contracts as scheduling and error-handling rules |
| `batch-type/spring-jpa-jdbc` | Plain Spring apps hand-rolling batch loops over JPA/JDBC, no Spring Batch framework | Where "a batch" is only a `main()` and a loop — commit points and restart behaviour must be inferred from transaction boundaries in code, not framework config |
| `batch-type/ksh-scripts` | `ksh` (and adjacent POSIX shell) drivers: argument parsing, exit codes, `trap`, file locking (`flock`, lockfiles), log rotation | Exit-code contracts, signal handling, and the shell's own retry/backoff loops as first-class rules, not incidental scripting |
| `batch-type/cron-scheduler-wrappers` | Crontab entries, or a scheduler's job-definition files, plus any wrapper script that sets up environment before the real job runs | The scheduling contract itself (frequency, dependency ordering, calendar exceptions) and environment/config the job silently relies on |
| `batch-type/stored-procedure-heavy` | Jobs that are thin callers around a PL/SQL package that does the real work | Flags that the bulk of the rule ledger for this job lives in the SQL-dialect axis, not here — this reader's job is mostly to record the calling contract (parameters, out cursors, exception propagation back to the caller) |

A given job is usually more than one row (a `ksh` wrapper that calls a Spring JAR that calls
stored procedures) — the readers compose; the rule ledger is per source unit and the constitution
aggregates across all of them for one job.

**Decided (2026-09-28), orchestration readers:** `batch-type/cron-scheduler-wrappers` generalizes
to any scheduler product, not only crontab — e.g. a reader for a scheduler product such as Control-M
— and its output is a mapping of inter-job dependencies (recorded as scheduling rules, same as a
crontab entry) onto whatever the target orchestrates with: a Spring Batch job flow under this
spec's default target architecture (below), or a cloud workflow orchestrator such as AWS Step
Functions if a consuming engagement chooses one instead. The reader's job is unchanged either way —
recover the dependency and calendar rules — only where those rules land downstream differs.

### Pluggable axis 2 — DB backend and SQL dialect (skill family)

| Skill | First target | Plug-in seam for later |
|---|---|---|
| `dialect/oracle-plsql` | **Yes — build first.** Packages, triggers, autonomous transactions, `%TYPE`/`%ROWTYPE`, bulk collect/`FORALL`, `WHEN OTHERS` handlers, sequences, materialized views | — |
| `dialect/db2-sql-pl` | No | Named seam only: same reader shape (packages → modules, `SQL PL` syntax), not built this round |
| `dialect/tsql` | No | Named seam only: T-SQL's stored procedures, `TRY...CATCH`, `@@ROWCOUNT` |
| `dialect/postgres-plpgsql` | No | Named seam only: `PL/pgSQL` functions, `RAISE`, triggers |

Each dialect reader's output feeds the rule ledger with one extra required field beyond the shared
shape: a **disposition recommendation** per procedure — `keep` (leave running in the database,
call it from the modernized service exactly as before), `wrap` (expose it behind a typed service
method with no logic change, so its behaviour is preserved by construction), or `port` (rewrite
its logic in the target language). This is a per-procedure decision, not a blanket policy, and
each one is recorded as an ADR once decided (`write-adr`), because "port everything" and "keep
everything" both hide real behaviour-preservation risk that the constitution needs to name.

**Decided (2026-09-28):** there is no hardcoded default disposition. A target High-Level
Architecture (HLA) document is a **required pipeline input**, and the *default* keep/wrap/port
disposition for a procedure with no procedure-specific rule is read from that document — the HLA
is the source of record for what the target architecture wants done with stored procedures in
general, this pipeline doesn't bake in a guess of its own. A recovered business rule can still
override that default for one specific procedure (an HLA default of `wrap`, overridden to `port`
for the one procedure a rule shows can't be preserved by wrapping, say). **If no HLA is supplied,
the pipeline stops before Stage 2 and asks for one** rather than silently assuming `wrap` or `port`
— see [Open questions](#open-questions) question 1, now decided on this basis.

**Decided (2026-09-28), v1 source acquisition:** PL/SQL source may be DDL extracted from a live
database rather than checked-in package source. `recover-business-rules` records that provenance
explicitly — *extracted-on-date*, not "as of the repo's history" — so a rule's citation is honest
about how fresh it is. If a referenced object's body isn't visible in what was extracted (only a
package spec with no body, or a wrapped/obfuscated body), that is a flagged gap in the rule ledger,
**never treated as a no-op**: a procedure this pipeline can't read is a procedure it can't yet
recover rules for, not one with no rules to recover.

**Decided (2026-09-28), access routes:** `recover-business-rules` and the characterization-test
runner use only scriptable access to the database — JDBC, SQLcl, `sqlplus`, or an equivalent CLI —
never a GUI database tool. A step that can only be done through a GUI (a vendor console with no
scripted equivalent, say) becomes an explicit manual handoff to a person, recorded the same way any
other overseer gap is, not silently skipped.

### Pluggable axis 3 — target architecture (default, with rationale)

**Default: Spring Boot 3 + Spring Batch 5**, with PL/SQL disposition decided per procedure as
above, not assumed.

Why this default and not a full rewrite onto something else:

- The legacy estate this targets is *already* Spring-based (JPA/JDBC batches) — staying in the
  Spring ecosystem means the modernization changes the batch *framework and packaging*, not the
  language, dependency-injection model, or the team's existing operational tooling around Spring
  apps. That shrinks the diff the constitution has to prove is behaviour-preserving.
- Spring Batch 5's step/chunk/restart model maps close to directly onto the constitution's
  **Ordering**, **Commit / transaction boundaries**, and **Error & restart semantics** rows — a
  legacy commit-every-N-records loop becomes a chunk size, a legacy "resume from the last
  checkpoint" script becomes Spring Batch's own restart-from-failure, rather than requiring a
  bespoke reimplementation of both.
- It is the framework Copilot (and Claude) have the deepest, most current training exposure to
  among JVM batch frameworks, which matters for a pipeline whose whole premise is an AI agent
  doing the work.

This is a default, not a mandate: a consuming engagement can choose differently (say, an
event-driven redesign, or a cloud workflow orchestrator such as AWS Step Functions if the estate's
dependency graph is scheduler-driven rather than framework-driven) and record that choice as an ADR
against this spec's recommendation — the constitution and rule-recovery skills don't change either
way; only the target side of the phase plan does.

### The shared artifacts, specialized for batch

- **Constitution rows that matter most here:** commit intervals, restart/checkpoint semantics, and
  exit-code contracts (batch jobs are usually invoked by something that only sees the exit code),
  plus file formats where the job reads or writes fixed-width, delimited, or mainframe-style
  extract files, and the full scheduling contract (frequency, calendar exceptions, upstream/
  downstream job dependencies).
- **Characterization tests for batch:** a golden master here is *"run the legacy job against a
  known input snapshot, capture its output file/table state and exit code, replay the same input
  against the modernized job, diff."* This needs a fixture database — see
  [Open questions](#open-questions) — and, for stored procedures with a `keep` disposition, the
  golden master calls the same real procedure from both legacy and modernized callers, so the test
  is only proving the caller's behaviour is preserved, not re-testing the procedure itself.
  **Decided (2026-09-28):** whichever way question 3 resolves, a shared non-production database is
  an allowed fixture target, not only the disposable-containerized option — but only under
  non-destructive constraints: the suite writes into its own data namespace, cleans up or rolls
  back everything it wrote, and assumes no exclusive access to the instance (other work may be
  reading or writing it concurrently). A suite that can't meet those three constraints against a
  given shared instance isn't ready to run there.
- **Overseer gates:** unchanged from [`modernization-shared.md`](modernization-shared.md#4-the-overseer--a-stage-gate-not-a-second-pipeline) —
  before Implement, every constitution row sourced or explicitly empty; before Tests report done,
  every row has a fixture that ran against the *legacy* job, not an authored expectation.

### Mapping onto Zethus's stages

Reuses [`modernization-shared.md`](modernization-shared.md#mapping-onto-zethuss-stages) in full.
Batch-specific instantiation:

| Stage | Batch-specific detail |
|---|---|
| 1 · Research | `recover-business-rules` runs the matching `batch-type/*` and `dialect/oracle-plsql` readers together over one job's Java/`ksh`/PL-SQL/SQL/config sources |
| 2 · Spec | Per-procedure disposition (keep/wrap/port) is decided here and recorded as an ADR each |
| 3 · Implement | Phase 0 = golden masters against the *current* Oracle schema and job, for every constitution row, before any Spring Batch code is written |
| 6 · Gates | New `gates.steps` entry: run the characterization suite against the fixture database as part of `run-local-gates.py` |

### What's new vs. reused

| Reused unchanged (from Zethus / shared spec) | New for batch |
|---|---|
| Seven-stage pipeline, sign-off, ADRs, `run-local-gates` mechanism | `batch-type/*` skill family (5 skills) |
| Rule ledger shape, constitution template, overseer gate design | `dialect/oracle-plsql` skill, with named seams for DB2/T-SQL/Postgres |
| `test-plan`'s mutation-check discipline | Batch-shaped characterization test recipe (fixture DB, before/after diff) |
| Config resolution order, `docSync.map` | A `gates.steps` convention for "run against a fixture database" gate steps |

## Open questions

Generic questions this spec needs answered before a consuming engagement can start implementing,
regardless of which real estate it targets. Engagement-specific questions (what one estate's
scheduler, Oracle version, or deployment process actually is) are tracked privately, not here —
see the note at the top of this document.

1. **Default per-procedure disposition when there's no strong reason either way?** Options:
   (A) `wrap` by default, `port` only when a rule can't otherwise be preserved (e.g., the
   procedure does something the target language can't call into, like a DB-side scheduled job),
   `keep` only for pure set-based bulk operations with no business logic; (B) `port` by default, to
   get everything out of the database. **DECIDED (2026-09-28): neither A nor B — no hardcoded
   default.** A target High-Level Architecture (HLA) document is a required pipeline input, and the
   default keep/wrap/port disposition is read from it rather than assumed by this spec; recovered
   business rules still drive per-procedure overrides against that default. If no HLA is supplied,
   the pipeline stops and asks, rather than silently falling back to A or B. Reasoning: a
   pipeline-level guess is exactly the kind of unreviewed disposition choice the constitution exists
   to prevent — the HLA is the artifact where that call belongs, not a hardcoded fallback. See the
   [Design](#pluggable-axis-2--db-backend-and-sql-dialect-skill-family) section above for detail. ·
   Decided by: Ceryce.
2. **Golden-master granularity: full schema/database diff, or targeted table/file diff?**
   Options: (A) diff only the tables/files the constitution's Outputs/Side-effects rows name;
   (B) diff the whole schema state before/after. **Recommended: A** — cheaper to run and to
   maintain, and a full-schema diff catches drift the constitution didn't ask about, which belongs
   in rule recovery, not in every test run. · Decides: whoever specs the first
   `characterization-tests-batch` implementation.
3. **Where do golden-master fixtures run?** Options: (A) a disposable, containerized Oracle
   instance (e.g., the free Oracle XE image), config-driven so Postgres/DB2/SQL Server plug in
   later the same way; (B) a shared non-production Oracle instance. **Recommended: A** — matches
   Zethus's own preference for local, repeatable checks (`pre-push-gates` running "on the working
   tree," not against shared state) and avoids a characterization suite that can only run where one
   shared DB happens to be reachable. · Decides: whoever specs the first consuming engagement,
   informed by the private, estate-specific answer to whether a sanitized non-prod instance exists
   at all.
4. **Does a `Low`-confidence rule in a commit-interval or restart-semantics row ever get a
   different bar than elsewhere in the constitution?** Options: (A) the same bar as
   [`modernization-shared.md`](modernization-shared.md#open-questions) question 3 (a recorded
   waiver, never an automatic block); (B) these two rows specifically require `High` confidence
   before Implement may start, because a wrong restart assumption corrupts data rather than just
   producing a wrong answer. **Recommended: B** — restart and commit-boundary mistakes are the
   batch failure mode most likely to be silent and destructive, so this is the one place a stricter
   bar earns its cost. · Decides: Ceryce.
5. **Do the five `batch-type/*` skills ship together, or one at a time as engagements need them?**
   Options: (A) all five in the first implementation phase; (B) `spring-jpa-jdbc` and
   `ksh-scripts` first (the ask's named first target), the other three as later phases gated on a
   real engagement needing them. **DECIDED (2026-09-28, v1 build): B, widened by one** —
   `spring-jpa-jdbc`, `ksh-scripts` and `cron-scheduler-wrappers` (Control-M) shipped together,
   because the ask separately named a scheduler reader as in-scope for v1; `spring-batch-xml` and
   `stored-procedure-heavy` stayed deferred, matching B's reasoning exactly — a skill built without
   a real job to test it against is a guess dressed up as a deliverable. · Decided by: implementer,
   per this question's own routing.
