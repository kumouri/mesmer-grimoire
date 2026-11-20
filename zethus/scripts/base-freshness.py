#!/usr/bin/env python3
"""Check that the current branch is not behind its base, at the two points it costs.

A stale base fails quietly. Every diff, measurement and research note taken on it compares
*branch drift* against the base instead of the change itself, and a PR cut from it can revert work
that already landed. Nothing about a stale checkout looks different from a fresh one, so this
script asks git instead of trusting the checkout:

1. ``git fetch <remote>`` (skip with ``--no-fetch``; the report then says it wasn't fetched);
2. pick the branch's base (below), and count the commits in ``HEAD..<remote>/<base>``: commits
   on the base that this branch lacks;
3. compare that with ``branchModel.maxBehind`` (default ``0``: any commit behind is stale).

**Which base.** ``--base`` names it outright. Otherwise the current branch's name picks it:

1. ``branchModel.bases``, a map of branch name or glob to base. An exact name beats every glob;
   among globs the one with the most literal characters wins (``search/*`` beats ``*``), and a tie
   between the best two is a usage error, never a guess. Globs use ``fnmatch`` rules, so ``*``
   also matches ``/``. An entry that would make a branch its own base is skipped.
2. ``branchModel.base``, the **default base**: the integration branch.
3. ``develop`` if ``<remote>/develop`` exists, else the remote's default branch.

A base the map picked has a base of its own, looked up the same way, up to the default base: the
**chain**, e.g. ``search/x → epic/search → develop``. The default base is the top of every chain;
the map is never consulted for it, and naming it as a key is a usage error. With no map the chain
is one link, and every result and exit code is what it was before the map existed. The decision
record is ``docs/per-branch-bases.md``.

**Each branch is gated against its own base only:** a child against its long-lived parent's
*current tip*, as fetched now; the parent against the integration branch when the parent is the
branch being checked. The parent is the child's base, so the fetch that finds the parent moved is
the one that finds the child stale. Three things about the links above are reported as well:

- **The parent is behind its own base** (the ``parent`` line). Not gated here, since rebasing the
  child can't fix it; it is synced at the parent's own checkpoints, or now if the person says so
  (pre-push-gates: *Keep a chain of bases in sync*).
- **The parent was rewritten** since this branch forked from it (it was rebased onto its own base):
  found with ``git merge-base --fork-point``. The STALE plan then replays only this branch's own
  commits, ``git rebase --onto <remote>/<parent> <fork point>``, so the parent's old commits don't
  come back.
- **The parent has merged, so the branch moves up a link** (``RETARGET``): when the parent is gone
  from the remote (``git ls-remote`` after the fetch), or has merged into its own base with a merge
  commit, the branch's base becomes the parent's base, and so on up the chain. The report says to
  retarget the PR and rebase onto the new base. A fast-forward merge is not told apart from a
  parent with no commits of its own; a squash or rebase merge is seen once the branch is deleted.

The report names the **merge-base**, the commit every diff, research note and PR body should be
taken against, and whether the branch was rewritten since it was last pushed (a rebase: the PR body
must say so). Neither affects the exit code.

``branchModel.style`` is ``"branch-per-change"`` (default: a new branch per change, cut from the
freshly fetched base), ``"rebase"`` (one long-lived branch, kept rebased onto the base) or
``"pr-later"`` (one working branch kept rebased onto the base, with no PR open yet; see
``docs/phase-advance-without-pr.md``). Every style runs the same check; only the steps for catching
up differ, and a ``pr-later`` branch has no PR body to note a rebase in, so the spec records it.

**A STALE result is not handed to a person.** The agent that runs this brings the branch up to date
itself and carries on, so the STALE line says what it is about to do, not what someone should do:
rebase onto ``<remote>/<base>``, resolve any conflicts, re-run this check, re-run the gates if work
was already written, and push a rewritten branch with ``--force-with-lease``. The full procedure is
"Bring a stale branch up to date" in ``skills/pre-push-gates/SKILL.md``. Only a failed fetch (exit
3), or a conflict the spec and the diff can't settle, stops the work, and a failed fetch only once
the agent has retried and diagnosed it and what's left is access only the person holds ("When the
fetch fails", same skill). The NO ANSWER line says that, too.

**The gate runs at two points, not at every stage:** Stage 0 (Orient), so the branch is cut from
or rebased onto a fresh base, and ``pre-push-gates``, so the pushed diff and the PR are against
the current base. Nothing in between re-runs it. A stage that needs only the **merge-base** to
diff against asks for it with ``--merge-base-only``: that mode prints the merge-base and exits 0
whatever the branch's freshness, so it can never stop a stage. ``--base-for BRANCH`` prints the
base a branch of that name gets, and its chain, and exits 0 too: Stage 0 uses it to know what to
cut a new branch from, and what its PR targets.

**The run log.** Every run writes which base was chosen for which branch and why: the config it
started with, each map entry tried and whether it matched, the winner, every link of the chain,
each retarget and rewritten-parent check with its evidence, the counts, the verdict and the exit
code, and the full traceback of anything unexpected. Each line is flushed as it is written, and
carries the run's id. The log is ``~/.copilot/zethus/logs/base-freshness.log`` unless ``--log`` or
``$ZETHUS_BASE_LOG`` names another; ``off`` turns it off. It holds branch names and commit ids,
nothing personal.

Exit codes: 0 fresh (behind <= maxBehind) · 1 stale: the agent rebases before anything else ·
2 usage error (not a git repo, bad config, base not found) · 3 no answer: the fetch failed, so
freshness is unknown and must not be assumed. With ``--merge-base-only`` or ``--base-for`` the only
non-zero code is 2: there is no gate to fail, and a failed fetch falls back to the last one.
"""
from __future__ import annotations

