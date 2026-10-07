#!/usr/bin/env python3
"""Check that the current branch is not behind the integration branch, at the two points it costs.

A stale base fails quietly. Every diff, measurement and research note taken on it compares
*branch drift* against the base instead of the change itself, and a PR cut from it can revert work
that already landed. Nothing about a stale checkout looks different from a fresh one, so this
script asks git instead of trusting the checkout:

1. ``git fetch <remote>`` (skip with ``--no-fetch``; the report then says it wasn't fetched);
2. count the commits in ``HEAD..<remote>/<base>``: commits on the base that this branch lacks;
3. compare that with ``branchModel.maxBehind`` (default ``0``: any commit behind is stale).

The base is ``--base``, else ``branchModel.base``, else ``develop`` if ``<remote>/develop``
exists, else the remote's default branch. The report also names the **merge-base**, the commit
every diff, research note and PR body should be taken against, and whether the branch was
rewritten since it was last pushed (a rebase: the PR body must say so). Neither affects the exit
code.

``branchModel.style`` is ``"branch-per-change"`` (default: a new branch per change, cut from the
freshly fetched base) or ``"rebase"`` (one long-lived branch, kept rebased onto the base). Both
styles run the same check; only the advice on how to catch up differs.

**The gate runs at two points, not at every stage:** Stage 0 (Orient), so the branch is cut from
or rebased onto a fresh base, and ``pre-push-gates``, so the pushed diff and the PR are against
the current base. Nothing in between re-runs it. A stage that needs only the **merge-base** to
diff against asks for it with ``--merge-base-only``: that mode prints the merge-base and exits 0
whatever the branch's freshness, so it can never stop a stage.

Exit codes: 0 fresh (behind <= maxBehind) · 1 stale: rebase before doing anything else ·
2 usage error (not a git repo, bad config, base not found) · 3 no answer: the fetch failed, so
freshness is unknown and must not be assumed. With ``--merge-base-only`` the only non-zero code
is 2: there is no gate to fail, and a failed fetch falls back to the last one.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import UsageError, cfg, find_repo_root, git, load_config  # noqa: E402

STYLES = ("branch-per-change", "rebase")
DEFAULT_STYLE = "branch-per-change"


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


def branch_model(config: dict) -> tuple[str, int]:
    """``(style, maxBehind)`` from config, validated."""
    style = cfg(config, "branchModel.style", DEFAULT_STYLE)
    if style not in STYLES:
        raise UsageError(f"branchModel.style must be one of {', '.join(STYLES)}; got {style!r}")
    max_behind = cfg(config, "branchModel.maxBehind", 0)
    if isinstance(max_behind, bool) or not isinstance(max_behind, int) or max_behind < 0:
        raise UsageError(f"branchModel.maxBehind must be a whole number >= 0; got {max_behind!r}")
    return style, max_behind


def resolve_base(repo: Path, remote: str, explicit: str | None) -> str:
    """The integration branch name: explicit, else ``develop``, else the remote's default."""
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


