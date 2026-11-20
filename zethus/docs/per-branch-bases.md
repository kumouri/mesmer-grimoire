# Each branch has its own base: a default base, and per-branch bases

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Ceryce Armstrong |
| Recorded by | Claude Code (AI agent). It wrote this record; the *Choices made inside the ask* below are its proposals, which stand once the change is merged |
| Source | Ceryce's request, 2026-11-19, paraphrased below |
| Enforced where | `branchModel.bases` and `--base-for` in [`../scripts/base-freshness.py`](../scripts/base-freshness.py) (the resolver, the chain, the retarget and rewritten-parent checks, the run log); Stage 0, the stage table and *Branch model* in [`../com.github.copilot/agents/zethus.agent.md`](../com.github.copilot/agents/zethus.agent.md); [`../skills/pre-push-gates/SKILL.md`](../skills/pre-push-gates/SKILL.md) (*Bring a stale branch up to date*, *Keep a chain of bases in sync*); [`../skills/zethus-pr-description/SKILL.md`](../skills/zethus-pr-description/SKILL.md) (step 1); [`../skills/implement-phase/SKILL.md`](../skills/implement-phase/SKILL.md) (preconditions); [`../copilot-instructions.md`](../copilot-instructions.md) (*Start from a fresh base*, *Pull requests*); the example config; `tests/test_zethus_per_branch_bases.py` |
| Extends | [Base freshness runs at two checkpoints](base-freshness-cadence.md), [the next phase starts on push](phase-advance-on-push.md), [`pr-later` style](phase-advance-without-pr.md) |
| Supersedes | — |
| Superseded by | — |

## Decision

Each branch has a base of its own. `branchModel.base` stays the **default base**, the integration
branch, exactly as before. A new key, `branchModel.bases`, maps a branch name or glob to that
branch's base:

```json
{
  "branchModel": {
    "base": "develop",
    "bases": {
      "epic/search": "develop",
      "search/*": "epic/search"
    }
  }
}
```

A base the map picks has a base of its own, looked up the same way, up to the default base: a
**chain**, here `search/ranking → epic/search → develop`. Everything that used the one `<base>`
now uses the branch's own base: the freshness check and its two checkpoints, the rebase steps, the
PR target, stacked phases, `pr-later`, and the text of the spec and the PR. With no map, every
branch's base is the default base and nothing behaves differently. Which base a branch got, and
why, goes in the run log.

## Context

Ceryce's request, paraphrased: Zethus should support a base per branch as well as a default base.
Teams that work with a long-term branch also have shorter-lived branches off it, which still live
longer than a day or two. Those need keeping in sync with the long-term branch, and the long-term
branch in turn needs keeping in sync with the integration branch.

Zethus had one `<base>` for every branch. A child of a long-term branch was measured against the
integration branch, so the checks were wrong in both directions:

- **The wrong branch was called stale.** The child went STALE whenever the integration branch
  moved, which says nothing about the child, and the rebase the STALE line called for would have
  replayed the whole long-term branch's work onto the integration branch under the child's name.
- **The right one wasn't.** When the long-term branch moved, which is what the child actually has
  to keep up with, nothing noticed.
- **The PR targeted the wrong branch** and its diff held every commit of the long-term branch.

## How it works now

### Which base a branch gets

`base-freshness.py` resolves it from the current branch's name, and `--base-for <branch>` resolves
it for a branch that doesn't exist yet. Most specific first:

| # | Source | Example |
|---|---|---|
| 1 | `--base` on the command line, outright. No map, no chain | `--base release/2.4` |
| 2 | An exact `branchModel.bases` entry for the branch | `"epic/search": "develop"` |
| 3 | The `branchModel.bases` glob with the most literal characters. A tie between two that name different bases is a usage error (exit 2), never a guess | `"search/*"` beats `"*"` |
| 4 | `branchModel.base`, the default base | `"develop"` |
| 5 | `develop` if `origin/develop` exists, else the remote's default branch | |

Globs follow `fnmatch` rules, as `docSync.map` does, so `*` also matches `/`. An entry that would
make a branch its own base is skipped. The default base is the top of every chain, so the map is
never consulted for it, and naming it as a key is a usage error, as are a cycle and a base that is
itself a glob. The report names the base and why (`why branchModel.bases['search/*'] (glob)`), and
for a chain of more than one link it prints the chain and what the PR targets.

### Where each piece uses it

| Piece | Uses the branch's own base for |
|---|---|
| `base-freshness` | The count in `HEAD..origin/<base>`, the merge-base, and the STALE plan |
| The two checkpoints | Unchanged: Stage 0 and the pre-push gates, once each per change. A child is gated against its parent, the parent against the integration branch when the parent is the branch being worked on. `--base-for`, like `--merge-base-only`, never gates |
| Stage 0 | What a new branch is cut from: `--base-for <name>` before cutting it |
| Rebase steps | `git rebase origin/<base>` is the branch's base, in every style ([pre-push-gates](../skills/pre-push-gates/SKILL.md#bring-a-stale-branch-up-to-date)) |
| PR target | The branch's base; a stacked phase still targets the previous phase's branch, and its freshness is still measured against the base |
| `pr-later` | The one PR, when the person says to open it, targets the branch's base |
| Spec and PR text | The base named in a PR body, a rebase note, or an *As built* list is the branch's own |