import argparse
import fnmatch
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (RunLog, UsageError, cfg, find_repo_root, git, load_config, rel,  # noqa: E402
                     run_log_path)

STYLES = ("branch-per-change", "rebase", "pr-later")
DEFAULT_STYLE = "branch-per-change"
LOG_ENV = "ZETHUS_BASE_LOG"
LOG_NAME = "base-freshness.log"
MAX_CHAIN = 10          # links; a longer chain is a config mistake, not a branch model
_GLOB_RE = re.compile(r"\[[^\]]*\]|[*?]")


def _quiet(_message: str) -> None:
    """The log for callers that pass none."""


@dataclass
class Link:
    """One link of a chain: ``branch``'s base is ``base``, for the reason ``why``."""
    branch: str
    base: str
    why: str


@dataclass
class BaseChoice:
    """The base a branch gets, the chain above it, and any link skipped because it merged."""
    branch: str                      # the branch the choice is for ("" when HEAD is detached)
    base: str                        # the base it is gated against, after any retarget
    why: str                         # why that base, in one line
    chain: list[Link]                # the configured links, branch first, ending at the default
    default: str                     # the default base: the top of every chain
    retargets: list[str] = field(default_factory=list)   # links skipped: "x has merged into y"
    onto: str | None = None          # replay only commits after this (a parent that merged away)

    @property
    def names(self) -> list[str]:
        return [self.chain[0].branch or "HEAD"] + [link.base for link in self.chain]


@dataclass
class Freshness:
    style: str
    base: str            # e.g. "develop"
    ref: str             # e.g. "origin/develop"
    behind: int
    ahead: int
    max_behind: int
    merge_base: str
    upstream: str | None             # e.g. "origin/feature/x", when HEAD tracks one
    rewritten: bool | None           # upstream not contained in HEAD: a force-push is needed
    why: str = ""                    # why this base (see BaseChoice.why)
    chain: list[str] = field(default_factory=list)       # branch → base → … → default
    retargets: list[str] = field(default_factory=list)
    parents: list[str] = field(default_factory=list)     # "origin/p is n behind origin/q"
    onto: str | None = None          # rebase --onto <ref> <this>: replay only this branch's commits
    onto_why: str = ""               # what made a plain rebase wrong (rewritten or merged parent)

    @property
    def stale(self) -> bool:
        return self.behind > self.max_behind


