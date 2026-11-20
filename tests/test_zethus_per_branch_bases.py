"""Each branch has its own base: ``branchModel.base`` as the default, ``branchModel.bases`` per branch.

Ceryce's request, 2026-11-19 (paraphrased; ``zethus/docs/per-branch-bases.md``): support a base per
branch as well as a default base. In a long-term-branch workflow, shorter-lived branches that still
live more than a day or two have to stay in sync with the long-term branch, and the long-term
branch with the integration branch. Zethus had one ``<base>`` for every branch.

These tests pin the resolver (exact name, then the most specific glob, then the default), the
chain up to the default base, freshness of a child against its parent's current tip, a parent that
moves, is rewritten, merges with a merge commit, or is squash-merged and deleted, the parent's own
staleness reported without gating, ``--base-for``, the run log, the config locations, that nothing
changes without a map, and the wording in the agent, the skills, the working agreement and the
README. The git tests use a real bare origin, so fetch, ls-remote and the reflog run for real.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "zethus"
SCRIPT = KIT / "scripts" / "base-freshness.py"
CANONICAL = KIT / "com.github.copilot" / "agents" / "zethus.agent.md"
MIRROR = KIT / "agents" / "zethus.agent.md"
AGREEMENT = KIT / "copilot-instructions.md"
GATES = KIT / "skills" / "pre-push-gates" / "SKILL.md"
PR_SKILL = KIT / "skills" / "zethus-pr-description" / "SKILL.md"
IMPLEMENT = KIT / "skills" / "implement-phase" / "SKILL.md"
RECORD = KIT / "docs" / "per-branch-bases.md"
CADENCE = KIT / "docs" / "base-freshness-cadence.md"
README = KIT / "README.md"
EXAMPLE = KIT / "zethus.config.example.json"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                     # a dataclass looks its module up while it is built
    spec.loader.exec_module(mod)
    return mod


fresh = load("base_freshness_per_branch", SCRIPT)

CHAIN = {"epic/search": "develop", "search/*": "epic/search"}


def flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


class Resolver(unittest.TestCase):
    """The map alone: most specific entry first, and never a guess."""

    def test_an_exact_name_beats_every_glob(self):
        bases = {"search/*": "epic/search", "search/ranking": "develop", "*": "main"}
        self.assertEqual(fresh.match_base("search/ranking", bases)[0], "develop")
        self.assertIn("exact name", fresh.match_base("search/ranking", bases)[1])

    def test_the_glob_with_the_most_literal_characters_wins(self):
        bases = {"*": "main", "search/*": "epic/search", "search/rank*": "epic/rank"}
        self.assertEqual(fresh.match_base("search/ranking", bases)[0], "epic/rank")
        self.assertEqual(fresh.match_base("search/facets", bases)[0], "epic/search")
        self.assertEqual(fresh.match_base("hotfix/x", bases)[0], "main")
        self.assertIsNone(fresh.match_base("x", {"search/*": "epic/search"}))

    def test_star_matches_a_slash_as_fnmatch_does(self):
        self.assertEqual(fresh.match_base("search/a/b", {"search/*": "epic/search"})[0],
                         "epic/search")

    def test_a_tie_between_different_bases_is_an_error_not_a_guess(self):
        with self.assertRaises(fresh.UsageError) as ctx:
            fresh.match_base("search/ranking", {"search/*": "epic/search", "*h/ranki*": "develop"})
        self.assertIn("equally", str(ctx.exception))
        same = {"search/*": "epic/search", "*h/ranki*": "epic/search"}
        self.assertEqual(fresh.match_base("search/ranking", same)[0], "epic/search",
                         "a tie that names the same base is no ambiguity")

    def test_an_entry_that_makes_a_branch_its_own_base_is_skipped(self):
        bases = {"epic/*": "epic/search", "*": "develop"}
        self.assertEqual(fresh.match_base("epic/search", bases)[0], "develop")
        self.assertEqual(fresh.match_base("epic/other", bases)[0], "epic/search")

    def test_the_chain_runs_up_to_the_default_base(self):
        links = fresh.chain_for("search/ranking", "develop", "default", CHAIN)
        self.assertEqual([(l.branch, l.base) for l in links],
                         [("search/ranking", "epic/search"), ("epic/search", "develop")])
        self.assertEqual([(l.branch, l.base) for l in fresh.chain_for("x", "develop", "d", {})],
                         [("x", "develop")], "no map: one link to the default, as before")

    def test_bad_maps_are_usage_errors(self):
        for bad in ([], "develop", {"x": ""}, {"": "develop"}, {"x": 3}, {"x": "epic/*"}):
            with self.assertRaises(fresh.UsageError, msg=repr(bad)) as ctx:
                fresh.bases_map({"branchModel": {"bases": bad}})
            self.assertIn("branchModel.bases", str(ctx.exception))
        with self.assertRaises(fresh.UsageError) as ctx:
            fresh.chain_for("x", "develop", "d", {"develop": "main"})
        self.assertIn("default base", str(ctx.exception))
        loop = {"search/*": "epic/search", "epic/search": "search/loop"}
        with self.assertRaises(fresh.UsageError) as ctx:
            fresh.chain_for("search/ranking", "develop", "d", loop)
        self.assertIn("cycle", str(ctx.exception))

    def test_branch_model_validates_the_map_and_still_returns_style_and_tolerance(self):
        self.assertEqual(fresh.branch_model({"branchModel": {"bases": CHAIN}}),
                         ("branch-per-change", 0))
        with self.assertRaises(fresh.UsageError):
            fresh.branch_model({"branchModel": {"bases": ["develop"]}})


class Chain(unittest.TestCase):
    """origin has develop, a long-term epic/search cut from it, and the work clone's child of it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.home = root / "_home"
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home),
               "ZETHUS_IDENTITY_FORGE": "off"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for var in ("ZETHUS_CONFIG", "ZETHUS_BASE_LOG"):
            os.environ.pop(var, None)
        self.root = root
        self.origin, self.seed, self.work = root / "origin.git", root / "seed", root / "work"
        self.git(root, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(root, "clone", "-q", str(self.origin), str(self.seed))
        self.commit(self.seed, "a.txt", "init")
        self.git(self.seed, "push", "-q", "origin", "HEAD:main", "HEAD:develop")
        self.git(self.seed, "checkout", "-q", "-b", "epic/search", "origin/develop")
        self.commit(self.seed, "epic.txt", "epic work")
        self.git(self.seed, "push", "-q", "origin", "epic/search")
        self.git(root, "clone", "-q", str(self.origin), str(self.work))
        self.git(self.work, "checkout", "-q", "-b", "search/ranking", "origin/epic/search")
        self.commit(self.work, "mine.txt", "my change")
        self.set_config({"bases": CHAIN})

    # -- helpers ---------------------------------------------------------------------------------
    def git(self, where: Path, *args: str) -> str:
        return subprocess.run(["git", "-C", str(where), "-c", "user.name=t",
                               "-c", "user.email=t@example.com", "-c", "core.autocrlf=false",
                               *args], check=True, capture_output=True, text=True).stdout.strip()

    def commit(self, where: Path, name: str, text: str) -> None:
        (where / name).write_text(text + "\n", encoding="utf-8", newline="\n")
        self.git(where, "add", name)
        self.git(where, "commit", "-q", "-m", text)

    def land(self, branch: str, n: int) -> None:
        """Someone else pushes ``n`` commits to ``branch`` on the remote."""
        self.git(self.seed, "fetch", "-q", "origin")
        self.git(self.seed, "checkout", "-q", "-B", branch, f"origin/{branch}")
        for i in range(n):
            self.commit(self.seed, f"theirs-{branch.replace('/', '-')}-{i}-{os.urandom(3).hex()}.txt",
                        f"theirs {branch} {i}")
        self.git(self.seed, "push", "-q", "origin", branch)

    def set_config(self, branch_model: dict, where: str = ".copilot/zethus.config.json") -> None:
        path = self.work / where
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"branchModel": branch_model}), encoding="utf-8")
        exclude = self.work / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with open(exclude, "a", encoding="utf-8") as fh:
            fh.write(".copilot/\n.github/\n")

    def check(self, *argv: str) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = fresh.main(["--repo", str(self.work), *argv])
        return code, buf.getvalue()

    def rev(self, ref: str) -> str:
        return self.git(self.work, "rev-parse", ref)

    def own_commits(self, base_ref: str) -> int:
        return int(self.git(self.work, "rev-list", "--count", f"{base_ref}..HEAD"))

    # -- the chain -------------------------------------------------------------------------------
    def test_the_child_is_checked_against_its_long_lived_parent(self):
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("base origin/epic/search", out)
        self.assertIn("why      branchModel.bases['search/*'] (glob)", out)
        self.assertIn("chain    search/ranking → epic/search → develop", out)
        self.assertIn("PR into  epic/search", out)
        self.assertIn("ahead    1 commit(s)", out, "only the child's own commit, not the parent's")
        self.assertIn("FRESH — HEAD is within 0 commit(s) of origin/epic/search", out)

    def test_without_a_map_nothing_changes(self):
        self.set_config({})
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("base origin/develop", out)
        self.assertNotIn("chain", out)
        self.assertNotIn("parent", out)
        self.assertIn("ahead    2 commit(s)", out, "measured against develop, as before")
        self.set_config({"bases": {"other/*": "epic/search"}})
        code, out = self.check()
        self.assertIn("base origin/develop", out)
        self.assertIn("no branchModel.bases entry matches search/ranking", out)

    def test_the_parent_moving_makes_the_child_stale_against_its_current_tip(self):
        self.land("epic/search", 2)
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("STALE — 2 commit(s) behind origin/epic/search", out)
        self.assertIn("rebase onto origin/epic/search (a stack from its top", out)
        self.assertNotIn("onto     ", out, "the parent only gained commits: a plain rebase is right")
        self.git(self.work, "rebase", "-q", "origin/epic/search")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.own_commits("origin/epic/search"), 1)

    def test_the_integration_branch_moving_is_reported_on_the_child_but_not_gated(self):
        self.land("develop", 3)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("parent   origin/epic/search is 3 commit(s) behind its base origin/develop — "
                      "not gated here", out)
        self.assertIn("Keep a chain of bases in sync", out)
        self.assertIn("FRESH", out)

    def test_the_parent_is_gated_against_the_integration_branch(self):
        self.land("develop", 1)
        self.git(self.work, "checkout", "-q", "-B", "epic/search", "origin/epic/search")
        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("base origin/develop", out)
        self.assertIn("why      branchModel.bases['epic/search'] (exact name)", out)
        self.assertIn("STALE — 1 commit(s) behind origin/develop", out)

    def test_a_rewritten_parent_replays_only_the_childs_own_commits(self):
        old_parent = self.rev("origin/epic/search")
        self.land("develop", 1)
        self.git(self.seed, "checkout", "-q", "-B", "epic/search", "origin/epic/search")
        self.git(self.seed, "rebase", "-q", "origin/develop")
        self.git(self.seed, "push", "-q", "--force", "origin", "epic/search")

        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("onto     origin/epic/search was rewritten since this branch forked from it: "
                      "replay only this branch's own commits, git rebase --onto origin/epic/search "
                      f"{old_parent[:12]}", out)
        self.assertIn(f"with git rebase --onto origin/epic/search {old_parent[:12]}", out)

        self.git(self.work, "rebase", "-q", "--onto", "origin/epic/search", old_parent)
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.own_commits("origin/epic/search"), 1,
                         "the parent's old commit didn't come back")

    def test_a_parent_merged_with_a_merge_commit_retargets_the_child(self):
        self.git(self.seed, "fetch", "-q", "origin")
        self.git(self.seed, "checkout", "-q", "-B", "develop", "origin/develop")
        self.git(self.seed, "merge", "-q", "--no-ff", "-m", "merge epic", "origin/epic/search")
        self.git(self.seed, "push", "-q", "origin", "develop")
        log = self.root / "retarget.log"

        code, out = self.check("--log", str(log))
        self.assertEqual(code, 1, out)
        self.assertIn("base origin/develop", out)
        self.assertIn("RETARGET — epic/search has merged into develop, so this branch's base is now "
                      "origin/develop: retarget the PR to it (gh pr edit --base develop)", out)
        self.assertIn("chain    search/ranking → epic/search → develop", out)
        self.assertIn("PR into  develop", out)
        self.assertIn("retarget: epic/search has merged into develop -> moving up to develop",
                      log.read_text(encoding="utf-8"))

        self.git(self.work, "rebase", "-q", "origin/develop")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertEqual(self.own_commits("origin/develop"), 1)

    def test_a_parent_squash_merged_and_deleted_retargets_with_onto(self):
        old_parent = self.rev("origin/epic/search")
        self.git(self.seed, "fetch", "-q", "origin")
        self.git(self.seed, "checkout", "-q", "-B", "develop", "origin/develop")
        self.git(self.seed, "merge", "-q", "--squash", "origin/epic/search")
        self.git(self.seed, "commit", "-q", "-m", "epic work (squashed)")
        self.git(self.seed, "push", "-q", "origin", "develop", ":epic/search")

        code, out = self.check("--no-fetch")
        self.assertNotIn("RETARGET", out, "offline, a stale tracking ref can't show a deletion")

        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("RETARGET — epic/search is gone from origin (merged and deleted", out)
        self.assertIn("base origin/develop", out)
        self.assertIn(f"git rebase --onto origin/develop {old_parent[:12]}", out)

        self.git(self.work, "rebase", "-q", "--onto", "origin/develop", old_parent)
        self.assertEqual(self.own_commits("origin/develop"), 1, "the squashed commits stay squashed")

    def test_a_just_cut_parent_is_not_mistaken_for_a_merged_one(self):
        self.git(self.seed, "fetch", "-q", "origin")
        self.git(self.seed, "push", "-q", "origin", "origin/develop:refs/heads/epic/new")
        self.land("develop", 1)
        self.set_config({"bases": {"new/*": "epic/new", "epic/new": "develop"}})
        self.git(self.work, "fetch", "-q", "origin")
        self.git(self.work, "checkout", "-q", "-b", "new/x", "origin/epic/new")
        self.commit(self.work, "x.txt", "x")
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("base origin/epic/new", out)
        self.assertNotIn("RETARGET", out)
        self.assertIn("parent   origin/epic/new is 1 commit(s) behind its base origin/develop", out)

    def test_base_for_names_what_to_cut_a_new_branch_from_and_never_gates(self):
        self.land("epic/search", 3)
        code, out = self.check("--base-for", "search/facets")
        self.assertEqual(code, 0, out)
        self.assertIn("base for search/facets: origin/epic/search", out)
        self.assertIn("why      branchModel.bases['search/*'] (glob)", out)
        self.assertIn("cut it from origin/epic/search", out)
        self.assertIn("its PR targets epic/search", out)
        self.assertIn("no gate", out)
        self.assertNotIn("STALE", out)
        code, out = self.check("--base-for", "hotfix/x")
        self.assertIn("base for hotfix/x: origin/develop", out)
        self.git(self.work, "remote", "set-url", "origin", str(self.root / "gone.git"))
        code, out = self.check("--base-for", "search/facets")
        self.assertEqual(code, 0, f"a failed fetch falls back, as --merge-base-only does: {out}")
        self.assertIn("NOT fetched", out)

    def test_merge_base_only_uses_the_branchs_own_base(self):
        mb = self.git(self.work, "merge-base", "HEAD", "origin/epic/search")
        code, out = self.check("--merge-base-only")
        self.assertEqual(code, 0, out)
        self.assertIn(f"diff base (merge-base) {mb[:12]} — base origin/epic/search", out)

    def test_a_detached_head_uses_the_default_base(self):
        self.git(self.work, "checkout", "-q", "--detach")
        code, out = self.check()
        self.assertIn("base origin/develop", out)
        self.assertIn("default base", out)

    def test_a_bad_map_is_exit_2_before_any_fetch(self):
        cases = ({"bases": {"search/*": "epic/search", "*h/ranki*": "develop"}},
                 {"bases": {"search/*": "epic/search", "epic/search": "search/loop"}},
                 {"bases": {"search/*": "epic/*"}})
        for bad in cases:
            self.set_config(bad)
            code, out = self.check("--no-fetch")
            self.assertEqual(code, 2, (bad, out))
            self.assertIn("base-freshness:", out)

    def test_a_base_that_isnt_on_the_remote_moves_up_the_chain_and_says_why(self):
        # Merged and deleted, or a typo: the two look the same from here, so the check moves up
        # to the stricter base and names both causes, rather than gating on a branch that's gone.
        self.set_config({"bases": {"search/*": "no-such-branch"}})
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("base origin/develop", out)
        self.assertIn("RETARGET — no-such-branch is gone from origin (merged and deleted, or a name "
                      "that doesn't exist: check branchModel.bases)", out)

    def test_the_map_is_read_from_every_config_location(self):
        (self.work / ".copilot" / "zethus.config.json").unlink()
        user = self.home / ".copilot" / "zethus" / "config.json"
        user.parent.mkdir(parents=True)
        user.write_text(json.dumps({"branchModel": {"bases": CHAIN}}), encoding="utf-8")
        self.assertIn("base origin/epic/search", self.check()[1], "user-level")
        self.set_config({"bases": CHAIN}, where=".copilot/zethus.config.json")
        self.assertIn("base origin/epic/search", self.check()[1], "repo-untracked")
        self.set_config({"bases": {"search/*": "develop"}}, where=".github/zethus.config.json")
        code, out = self.check()
        self.assertIn("base origin/develop", out, "committed, and the first file found wins whole")
        self.assertIn("branchModel.bases['search/*']", out)

    def test_the_run_log_says_which_base_and_why(self):
        log = self.root / "logs" / "base.log"
        code, _ = self.check("--log", str(log))
        self.assertEqual(code, 0)
        text = log.read_text(encoding="utf-8")
        for line in ("base-freshness: start mode=gate remote=origin fetch=True",
                     "config: .copilot/zethus.config.json",
                     "fetch origin: ok",
                     "default base develop",
                     "bases: 'search/*' matches 'search/ranking' -> 'epic/search'",
                     "link: epic/search -> develop because branchModel.bases['epic/search']",
                     "chosen: search/ranking -> epic/search because branchModel.bases['search/*']",
                     "retarget: origin/epic/search is live",
                     "verdict: FRESH (0 behind origin/epic/search, allowed 0)",
                     "base-freshness: exit 0"):
            self.assertIn(line, text, line)
        self.assertRegex(text, r"^\d{4}-\d\d-\d\dT[\d:]+ \[\d{8}T\d{6}-\d+\] ", "stamped, with the "
                         "run's id")

        self.set_config({"bases": ["develop"]})
        self.assertEqual(self.check("--log", str(log))[0], 2)
        self.assertIn("usage error: branchModel.bases must be an object",
                      log.read_text(encoding="utf-8"))

    def test_the_log_defaults_to_the_user_home_and_can_be_turned_off(self):
        default = self.home / ".copilot" / "zethus" / "logs" / "base-freshness.log"
        self.check()
        self.assertTrue(default.is_file())
        default.unlink()
        self.check("--log", "off")
        with mock.patch.dict(os.environ, {"ZETHUS_BASE_LOG": "off"}):
            self.check()
        self.assertFalse(default.exists())


