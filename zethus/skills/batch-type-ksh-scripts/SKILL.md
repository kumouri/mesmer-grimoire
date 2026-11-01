---
name: batch-type-ksh-scripts
description: Recover business rules from ksh (and adjacent POSIX shell) batch drivers -- argument parsing, exit-code contracts, trap/signal handling, file locking, and retry/backoff loops -- as first-class rules rather than incidental scripting. Use as the batch-type/ksh-scripts reader within recover-business-rules whenever a batch job is driven by a ksh wrapper, alone or in front of a Spring JAR or a call into stored procedures.
---

# Batch-type reader: ksh scripts

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

A `ksh` wrapper is usually treated as plumbing around "the real job." It isn't: its exit code is
often the *only* thing the caller (a scheduler, another script) ever sees, and its trap handlers and
lock files are the actual definition of what happens when the job is interrupted. This reader makes
those explicit. See
[`../../docs/batch-modernization.md`](../../docs/batch-modernization.md#pluggable-axis-1--legacy-batch-type-skill-family).

## Procedure

1. **Run the reader over every wrapper in the job:**

   ```bash
   python <kit root>/scripts/ksh-wrapper-reader.py path/to/job.ksh [more.ksh ...] \
     --out rules/job-ksh.json
   ```

   It recovers, each cited to `file:line`: `getopts` argument parsing (`kind: validation`), `exit N`
   statements (`kind: error-handling` — this is the job's exit-code contract), `trap` handlers
   (`kind: error-handling`), file locking via `flock` or the `mkdir`-as-mutex idiom
   (`kind: orchestration`), and retry/backoff loops (`kind: error-handling`, graded Medium when the
   loop's bound is a clear counter comparison, Low when a sleep loop's bound can't be read
   mechanically).
2. **Read every finding before trusting it.** This is pattern matching over the script's text, not a
   shell parser — it can miss a retry loop written unusually, or flag a `mkdir` that has nothing to
   do with locking. Confirm each finding against the actual script before it becomes a ledger row,
   the same discipline `research-existing-code` applies to any citation.
3. **The exit-code contract is usually the most important output here.** List every distinct exit
   code the script can produce and what each means to its caller — this becomes the constitution's
   **Exit / status contract** row directly.
4. **A trap that cleans up a lock file or temp state is a restart-semantics rule,** not just an
   error-handling detail: it tells you whether a killed run leaves the system in a state the next
   run can safely resume from. Cite it into the constitution's **Error & restart semantics** row.
5. **Merge with the caller.** If the `ksh` wrapper invokes a Spring JAR or calls stored procedures,
   its rules combine with [`batch-type-spring-jpa-jdbc`](../batch-type-spring-jpa-jdbc/SKILL.md) or
   [`dialect-oracle-plsql`](../dialect-oracle-plsql/SKILL.md)'s findings into one job's rule ledger —
   this reader's job is the wrapper's own contract, not the whole job.

## Output

- The rule ledger rows this reader contributes, as printed and as `rules/<script>.json`.
- Which exit codes exist and what each means — feed this straight into the constitution.

## Anti-patterns

- **Trusting a retry-loop finding at High confidence.** It's inferred from shape; grade it Medium or
  Low per the tool's own output, and say why if you override it.
- **Skipping a script because "it's just a wrapper."** The wrapper is frequently where the actual
  restart and exit-code contract live, not the code it calls.
- **Hand-parsing the script instead of running the reader first.** Run it, then verify — reading a
  200-line script line by line for every job doesn't scale, and the reader exists so you don't have
  to for the stereotyped part.

## Next

Rules in hand → back to
[`recover-business-rules`](../recover-business-rules/SKILL.md#output) to assemble the constitution.
