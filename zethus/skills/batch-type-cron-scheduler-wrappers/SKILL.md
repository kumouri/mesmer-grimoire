---
name: batch-type-cron-scheduler-wrappers
description: Recover the scheduling contract -- frequency, dependency ordering, calendar exceptions, and the environment a job silently relies on -- from crontab entries or a scheduler product's job-definition export such as Control-M, and map inter-job ordering onto the modernization target (a Spring Batch job flow by default, or a cloud workflow orchestrator such as AWS Step Functions). Use as the batch-type/cron-scheduler-wrappers reader within recover-business-rules whenever a batch estate's ordering lives in a scheduler rather than in application code.
---

# Batch-type reader: cron / scheduler wrappers

> `<kit root>` is the folder holding Zethus's `scripts/` and `templates/`: the path announced at session start, else two folders above this skill's folder.

**Decided (2026-09-28, `docs/batch-modernization.md`):** this reader generalizes to any scheduler
product, not only crontab — Control-M is the first one this kit reads directly, via
[`control-m-reader.py`](../../scripts/control-m-reader.py). The reader's job is unchanged regardless
of scheduler: recover the dependency and calendar rules; only where those rules land downstream
(a Spring Batch flow vs. a cloud workflow orchestrator) differs by target.

## Procedure

1. **Get the job-definition export**, not a description of the schedule. For Control-M, this is the
   Control-M/EM bulk export (`<DEFTABLE><FOLDER><JOB>…</FOLDER></DEFTABLE>`, with `<INCOND>`/
   `<OUTCOND>` recording dependencies). For a plain crontab, the crontab file itself.
2. **Run the reader:**

   ```bash
   python <kit root>/scripts/control-m-reader.py --export path/to/export.xml \
     --target spring-batch-flow \
     --out rules/scheduling.json
   ```

   `--target step-functions` produces an AWS Step Functions state-machine skeleton instead; the
   default matches this spec's default target architecture (Spring Boot 3 + Spring Batch 5). Either
   way the output is a **mapping suggestion**, not the target's actual config file — the implementing
   phase writes that, informed by this skeleton.
3. **A reported `CYCLE` blocks the mapping — don't resolve it by guessing an order.** A cycle in a
   Control-M export usually means a misread dependency convention (see the tool's docstring for the
   default-`OUTCOND` convention it assumes) or a genuine scheduling bug worth its own rule. Either
   way, it's a person's call, not a silent pick.
4. **Every calendar attribute (`WDAYS`, `MONTHS`, `TIME`, `CONFCAL`) is a scheduling rule,** not
   metadata to skip — "the nightly run skips weekends" only survives modernization if it's written
   down. Cite it into the constitution's **Scheduling / invocation contract** row.
5. **Also record the environment a wrapper sets up before the real job runs,** if the export or an
   accompanying wrapper script names one — a job that silently relies on an env var Control-M sets is
   a rule the modernized scheduler must also satisfy, one way or another.

## Output

- The scheduling rule-ledger rows, printed and as JSON.
- The dependency-ordered job list (or the reported cycle, unresolved).
- The mapping skeleton for the chosen target.

## Anti-patterns

- **Assuming crontab's implicit ordering (declaration order) is the dependency order.** Crontab has
  no native inter-job dependency mechanism; if jobs depend on each other only by careful time
  offsets, that offset *is* the rule, and a fragile one worth flagging, not silently preserving.
- **Picking an order to break a reported cycle.** Stop and ask; a cycle is either a misread
  convention or a real bug, and guessing hides which.
- **Treating the mapping skeleton as done.** It's a starting shape for the phase that writes the
  actual Spring Batch flow or state machine, not a finished artifact.

## Next

Rules in hand → back to
[`recover-business-rules`](../recover-business-rules/SKILL.md#output) to assemble the constitution.