def _git_out(repo: Path, *args: str) -> str | None:
    """Stripped stdout of a successful git command, else ``None``."""
    proc = git(repo, *args)
    if proc is None or proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _ref_exists(repo: Path, ref: str) -> bool:
    return _git_out(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}") is not None


def _is_ancestor(repo: Path, older: str, newer: str) -> bool:
    proc = git(repo, "merge-base", "--is-ancestor", older, newer)
    return proc is not None and proc.returncode == 0


def branch_model(config: dict) -> tuple[str, int]:
    """``(style, maxBehind)`` from config, validated."""
    style = cfg(config, "branchModel.style", DEFAULT_STYLE)
    if style not in STYLES:
        raise UsageError(f"branchModel.style must be one of {', '.join(STYLES)}; got {style!r}")
    max_behind = cfg(config, "branchModel.maxBehind", 0)
    if isinstance(max_behind, bool) or not isinstance(max_behind, int) or max_behind < 0:
        raise UsageError(f"branchModel.maxBehind must be a whole number >= 0; got {max_behind!r}")
    bases_map(config)
    return style, max_behind


def bases_map(config: dict) -> dict[str, str]:
    """``branchModel.bases``, validated: branch name or glob -> base branch name."""
    bases = cfg(config, "branchModel.bases", {})
    if bases is None:
        return {}
    if not isinstance(bases, dict):
        raise UsageError("branchModel.bases must be an object mapping a branch name or glob to its "
                         f"base; got {type(bases).__name__}")
    for key, value in bases.items():
        if not key.strip() or not isinstance(value, str) or not value.strip():
            raise UsageError("every branchModel.bases entry maps a non-empty branch name or glob "
                             f"to a non-empty base branch name; got {key!r}: {value!r}")
        if _GLOB_RE.search(value):
            raise UsageError(f"branchModel.bases[{key!r}] is {value!r}: a base is one branch, "
                             "not a glob")
    return {k.strip(): v.strip() for k, v in bases.items()}


def _literal(pattern: str) -> int:
    """How specific a glob is: its characters that aren't wildcards."""
    return len(_GLOB_RE.sub("", pattern))


def match_base(branch: str, bases: dict[str, str], log=_quiet) -> tuple[str, str] | None:
    """``(base, why)`` from the map for ``branch``, most specific entry first; ``None`` if none."""
    if branch in bases and bases[branch] != branch:
        log(f"  bases: {branch!r} is an exact entry -> {bases[branch]!r}")
        return bases[branch], f"branchModel.bases[{branch!r}] (exact name)"
    hits = []
    for pattern, base in bases.items():
        if not _GLOB_RE.search(pattern):
            continue
        if not fnmatch.fnmatchcase(branch, pattern):
            log(f"  bases: {pattern!r} doesn't match {branch!r}")
            continue
        if base == branch:
            log(f"  bases: {pattern!r} matches {branch!r} but names it as its own base: skipped")
            continue
        log(f"  bases: {pattern!r} matches {branch!r} -> {base!r} ({_literal(pattern)} literal "
            "characters)")
        hits.append((_literal(pattern), pattern, base))
    if not hits:
        return None
    hits.sort(key=lambda h: -h[0])
    if len(hits) > 1 and hits[0][0] == hits[1][0] and hits[0][2] != hits[1][2]:
        raise UsageError(f"branch {branch!r} matches branchModel.bases {hits[0][1]!r} and "
                         f"{hits[1][1]!r} equally ({hits[0][0]} literal characters each), and they "
                         "name different bases. Add an exact entry for it, or make one glob more "
                         "specific.")
    score, pattern, base = hits[0]
    others = f", most specific of {len(hits)} matches" if len(hits) > 1 else ""
    return base, f"branchModel.bases[{pattern!r}] (glob{others})"