def check(repo: Path, config: dict, *, remote: str = "origin", base: str | None = None,
          max_behind: int | None = None) -> Freshness:
    """Measure freshness against ``<remote>/<base>``. Doesn't fetch; ``main`` does that."""
    if _git_out(repo, "rev-parse", "--git-dir") is None:
        raise UsageError("not a git repository (or git is not installed)")
    style, cfg_max = branch_model(config)
    if max_behind is not None and max_behind < 0:
        raise UsageError("--max-behind must be >= 0")
    base = resolve_base(repo, remote, base or cfg(config, "branchModel.base"))
    ref = f"{remote}/{base}"
    counts = _git_out(repo, "rev-list", "--left-right", "--count", f"HEAD...{ref}")
    if counts is None:
        raise UsageError(f"can't compare HEAD with {ref} (no commits yet?)")
    ahead, behind = (int(n) for n in counts.split())
    merge_base = _git_out(repo, "merge-base", "HEAD", ref) or ""

    upstream = _git_out(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    rewritten = None
    if upstream and upstream != ref:
        proc = git(repo, "merge-base", "--is-ancestor", upstream, "HEAD")
        rewritten = None if proc is None else proc.returncode == 1
    else:
        upstream = None
    return Freshness(style, base, ref, behind, ahead,
                     cfg_max if max_behind is None else max_behind,
                     merge_base, upstream, rewritten)


def report(f: Freshness, fetched: bool) -> list[str]:
    lines = [
        f"base freshness · style {f.style} · base {f.ref}"
        + ("" if fetched else " (NOT fetched: as of the last fetch)"),
        f"  behind   {f.behind} commit(s) in HEAD..{f.ref} (allowed: {f.max_behind})",
        f"  ahead    {f.ahead} commit(s) of your own",
        f"  diff base (merge-base) {f.merge_base[:12] or 'none'}"
        f" — diff, research and PR bodies against this, e.g. git diff {f.ref}...HEAD",
    ]
    if f.upstream is not None:
        state = ("rewritten since the last push: push with --force-with-lease and say in the PR "
                 "that it was rebased" if f.rewritten else "contained in HEAD")
        lines.append(f"  upstream {f.upstream} — {state}")
    if f.stale:
        how = (f"git rebase {f.ref}, re-run the gates, then git push --force-with-lease"
               if f.style == "rebase" else
               f"rebase onto {f.ref}, or cut a fresh branch from it and move the work across")
        lines.append(f"STALE — {f.behind} commit(s) behind {f.ref}. Rebase before doing anything "
                     f"else: {how}.")
    else:
        lines.append(f"FRESH — HEAD is within {f.max_behind} commit(s) of {f.ref}.")
    return lines


def merge_base_report(f: Freshness, fetched: bool) -> list[str]:
    """The merge-base alone, for a stage that needs a diff base and must not be gated."""
    return [
        f"diff base (merge-base) {f.merge_base[:12] or 'none'} — base {f.ref}"
        + ("" if fetched else " (NOT fetched: as of the last fetch)"),
        f"  diff, research and PR bodies against this, e.g. git diff {f.ref}...HEAD",
        f"  no gate: this is --merge-base-only ({f.behind} commit(s) behind; freshness is "
        f"checked at Stage 0 and before the push, not here).",
    ]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="base-freshness",
                                description="Stop work on a branch that is behind its base.")
    p.add_argument("--repo", help="repository root (default: nearest .git ancestor of cwd)")
    p.add_argument("--config", help="config file")
    p.add_argument("--remote", default="origin", help="remote holding the base (default: origin)")
    p.add_argument("--base", help="integration branch (default: branchModel.base, else develop, "
                                  "else the remote's default branch)")
    p.add_argument("--max-behind", type=int, help="override branchModel.maxBehind")
    p.add_argument("--no-fetch", action="store_true", help="don't fetch; check the last fetch")
    p.add_argument("--merge-base-only", action="store_true",
                   help="print the merge-base to diff against and exit 0 whatever the freshness; "
                        "never gates a stage (the gate is Stage 0 and pre-push-gates)")
    args = p.parse_args(argv)
    fetched = not args.no_fetch
    try:
        repo = Path(args.repo).resolve() if args.repo else find_repo_root()
        config, _ = load_config(repo, args.config)
        branch_model(config)                        # a bad config is a usage error, fetch or not
        if fetched:
            proc = git(repo, "fetch", "--quiet", args.remote)
            if proc is None or proc.returncode != 0:
                if proc is None:
                    detail = "git not found"
                else:
                    err = proc.stderr.strip().splitlines()
                    detail = err[-1] if err else f"exit {proc.returncode}"
                if args.merge_base_only:
                    # No gate to fail: report the merge-base as of the last fetch, and say so.
                    print(f"base-freshness: could not fetch {args.remote}: {detail} — the "
                          "merge-base below is as of the last fetch.")
                    fetched = False
                else:
                    print(f"base freshness: NO ANSWER — could not fetch {args.remote}: {detail}\n"
                          "Freshness is unknown. Don't treat the base as fresh; fix the fetch, or "
                          "re-run with --no-fetch and say the result is as of the last fetch.")
                    return 3
        result = check(repo, config, remote=args.remote, base=args.base,
                       max_behind=args.max_behind)
    except UsageError as exc:
        print(f"base-freshness: {exc}", file=sys.stderr)
        return 2
    if args.merge_base_only:
        print("\n".join(merge_base_report(result, fetched=fetched)))
        return 0
    print("\n".join(report(result, fetched=fetched)))
    return 1 if result.stale else 0


if __name__ == "__main__":
    sys.exit(main())
