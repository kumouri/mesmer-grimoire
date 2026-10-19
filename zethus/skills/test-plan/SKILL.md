---
name: test-plan
description: Plan and verify the tests for a change — per phase, what each test proves, at what level, including the refusal and failure paths, plus a mutation check that the key test actually fails without the change. Use when filling a spec's Test plan section, before implementing a phase, or when asked "how should we test this" or "are these tests enough".
---

# Test plan

A test only matters if it fails when the code is wrong. A plan that lists only happy paths proves
the code runs, not that it's right. This procedure plans the tests before the code, then checks
that they bite.

## When writing the spec — plan

For each phase, list the tests in the spec's **Test plan** table:

| Phase | Test | Level | Proves |
|---|---|---|---|
| 0 | `test_logs_retry_attempt` | unit | every retry is recorded (no behaviour change) |
| 1 | `test_backoff_doubles_until_cap` | unit | the new behaviour |
| 1 | `test_gives_up_after_max_attempts` | unit | the failure path |
| 1 | `test_rejects_negative_delay_config` | unit | the refusal |

Cover each of these in every behaviour-changing phase:

- **The change:** the new behaviour, with its edge values (zero, one, the maximum, empty).
- **The failure path:** what happens when a dependency fails or times out, or returns something
  unexpected.
- **The refusal:** input or state the code must reject, and a check that it does. Test refusals
  explicitly, not just by implication.
- **What must not change:** a regression test on the nearest existing behaviour you're relying on.

Choose the lowest level that proves the point. Use integration or end-to-end tests only for
behaviour that exists only when the parts are joined. Tag anything you can't automate as
**manual**, with the steps, so it shows up under *What was not checked* in the PR.

## After implementing — verify

1. **Every planned test exists and passes, in one run.** Run the phase's tests once. If any fails,
   fix it and run them again; the run that counts is the green one, on the tree you go on to
   mutation-check. If you dropped or changed a test, record why in the spec's *As built* list.
2. **Mutation check the key test.** Stage the file that holds the line that matters
   (`git add <file>`), so the index holds the version that just passed. Revert or break that line,
   run the key test alone, and confirm it fails. Then restore the file from the index
   (`git restore <file>`) and prove the restore with `git diff --quiet -- <file>`: exit 0 means the
   file is byte for byte the one that passed, so there's nothing to re-run. A non-zero exit means
   it isn't; restore it until it is. If the mutated test still passes, it proves nothing: fix the
   test, not the code. Record the check in one line in the PR ("reverting `retry.py:52` fails
   `test_backoff_doubles_until_cap`").
3. **Flaky means failing.** A test that passes on retry isn't passing. Fix it, or quarantine it
   with a tracked issue that names it, and say so in the PR.

## Anti-patterns

- **Asserting only that code ran** ("no exception"), not what it produced.
- **Mocking the thing under test.**
- **Snapshot tests nobody reads.** A snapshot updated by reflex proves nothing.
- **Typing test totals into docs.** Counts go stale by the next commit. Say how to measure them
  instead.