def resolve_base(repo: Path, remote: str, explicit: str | None) -> str:
    """The default base's name: explicit, else ``develop``, else the remote's default."""
    if explicit:
        if not _ref_exists(repo, f"{remote}/{explicit}"):
            raise UsageError(f"{remote}/{explicit} does not exist (is the base branch right?)")
        return explicit
    if _ref_exists(repo, f"{remote}/develop"):
        return "develop"
    head = _git_out(repo, "symbolic-ref", "--quiet", "--short", f"refs/remotes/{remote}/HEAD")
    if head and head.startswith(remote + "/"):
        return head[len(remote) + 1:]
    raise UsageError(f"can't tell the integration branch: no {remote}/develop and no "
                     f"{remote}/HEAD. Set branchModel.base, or pass --base.")


def _default_why(configured: str | None, remote: str, default: str) -> str:
    if configured:
        return "branchModel.base (the default base)"
    if default == "develop":
        return f"the default base: {remote}/develop exists (branchModel.base not set)"
    return f"the default base: {remote}/HEAD (no {remote}/develop, branchModel.base not set)"


def chain_for(branch: str, default: str, default_why: str, bases: dict[str, str],
              log=_quiet) -> list[Link]:
    """Every link from ``branch`` up to the default base, as configured."""
    if default in bases:
        raise UsageError(f"branchModel.bases names the default base {default!r} as a key: the "
                         "default base is the top of every chain. Change branchModel.base instead.")
    links: list[Link] = []
    seen = [branch]
    name = branch
    for _ in range(MAX_CHAIN):
        hit = match_base(name, bases, log) if name and name != default else None
        base, why = hit if hit else (default, default_why)
        log(f"  link: {name or 'HEAD (detached)'} -> {base} because {why}")
        links.append(Link(name, base, why))
        if base == default:
            return links
        if base in seen:
            raise UsageError("branchModel.bases has a cycle: " + " -> ".join(seen + [base]))
        seen.append(base)
        name = base
    raise UsageError(f"branchModel.bases chain from {branch!r} is longer than {MAX_CHAIN} links: "
                     + " -> ".join(seen))


def _on_remote(repo: Path, remote: str, branch: str, log) -> bool | None:
    """Whether the remote still has ``branch`` (``git ls-remote``); ``None`` if it can't say."""
    proc = git(repo, "ls-remote", "--exit-code", "--heads", remote, f"refs/heads/{branch}")
    if proc is None or proc.returncode not in (0, 2):
        detail = "git not found" if proc is None else (proc.stderr.strip().splitlines() or
                                                       [f"exit {proc.returncode}"])[-1]
        log(f"  retarget: ls-remote {remote} {branch} gave no answer ({detail}): not checked")
        return None
    return proc.returncode == 0


def _merged_into(repo: Path, ref: str, into: str) -> bool:
    """``ref`` came into ``into`` through a merge: an ancestor, but not on its first-parent line.

    A branch cut from ``into`` with no commits of its own is on that line, so a parent that was
    only just cut is not mistaken for one that has merged."""
    if not _is_ancestor(repo, ref, into):
        return False
    sha = _git_out(repo, "rev-parse", ref + "^{commit}")
    walk = _git_out(repo, "rev-list", "--first-parent", "--parents", f"{ref}..{into}")
    if not walk or not sha:
        return False
    last = walk.splitlines()[-1].split()
    return len(last) < 2 or last[1] != sha