### When the parent moves

Freshness is always measured against the parent's **current tip**, as just fetched. A parent that
gained commits makes the child STALE at the next checkpoint, and the child is rebased onto
`origin/<parent>` like any stale branch.

A parent that was **rewritten**, rebased onto its own base and force-pushed, needs more care: a
plain `git rebase origin/<parent>` would replay the parent's old commits under the child. The
script finds that case with `git merge-base --fork-point` (the reflog of `origin/<parent>` still
holds the old tip) and prints an `onto` line, so the child replays only its own commits:
`git rebase --onto origin/<parent> <fork point>`.

### When the parent merges

When the parent has merged, the child's base moves up a link, to the parent's base. The script
prints `RETARGET` and measures the child against the new base. The parent counts as merged when:

- it is **gone from the remote**: `git ls-remote` after the fetch no longer lists it (a squash or
  rebase merge, then the branch deleted). The STALE plan then uses `--onto` with the last commit
  of the old parent the child holds, so a squash merge doesn't bring the parent's commits back;
- or it has **merged into its own base with a merge commit**: it is an ancestor of its base, but
  not on its base's first-parent line.

The report says to retarget the PR (`gh pr edit --base <new base>`; in `pr-later`, note it in the
spec), rebase onto the new base, and remove the map entry once no branch needs it. A base that is
missing from the remote looks the same whether it merged and was deleted or was mistyped in the
map, so the `RETARGET` line names both. The check then runs against the next base up, which is
stricter, rather than against a branch that isn't there. A
fast-forward merge is not told apart from a parent with no commits of its own, so the child keeps
its base until the parent is deleted.

### When the parent is behind its own base

The `parent` line says so, at the child's checkpoints, and it doesn't gate the child. Rebasing the
child can't fix it, and fixing it means rewriting or merging into a branch that this change isn't
on and that other branches may be built on. The agent names it in its report and the PR body, and
the parent is brought up to date at its own checkpoints, the next time work happens on it, or now
if the person says so ([keep a chain of bases in sync](../skills/pre-push-gates/SKILL.md#keep-a-chain-of-bases-in-sync)).

### Where the key may live

Anywhere the other keys may: the committed `.github/zethus.config.json` for a team's shared chain,
`$ZETHUS_CONFIG`, the repo's untracked `.copilot/zethus.config.json`, Amphion's config, or the
user-level `~/.copilot/zethus/config.json`. The first file found wins whole, as for every key
except `identity`, so the map is never merged across files.

### The run log

Every run of `base-freshness` writes, line by line, to `~/.copilot/zethus/logs/base-freshness.log`
(`--log`, `$ZETHUS_BASE_LOG`, `off`): the config it started with, each map entry tried and whether
it matched, the base chosen and why, every link of the chain, each retarget and fork-point check
with what it found, the counts, the verdict and the exit code, and the traceback of anything
unexpected. It holds branch names and commit ids, nothing personal.

### Choices made inside the ask

- **An exact name beats any glob, and a glob's specificity is its literal characters.** It is easy
  to predict from the config alone, and a tie is reported rather than settled by file order.
- **The parent's own staleness is reported, not gated** (option D below, declined).
- **`--base-for` is a new mode, never a gate,** so Stage 0 can learn what to cut a branch from
  without a third freshness call.
- **`git ls-remote` runs only for a base below the default**, and only after a fetch that worked,
  so a repo with no map makes no extra network call.
- **The fork-point check runs for every base**, the default included. A rewritten integration
  branch is rare, but the same `--onto` is the right answer there too, and the exit code is
  unchanged.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — `branchModel.bases`, name or glob to base, resolved into a chain | The table above | One more key and a resolver; globs need a tie rule | **Chosen** |
| B — infer the base from git: the upstream, or the nearest branch the child forked from | No config | A guess, and a different one after every rebase; the kit's rule is config, then repo evidence, then ask, never a silent guess | Declined |
| C — per-branch git config (`branch.<name>.zethusBase`) | No shared file | Invisible to the team and lost with the clone; a long-term branch's children are made by several people | Declined |
| D — gate the whole chain: the child is STALE when its parent is behind the integration branch | Every link always fresh | The child's checkpoint would have to rewrite or merge into the parent, a branch other work is built on, from a session that isn't working on it | Declined |

## Consequences

- **Easier:** a long-term-branch workflow works without workarounds: the child is kept fresh
  against the parent, the parent against the integration branch, and each PR targets the branch it
  will merge into.
- **Harder:** a chain can go out of date as branches merge; `RETARGET` catches it at the next
  checkpoint, and the map entry then wants removing.
- **New obligations:** no doc, skill or script may assume the integration branch is the base of
  every branch; it says "the branch's base". `tests/test_zethus_per_branch_bases.py` pins the
  resolver, the chain, the parent that moves, is rewritten, merges or is deleted, the run log, the
  config locations, and the wording in the agent, the skills, the working agreement and the README.

## Revisit when

A chain's parents drift because no session ever works on them, so the `parent` line is seen but
never acted on: then gating the chain (option D) or a scheduled sync becomes worth its cost. Or a
forge makes the PR's base visible to the check directly, which would let `RETARGET` read it instead
of inferring it from the branch.