class Wording(unittest.TestCase):
    """Every doc that used one ``<base>`` now says it is the branch's own."""

    def test_the_decision_is_recorded_beside_the_others(self):
        text = RECORD.read_text(encoding="utf-8")
        for phrase in ("| Date | 2026-11-19 |", "| Deciders | Ceryce Armstrong |",
                       "Ceryce's request, paraphrased", "## Decision", "## Context",
                       "## Options considered", "## Consequences", "## Revisit when",
                       "### When the parent moves", "### When the parent merges",
                       "current tip", "--fork-point", "RETARGET", "The run log"):
            self.assertIn(phrase, text, phrase)
        self.assertNotIn("\n> ", text, "a public record paraphrases; no block quote")
        self.assertIn("per-branch-bases.md", CADENCE.read_text(encoding="utf-8"))
        self.assertIn("`--base-for`", CADENCE.read_text(encoding="utf-8"))

    def test_the_agent_and_its_mirror_resolve_the_base_per_branch(self):
        for path in (CANONICAL, MIRROR):
            text = flat(path)
            self.assertIn("base-freshness.py --base-for <branch>", text, path)
            self.assertIn("per-branch-bases.md", text, path)
            self.assertIn("`branchModel.bases`", text, path)
            self.assertIn("PR opened against the branch's base", text, path)
            self.assertNotIn("find the integration branch", text, path)

    def test_the_skills_use_the_branchs_own_base(self):
        gates = flat(GATES)
        for phrase in ("## Keep a chain of bases in sync", "this branch's own base", "`onto`",
                       "`RETARGET`", "git merge origin/<its base>", "--update-refs"):
            self.assertIn(phrase, gates, phrase)
        pr = flat(PR_SKILL)
        for phrase in ("`branchModel.bases`", "--base-for <branch>", "`RETARGET`",
                       "open the PR against this branch's base"):
            self.assertIn(phrase, pr, phrase)
        self.assertNotIn("open the PR against the integration branch", pr)
        self.assertIn("--base-for <branch>", flat(IMPLEMENT))

    def test_the_working_agreement_says_each_branch_has_its_base(self):
        text = flat(AGREEMENT)
        for phrase in ("Branch from the **branch's base**", "`branchModel.bases`",
                       "--base-for <branch>", "Open the PR against the branch's base", "RETARGET"):
            self.assertIn(phrase, text, phrase)

    def test_readme_and_example_config_are_in_sync(self):
        readme = README.read_text(encoding="utf-8")
        self.assertIn("### Per-branch bases", readme)
        self.assertIn("| `branchModel.bases` |", readme)
        self.assertIn("(docs/per-branch-bases.md)", readme)
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(example["branchModel"]["bases"], {}, "the installed config maps nothing")
        self.assertEqual(fresh.branch_model(example), ("branch-per-change", 0))
        self.assertIn("docs/per-branch-bases.md", example["_branchModelReadme"])
        shown = json.loads(readme.split("### Per-branch bases", 1)[1].split("```json", 1)[1]
                           .split("```", 1)[0])
        bases = fresh.bases_map(shown)
        self.assertEqual(fresh.match_base("search/ranking", bases)[0], "epic/search")
        self.assertEqual(fresh.match_base("epic/search", bases)[0], "develop")


if __name__ == "__main__":
    unittest.main()