def choose_base(repo: Path, remote: str, config: dict, branch: str, *, online: bool,
                log=_quiet) -> BaseChoice:
    """The base for ``branch``: the map, then the default, then up the chain past merged parents."""
    configured = cfg(config, "branchModel.base")
    default = resolve_base(repo, remote, configured)
    bases = bases_map(config)
    log(f"  default base {default} ({_default_why(configured, remote, default)}); "
        f"{len(bases)} branchModel.bases entr{'y' if len(bases) == 1 else 'ies'}"
        + (": " + ", ".join(f"{k!r}->{v!r}" for k, v in bases.items()) if bases else ""))
    if not branch:
        log("  HEAD is detached: no branch name to match branchModel.bases, so the default base")
    chain = chain_for(branch, default, _default_why(configured, remote, default), bases, log)
    choice = BaseChoice(branch, chain[0].base, chain[0].why, chain, default)
    if branch and chain[0].base == default and bases:
        choice.why += f" (no branchModel.bases entry matches {branch})"

    for i, link in enumerate(chain[:-1]):          # every base below the default
        parent, above = link.base, chain[i + 1].base
        ref = f"{remote}/{parent}"
        here = _ref_exists(repo, ref)
        gone = None if here else True
        if here and online:
            present = _on_remote(repo, remote, parent, log)
            gone = None if present is None else not present
        if gone:
            if here:
                choice.onto = _git_out(repo, "merge-base", "HEAD", ref) if branch else None
            reason = (f"{parent} is gone from {remote} (merged and deleted, or a name that "
                      "doesn't exist: check branchModel.bases)")
        elif here and _merged_into(repo, ref, f"{remote}/{above}"):
            reason = f"{parent} has merged into {above}"
        else:
            log(f"  retarget: {ref} is live (on the remote, not merged into {above}): keep it")
            break
        log(f"  retarget: {reason} -> moving up to {above}")
        choice.retargets.append(reason)
        choice.base = above
        choice.why = f"{link.why}, retargeted up the chain to {above}: {reason}"
    if not _ref_exists(repo, f"{remote}/{choice.base}"):
        raise UsageError(f"{remote}/{choice.base} does not exist (the base from {choice.why})")
    log(f"  chosen: {branch or 'HEAD'} -> {choice.base} because {choice.why}")
    return choice


def _parents(repo: Path, remote: str, choice: BaseChoice, log) -> list[str]:
    """How far each link above the chosen base is behind its own base. Reported, never gated."""
    lines = []
    names = [link.base for link in choice.chain]
    start = names.index(choice.base)
    for lower, upper in zip(names[start:], names[start + 1:]):
        count = _git_out(repo, "rev-list", "--count", f"{remote}/{lower}..{remote}/{upper}")
        log(f"  parent: {remote}/{lower} is {count or '?'} commit(s) behind {remote}/{upper}")
        if count and int(count) > 0:
            lines.append(f"{remote}/{lower} is {count} commit(s) behind its base {remote}/{upper}")
    return lines


def current_branch(repo: Path) -> str:
    """The checked-out branch's short name, or ``""`` when HEAD is detached."""
    return _git_out(repo, "symbolic-ref", "--quiet", "--short", "HEAD") or ""


