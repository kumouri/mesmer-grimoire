# Lesson review checklist

Use this when reviewing a PR that promotes a lesson into the **shared** tier
(`memory/lessons.jsonl`). When the memory lives in its own git repo, copy this file to
`.github/pull_request_template.md` so it appears on every promotion PR.

A shared lesson steers everyone's future work, so the bar is higher than for a local one.
**Merging the PR is the approval:** the lesson on the branch already reads `review.state:
approved`, and the author's next `mnemosyne sync` retires their local copy. If it shouldn't be
shared, close the PR instead.

- [ ] **True and sourced.** The lesson is accurate and its `source` (spec/ticket, anchors, or
      `reflection_of`) lets a reviewer verify it against its origin.
- [ ] **Actionable.** The `lesson` says what to *do* next time, not just what went wrong.
- [ ] **Correctly scoped.** The `trigger` fires where it should and not everywhere — tags and
      other axes are specific enough that recall won't surface it on unrelated work.
- [ ] **Not a duplicate.** It isn't a near-copy of an existing active lesson (would it have
      reinforced one instead?). Check `mnemosyne hygiene`.
- [ ] **Generalizable.** It applies beyond the single ticket that produced it.
- [ ] **Right confidence.** `high` only if it's well-established; uncertain lessons are `low`
      (surfaced flagged-for-confirmation).
- [ ] **No secrets / PII.** No credentials, tokens, customer data, or internal identifiers that
      shouldn't be shared. The engine already scrubbed the login name and absolute paths; a clean
      scrub is not clearance, so read the text anyway.
- [ ] **Authored by the engine.** The JSONL wasn't hand-edited (ids, stamps, and `LESSONS.md`
      are consistent; `mnemosyne validate` passes).
