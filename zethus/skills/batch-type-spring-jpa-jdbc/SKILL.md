---
name: batch-type-spring-jpa-jdbc
description: Recover business rules from plain Spring applications that hand-roll batch loops over JPA/JDBC with no Spring Batch framework -- where "a batch" is only a main() and a loop, and commit points and restart behaviour must be inferred from transaction boundaries in code rather than read off framework config. Use as the batch-type/spring-jpa-jdbc reader within recover-business-rules for the ask's named first target, old Spring-based JPA/JDBC batches.
---

# Batch-type reader: plain Spring JPA/JDBC batch loops

**Scope decision for v1:** unlike the PL/SQL, Control-M and `ksh` readers, this reader has no
dedicated parsing script. Spring/JPA/JDBC batch code is general-purpose Java with no small,
stereotyped syntax the way `getopts` or `DBMS_SCHEDULER.CREATE_JOB` calls are — a bespoke Java parser
is a large dependency for what `research-existing-code`'s own reading procedure already covers well.
This skill is the *reading guide*: what to look for and how to grade it, using ordinary code search
and reading, per [`recover-business-rules`](../recover-business-rules/SKILL.md)'s base procedure. A
future revision may add a script once a real engagement shows which of the patterns below are worth
mechanizing.

Where Spring Batch's own job/step/chunk config would tell you the commit interval and restart
behaviour directly (see `batch-type-spring-batch-xml`, a named seam, not built this round), a plain
JPA/JDBC batch has none of that — it's a `main()` and a loop, and the same facts are implicit in how
transactions are opened and closed. That's what this reader is for.

## What to look for

1. **Commit boundaries.** Find every `@Transactional` boundary, every explicit
   `EntityManager.flush()`/`clear()`, and every JDBC `commit()` call. The loop's actual commit
   interval is wherever one of these sits *inside* the iteration — "commits every record" (no batching
   at all) and "commits every 500 records" are very different restart stories, and the difference is
   easy to miss if you only read the loop's top-level shape.
2. **Restart / resume behaviour.** Does the loop track a high-water mark (a last-processed id, an
   offset file, a status column) that a restarted run reads before resuming? Or does every restart
   reprocess everything from the start? Neither answer is wrong, but the constitution needs the real
   one, not the one that "should" be true of a well-written batch.
3. **Idempotency on rerun.** If a run is restarted after a partial commit, does reprocessing an
   already-committed record cause a duplicate side effect (a duplicate insert, a duplicate downstream
   call), or is there a check that makes it a no-op? This is usually the highest-stakes rule in the
   whole job and the one most often undocumented.
4. **Skip/error policy.** When one record's processing throws, does the loop abort the whole run, log
   and continue, or retry that record? Cite the exact `catch` block and what it does — a
   `catch (Exception e) { log.error(...); }` with no `continue`/`return`/`throw` after it is exactly
   the kind of implicit rule this whole skill exists to surface.
5. **Batch size and memory shape.** A JDBC `fetchSize`/`setFetchSize` or a JPA `Query.setMaxResults`
   used for paging is a rule about how much of the input is held in memory at once, worth a row if the
   modernized version's memory behaviour needs to match (a Spring Batch chunk size, for instance).
6. **Where the loop gets its input and writes its output.** A `SELECT ... FOR UPDATE SKIP LOCKED`, a
   status-column claim-then-process pattern, or a plain unfiltered `SELECT *` each imply a different
   concurrency contract if two instances of the job ever run at once — state explicitly whether that
   was ever true of this job's deployment, or say it's unknown.

## Grading confidence

- **High** — an explicit `@Transactional(propagation = ...)` annotation, an explicit commit call at
  a fixed interval, an explicit high-water-mark read/write.
- **Medium** — transaction behaviour inferred from a framework default (e.g., Spring's
  `@Transactional` default propagation) rather than an explicit annotation on this method.
- **Low** — restart/idempotency behaviour inferred only from the *absence* of a check, not a
  confirmed test of what actually happens on a real restart.

## Output

Follow [`recover-business-rules`](../recover-business-rules/SKILL.md)'s output shape: the rule ledger
table plus `rules/<unit>.json`, each row's **Kind** drawn from the shared vocabulary (commit/restart
findings are usually `error-handling` or `orchestration`; batch sizing is `calculation` or
`orchestration` depending on whether it changes correctness or only throughput).

## Anti-patterns

- **Assuming Spring's default transaction behaviour without checking it applies here.** A
  `@Transactional` on a calling method, a proxy that isn't being invoked through Spring (a
  self-invocation), or an explicitly disabled transaction manager all change what "the default" means
  in this specific codebase.
- **Treating "no explicit restart handling" as "restart is safe."** State the gap explicitly —
  "no restart/resume mechanism found — treated as full-reprocess-on-restart until a golden master
  says otherwise," the same sentinel language the constitution template itself uses.
- **Skipping this reader because the job "looks simple."** A `main()` and a loop is exactly where
  commit and idempotency rules hide in plain sight, because there's no framework config forcing them
  to be explicit.

## Next

Rules in hand → back to
[`recover-business-rules`](../recover-business-rules/SKILL.md#output) to assemble the constitution.
