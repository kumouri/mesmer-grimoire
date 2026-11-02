# Independent work runs at the same time

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-01 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's report of using the kit and her two rulings on it, 2026-11-01, paraphrased below |
| Enforced where | *Run independent work at the same time* and *Keep the plan visible*, rule 2, in [`../com.github.copilot/agents/zethus.agent.md`](../com.github.copilot/agents/zethus.agent.md); *Independent work runs at the same time* in [`../copilot-instructions.md`](../copilot-instructions.md), which the plugin's `sessionStart` hook injects; [`../skills/implement-phase/SKILL.md`](../skills/implement-phase/SKILL.md) step 7; [`../skills/pre-push-gates/SKILL.md`](../skills/pre-push-gates/SKILL.md); [`../skills/docs-sync-check/SKILL.md`](../skills/docs-sync-check/SKILL.md); [`../skills/test-plan/SKILL.md`](../skills/test-plan/SKILL.md); `tests/test_zethus.py`. Convention only at runtime: no script checks it |
| Supersedes | The visible-plan rule's "Exactly one step is in progress at a time" |
| Superseded by | — |

## Decision

Let two or three independent tasks run at once, start remote or long-running work as soon as a
check of its build and deploy definitions shows the pending change doesn't touch it, and re-judge
any results collected while local tooling was still changing.

## Context

Ceryce reported that the agent did one thing at a time even when the work was plainly independent.
Two cases stood out:

- Updating documentation and running the local gates could have overlapped, since the gates didn't
  read the docs.
- The agent wouldn't start independent remote runs while unrelated local changes were pending. The
  only code it had changed was a local-only helper that the remote job's image doesn't contain, so
  the runs would have executed exactly the same code either way. The pending changes alone held
  them back.

Her first ruling set the remote case aside: an agent can't easily tell which code reaches a remote
job, and mixing local and remote code in one tree makes that harder. Independent local tasks,
though, should get limited parallelism.

Her second ruling restored the remote case, in the form of a rule drafted during the discussion:
remote or long-running work starts as soon as the pending change doesn't touch what that work runs,
the agent checks the image or deploy definition instead of guessing, and it says what it checked in
one line.

The second ruling restores what the first set aside, so both halves are built. The concern that the
agent can't easily tell is answered by having it read the definitions, and by not starting when they
don't settle it.

### What forced the serialization

No line in the kit said to hold work for uncommitted code. These lines together left no other
reading, because each described a strict sequence and nothing named an exception:

| What the kit said | Where | Effect |
|---|---|---|
| "seven stages, in order … You don't move on until it is met" | the agent file, its opening | Read as a queue for all work, not an order of exit conditions |
| "the full build and test suite runs once, last, on the exact tree that is pushed. Anything edited after the gates go green sends you back to stage 6." | the agent file, under the stage table | The rule protects the final run, but nothing said anything else could overlap it |
| "Exactly one step is in progress at a time" | the agent file, *Keep the plan visible* rule 2; `README.md` | The one line that forbade concurrency outright. It was written to keep the plan readable |
| "Run it last, after the docs are updated" | `copilot-instructions.md` | Forbade an early gate run by its letter |
| "Run this stage last … If you edit anything after it goes green, run it again." | `pre-push-gates` | Same, and it made any overlap with docs look like wasted work |
| "This stage runs before the gates, not after them" | `docs-sync-check` | Same, from the docs side |
| "Docs comes before Gates, so the full build and test suite runs once, last" | `README.md` | Same, in the description of the flow |

The session she reported isn't available here, so which of these the model acted on can't be shown
from the files. The list is what the kit said, not a reconstruction of its reasoning.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — limited parallelism, plus remote work started on a checked definition | Both of her rulings, plus re-judging and an explicit unblock by the person | Five rules to keep in two host formats | **Chosen** |
| B — limited parallelism alone | Her first ruling | The remote-run case she reported stays blocked | Declined by her second ruling |
| C — start remote work on the agent's judgment | No definition check | A guess presented as a fact, and results from an image that did carry the change | Declined: the second ruling asks for a check, not a guess |
| D — a script that decides from the Dockerfile | Deterministic for one definition format | Images and deploys come from Dockerfiles, build scripts, manifests and charts, and a script covering one of them would give a confident wrong answer on the rest | Declined |

## Consequences

- **Easier:** independent work overlaps, and a remote run doesn't wait on a change it won't run.
- **Harder:** an early gate run that overlaps docs doesn't replace the final run, so that pairing
  can mean a second full suite, which [run each check once per phase](run-once-per-phase.md) worked
  to remove. It is a choice to find a red sooner, not the new default. That record's single counted
  run is unchanged.
- **New obligations:**
  - The final gate run still comes last, on the exact tree that is pushed. A gate run that overlapped
    an edit can find a red but can't clear the push.
  - The mutation check breaks a file on disk, so nothing that reads that file runs alongside it.
  - Sign-off, one phase at a time and the refusal table are unchanged. Parallelism applies to
    independent tasks, so "Do Phase 1 and 2 together" is still declined.
  - The person's word that work isn't affected replaces the check for that work. It isn't an ADR,
    since it's a call about one piece of work, and re-judging still applies to the results.
  - `tests/test_zethus.py` pins the rules in the agent file, the working agreement, the text the
    plugin's hook injects, and the README, plus the absence of the old "exactly one" wording.