def check(repo: Path, config: dict, *, remote: str = "origin", base: str | None = None,
          max_behind: int | None = None, online: bool = False, log=_quiet) -> Freshness:
    """Measure freshness against the branch's base. Doesn't fetch; ``main`` does that."""
    if _git_out(repo, "rev-parse", "--git-dir") is None:
        raise UsageError("not a git repository (or git is not installed)")
    style, cfg_max = branch_model(config)
    if max_behind is not None and max_behind < 0:
        raise UsageError("--max-behind must be >= 0")
    branch = current_branch(repo)
    log(f"check: branch {branch or 'HEAD (detached)'} style={style} maxBehind="
        f"{cfg_max if max_behind is None else max_behind}"
        + ("" if max_behind is None else " (--max-behind)"))
    if base:
        resolve_base(repo, remote, base)
        choice = BaseChoice(branch, base, "--base", [Link(branch, base, "--base")], base)
        log(f"  chosen: {branch or 'HEAD'} -> {base} because --base (the map and chain not used)")
    else:
        choice = choose_base(repo, remote, config, branch, online=online, log=log)
    ref = f"{remote}/{choice.base}"
    counts = _git_out(repo, "rev-list", "--left-right", "--count", f"HEAD...{ref}")
    if counts is None:
        raise UsageError(f"can't compare HEAD with {ref} (no commits yet?)")
    ahead, behind = (int(n) for n in counts.split())
    merge_base = _git_out(repo, "merge-base", "HEAD", ref) or ""

    onto, onto_why = choice.onto, ""
    if onto:
        onto_why = f"its old base {choice.chain[0].base} merged away"
    else:
        fork = _git_out(repo, "merge-base", "--fork-point", ref, "HEAD")
        if fork and fork != merge_base and not _is_ancestor(repo, fork, ref):
            onto, onto_why = fork, f"{ref} was rewritten since this branch forked from it"
        log(f"  fork point with {ref}: {(fork or 'none (no reflog)')[:12]}"
            + (" — rewritten since this branch forked from it" if onto else ""))

    upstream = _git_out(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    rewritten = None
    if upstream and upstream != ref:
        proc = git(repo, "merge-base", "--is-ancestor", upstream, "HEAD")
        rewritten = None if proc is None else proc.returncode == 1
    else:
        upstream = None
    result = Freshness(style, choice.base, ref, behind, ahead,
                       cfg_max if max_behind is None else max_behind,
                       merge_base, upstream, rewritten, why=choice.why, chain=choice.names,
                       retargets=choice.retargets, parents=_parents(repo, remote, choice, log),
                       onto=onto, onto_why=onto_why)
    log(f"  counts: behind {behind} ahead {ahead} merge-base {merge_base[:12] or 'none'} "
        f"upstream {upstream or 'none'} rewritten {rewritten}")
    return result


def _chain_lines(f: Freshness) -> list[str]:
    lines = [f"  why      {f.why}"] if f.why else []
    if len(f.chain) > 2 or f.retargets:
        lines.append("  chain    " + " → ".join(f.chain))
        lines.append(f"  PR into  {f.base} (a stacked phase: the previous phase's branch)")
    return lines


def report(f: Freshness, fetched: bool) -> list[str]:
    lines = [
        f"base freshness · style {f.style} · base {f.ref}"
        + ("" if fetched else " (NOT fetched: as of the last fetch)"),
        *_chain_lines(f),
        f"  behind   {f.behind} commit(s) in HEAD..{f.ref} (allowed: {f.max_behind})",
        f"  ahead    {f.ahead} commit(s) of your own",
        f"  diff base (merge-base) {f.merge_base[:12] or 'none'}"
        f" — diff, research and PR bodies against this, e.g. git diff {f.ref}...HEAD",
    ]
    if f.upstream is not None:
        where = ("the spec's As built list (no PR is open)" if f.style == "pr-later"
                 else "the PR")
        state = (f"rewritten since the last push: push with --force-with-lease and say in {where} "
                 "that it was rebased" if f.rewritten else "contained in HEAD")
        lines.append(f"  upstream {f.upstream} — {state}")
    for parent in f.parents:
        lines.append(f"  parent   {parent} — not gated here: rebasing this branch can't fix it. "
                     "Say so in the report and PR body; it is synced at its own checkpoints, or now "
                     "if the person says so (pre-push-gates: Keep a chain of bases in sync).")
    for reason in f.retargets:
        pr = ("note the new base in the spec's As built list (no PR is open)"
              if f.style == "pr-later" else f"retarget the PR to it (gh pr edit --base {f.base})")
        lines.append(f"RETARGET — {reason}, so this branch's base is now {f.ref}: {pr}, rebase "
                     f"onto it whenever it is behind (below), and remove the branchModel.bases "
                     "entry once no branch needs it.")
    if f.onto and f.stale:
        lines.append(f"  onto     {f.onto_why}: replay only this branch's own commits, "
                     f"git rebase --onto {f.ref} {f.onto[:12]}")
    if f.stale:
        lines.extend(stale_plan(f))
    else:
        lines.append(f"FRESH — HEAD is within {f.max_behind} commit(s) of {f.ref}.")
    return lines


def stale_plan(f: Freshness) -> list[str]:
    """What the agent does next about a stale branch: it rebases it itself, then carries on."""
    rebase = f"git rebase --onto {f.ref} {f.onto[:12]}" if f.onto else f"git rebase {f.ref}"
    if f.style == "rebase":
        how = (f"{rebase} (--update-refs if branches are stacked on it), resolve any "
               f"conflicts, re-run the gates, then git push --force-with-lease and say in the PR "
               f"body that it was rebased")
    elif f.style == "pr-later":
        how = (f"{rebase} on the working branch, resolve any conflicts, re-run the gates, "
               f"then git push --force-with-lease if the branch was pushed; no PR is open, so note "
               f"the rebase in the spec's As built list, and open no PR for it")
    else:
        onto = f" with {rebase}" if f.onto else ""
        how = (f"rebase onto {f.ref}{onto} (a stack from its top with --update-refs), or cut a "
               f"fresh branch from it and move the work across; resolve any conflicts, re-run "
               f"base-freshness to confirm, and re-run the gates if work was already written")
    return [
        f"STALE — {f.behind} commit(s) behind {f.ref}. Bringing the branch up to date now, before "
        f"any other work: {how}.",
        "  then carry on. Stop only for a conflict the spec and the diff can't settle: name the "
        "hunk and why, with the rebase paused cleanly or aborted, never half-applied "
        "(pre-push-gates: Bring a stale branch up to date).",
    ]


def fetch_plan(remote: str) -> list[str]:
    """What the agent does next about a failed fetch: diagnose it itself, stop only for access."""
    return [
        "Freshness is unknown, so don't treat the base as fresh. Retrying and diagnosing it now: "
        f"fetch once more, then git remote -v and git ls-remote --heads {remote}; fix a wrong "
        "remote name (--remote) or base (branchModel.base, branchModel.bases) and re-run this "
        "check.",
        "  Stop only for what this machine can't supply (a missing or rejected credential, a VPN "
        "or proxy), and name that one thing and what was tried. --no-fetch is not a way round: "
        "the last fetch is not a fresh base (pre-push-gates: When the fetch fails).",
    ]


def merge_base_report(f: Freshness, fetched: bool) -> list[str]:
    """The merge-base alone, for a stage that needs a diff base and must not be gated."""
    return [
        f"diff base (merge-base) {f.merge_base[:12] or 'none'} — base {f.ref}"
        + ("" if fetched else " (NOT fetched: as of the last fetch)"),
        *_chain_lines(f),
        f"  diff, research and PR bodies against this, e.g. git diff {f.ref}...HEAD",
        f"  no gate: this is --merge-base-only ({f.behind} commit(s) behind; freshness is "
        f"checked at Stage 0 and before the push, not here).",
    ]


def base_for_report(choice: BaseChoice, remote: str, fetched: bool) -> list[str]:
    """The base a branch of this name gets: what to cut it from and what its PR targets."""
    lines = [f"base for {choice.branch}: {remote}/{choice.base}"
             + ("" if fetched else " (NOT fetched: as of the last fetch)"),
             f"  why      {choice.why}"]
    if len(choice.names) > 2 or choice.retargets:
        lines.append("  chain    " + " → ".join(choice.names))
    lines += [f"  cut it from {remote}/{choice.base} (a stacked phase: the previous phase's "
              f"branch); its PR targets {choice.base}",
              "  no gate: this is --base-for; freshness is checked at Stage 0 and before the push."]
    return lines


def _fetch_failure(proc) -> str:
    if proc is None:
        return "git not found"
    err = proc.stderr.strip().splitlines()
    return err[-1] if err else f"exit {proc.returncode}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="base-freshness",
                                description="Say whether the branch is behind its base, so the "
                                            "agent rebases it before any other work.")
    p.add_argument("--repo", help="repository root (default: nearest .git ancestor of cwd)")
    p.add_argument("--config", help="config file")
    p.add_argument("--remote", default="origin", help="remote holding the base (default: origin)")
    p.add_argument("--base", help="the base, outright (default: branchModel.bases for this "
                                  "branch, else branchModel.base, else develop, else the remote's "
                                  "default branch)")
    p.add_argument("--max-behind", type=int, help="override branchModel.maxBehind")
    p.add_argument("--no-fetch", action="store_true", help="don't fetch; check the last fetch")
    p.add_argument("--merge-base-only", action="store_true",
                   help="print the merge-base to diff against and exit 0 whatever the freshness; "
                        "never gates a stage (the gate is Stage 0 and pre-push-gates)")
    p.add_argument("--base-for", metavar="BRANCH",
                   help="print the base a branch of this name gets, and its chain, and exit 0: "
                        "what to cut it from and what its PR targets; never gates")
    p.add_argument("--log", help=f"run log path, or 'off' (default: ${LOG_ENV}, else "
                                 f"~/.copilot/zethus/logs/{LOG_NAME})")
    args = p.parse_args(argv)
    log = RunLog(run_log_path(args.log, LOG_ENV, LOG_NAME))
    try:
        code = _run(args, log)
    except Exception:
        log("base-freshness: unexpected error\n" + traceback.format_exc().rstrip())
        log.close()
        raise
    log(f"base-freshness: exit {code}")
    log.close()
    return code


def _run(args, log: RunLog) -> int:
    fetched = not args.no_fetch
    gated = not (args.merge_base_only or args.base_for)
    mode = "--base-for" if args.base_for else "--merge-base-only" if args.merge_base_only else "gate"
    log(f"base-freshness: start mode={mode} remote={args.remote} fetch={fetched} "
        f"base={args.base or '-'} max-behind={args.max_behind if args.max_behind is not None else '-'}")
    try:
        repo = Path(args.repo).resolve() if args.repo else find_repo_root()
        config, path = load_config(repo, args.config)
        log(f"  config: {rel(path, repo) if path else 'none (repository evidence only)'}")
        branch_model(config)                        # a bad config is a usage error, fetch or not
        if fetched:
            proc = git(repo, "fetch", "--quiet", args.remote)
            if proc is None or proc.returncode != 0:
                detail = _fetch_failure(proc)
                log(f"  fetch {args.remote} failed: {detail}")
                if not gated:
                    # No gate to fail: report as of the last fetch, and say so.
                    print(f"base-freshness: could not fetch {args.remote}: {detail} — the "
                          "answer below is as of the last fetch.")
                    fetched = False
                else:
                    print(f"base freshness: NO ANSWER — could not fetch {args.remote}: {detail}\n"
                          + "\n".join(fetch_plan(args.remote)))
                    return 3
            else:
                log(f"  fetch {args.remote}: ok")
        if args.base_for:
            log(f"base-for: branch {args.base_for}")
            if args.base:
                resolve_base(repo, args.remote, args.base)
                choice = BaseChoice(args.base_for, args.base, "--base",
                                    [Link(args.base_for, args.base, "--base")], args.base)
            else:
                choice = choose_base(repo, args.remote, config, args.base_for, online=fetched,
                                     log=log)
            print("\n".join(base_for_report(choice, args.remote, fetched)))
            return 0
        result = check(repo, config, remote=args.remote, base=args.base,
                       max_behind=args.max_behind, online=fetched, log=log)
    except UsageError as exc:
        log(f"  usage error: {exc}")
        print(f"base-freshness: {exc}", file=sys.stderr)
        return 2
    if args.merge_base_only:
        print("\n".join(merge_base_report(result, fetched=fetched)))
        return 0
    verdict = "STALE" if result.stale else "FRESH"
    log(f"  verdict: {verdict} ({result.behind} behind {result.ref}, allowed {result.max_behind})"
        + (f"; retargeted: {'; '.join(result.retargets)}" if result.retargets else ""))
    print("\n".join(report(result, fetched=fetched)))
    return 1 if result.stale else 0


if __name__ == "__main__":
    sys.exit(main())
