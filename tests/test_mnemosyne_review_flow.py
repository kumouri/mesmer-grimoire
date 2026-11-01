"""The promote/export review loop, end to end against real git repos with local bare remotes.

Each class pins one behaviour the loop depends on:

- ids are never reused across the local tier, a review branch and the merged shared tier, a
  merged lesson stays recallable, and `validate` reports a collision;
- a promotion commits only its own lesson, whatever else is uncommitted;
- merging a store's review PR is the approval: the next `sync` retires the local copy, with no
  hand edit anywhere;
- recall reads only cached stores and never clones; `sync` is the one network path;
- nothing leaves the local tier carrying the login name or an absolute path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
MNEMOSYNE_SRC = REPO / "mnemosyne" / "src"
if str(MNEMOSYNE_SRC) not in sys.path:
    sys.path.insert(0, str(MNEMOSYNE_SRC))

import mnemosyne as mn  # noqa: E402
from mnemosyne import core, stores  # noqa: E402
from mnemosyne.config import Config, load_named_example  # noqa: E402

# Hermetic git: a fixed identity, no signing, no system config, so the tests behave the same on a
# developer machine and a bare CI runner.
GIT_ENV = {
    "GIT_AUTHOR_NAME": "alice", "GIT_AUTHOR_EMAIL": "alice@example.com",
    "GIT_COMMITTER_NAME": "alice", "GIT_COMMITTER_EMAIL": "alice@example.com",
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "init.defaultBranch", "GIT_CONFIG_VALUE_1": "main",
}


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                          text=True, stdin=subprocess.DEVNULL).stdout.strip()


def ids_in(text):
    return sorted(json.loads(line)["id"] for line in text.splitlines() if line.strip())


class GitWorld(unittest.TestCase):
    """A temp dir with helpers for bare remotes, clones and a reviewer who merges PRs."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        env = patch.dict(os.environ, GIT_ENV)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("MNEMOSYNE_AUTHOR", None)
        self.cache = self.root / "cache"
        cache_env = patch.dict(os.environ, {"MNEMOSYNE_CACHE": str(self.cache)})
        cache_env.start()
        self.addCleanup(cache_env.stop)
        self.cfg = load_named_example("default")

    def memory_remote(self, name, seed=()):
        """A bare repo holding an initialized memory store (optionally seeded), on branch main."""
        bare = self.root / f"{name}.git"
        git(self.root, "init", "-q", "--bare", str(bare))
        work = self.root / f"{name}-seed"
        git(self.root, "clone", "-q", str(bare), str(work))
        core.init_repo(work)
        if seed:
            core.write_jsonl(core.shared_path(work), list(seed))
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", "init store")
        git(work, "push", "-q", "origin", "HEAD:main")
        return bare

    def clone(self, bare, name):
        dest = self.root / name
        git(self.root, "clone", "-q", str(bare), str(dest))
        return dest

    def merge_review_branch(self, bare, branch):
        """A reviewer merges the PR: a merge commit of origin/<branch> into main, pushed."""
        reviewer = self.root / f"reviewer-{bare.stem}"
        if not reviewer.exists():
            git(self.root, "clone", "-q", str(bare), str(reviewer))
        git(reviewer, "checkout", "-q", "main")
        git(reviewer, "pull", "-q", "--ff-only")
        git(reviewer, "merge", "-q", "--no-ff", "-m", f"Merge {branch}", f"origin/{branch}")
        git(reviewer, "push", "-q", "origin", "main")

    def capture(self, repo, title, tags, cfg=None):
        return core.capture(cfg or self.cfg, repo, {
            "title": title, "lesson": f"{title}: apply this whenever the {tags} code changes.",
            "trigger": {"tags": tags}})["id"]


class LessonIdsAreNeverReused(GitWorld):
    def setUp(self):
        super().setUp()
        self.remote = self.memory_remote("primary")
        self.dev = self.clone(self.remote, "dev")

    def test_the_next_capture_after_a_promotion_gets_a_fresh_id(self):
        first = self.capture(self.dev, "Page list endpoints at 50 by default", "pagination")
        res = core.promote(self.cfg, self.dev, first, push=True)
        self.assertTrue(res["pr"]["pushed"], res["pr"]["error"])
        self.assertEqual(git(self.dev, "branch", "--show-current"), "main",
                         "promote must leave the developer on their branch")
        second = self.capture(self.dev, "Prefer composed helpers over deep trees", "composition")
        self.assertNotEqual(second, first)

    def test_a_fresh_clone_does_not_reuse_an_id_on_a_review_branch(self):
        first = self.capture(self.dev, "Page list endpoints at 50 by default", "pagination")
        core.promote(self.cfg, self.dev, first, push=True)
        teammate = self.clone(self.remote, "teammate")  # sees origin/reflexion/<id>, not dev's local tier
        self.assertNotEqual(self.capture(teammate, "Prefer composed helpers", "composition"), first)

    def test_a_merged_promotion_stays_recallable(self):
        first = self.capture(self.dev, "Page list endpoints at 50 by default", "pagination")
        res = core.promote(self.cfg, self.dev, first, push=True)
        git(self.dev, "checkout", "-q", "main")  # back to work on main, wherever promote left us
        self.merge_review_branch(self.remote, res["branch"])
        second = self.capture(self.dev, "Prefer composed helpers over deep trees", "composition")

        core.sync(self.cfg, self.dev)

        ranked, tier = core.recall(self.cfg, self.dev,
                                   core.build_recall_context(self.cfg, axes={"tags": "pagination"}))
        self.assertEqual([l["id"] for l, _, _ in ranked], [first])
        self.assertEqual(tier[first], "shared")
        listed = {l["id"]: (l["title"], t) for l, t in core.list_lessons(self.cfg, self.dev)}
        self.assertEqual(listed[first][1], "shared")
        self.assertEqual(listed[second][1], "local")
        v = core.validate(self.cfg, self.dev)
        self.assertEqual(v["problems"], [])

    def test_validate_reports_a_collision_and_recall_keeps_the_shared_lesson(self):
        repo = self.root / "collided"
        core.init_repo(repo)
        base = {"category": "decision", "memory_type": "semantic", "trigger": {"tags": ["x"]},
                "status": "active", "confidence": "medium", "created": core.today()}
        core.write_jsonl(core.shared_path(repo), [{
            **base, "id": "L-0001", "title": "Page list endpoints at 50", "review": {"state": "approved"},
            "lesson": "Default list endpoints to a page size of 50.", "trigger": {"tags": ["pagination"]}}])
        core.write_jsonl(core.local_path(repo), [{
            **base, "id": "L-0001", "title": "Prefer composed helpers", "review": {"state": "local"},
            "lesson": "Compose small helpers instead of deep inheritance."}])

        v = core.validate(self.cfg, repo)
        self.assertFalse(v["ok"])
        self.assertTrue(any("L-0001" in p and "collision" in p for p in v["problems"]), v["problems"])
        hits = mn.recall(tags="pagination", repo=repo, config=self.cfg)
        self.assertEqual([h["title"] for h in hits], ["Page list endpoints at 50"])


class PromotionCommitsOnlyItsOwnLesson(GitWorld):
    def test_an_earlier_unpushed_promotion_is_not_swept_in(self):
        remote = self.memory_remote("primary")
        dev = self.clone(remote, "dev")
        a = self.capture(dev, "Page list endpoints at 50 by default", "pagination")
        b = self.capture(dev, "Pin idempotency for every new POST endpoint", "idempotency")

        core.promote(self.cfg, dev, a)              # staged only, never pushed
        res = core.promote(self.cfg, dev, b, push=True)
        self.assertTrue(res["pr"]["pushed"], res["pr"]["error"])

        pushed = git(dev, "show", f"origin/reflexion/{b}:memory/lessons.jsonl")
        self.assertEqual(ids_in(pushed), [b])
        self.assertIn(b, git(dev, "show", f"origin/reflexion/{b}:memory/LESSONS.md"))
        self.assertNotIn(a, git(dev, "show", f"origin/reflexion/{b}:memory/LESSONS.md"))
        self.assertEqual(ids_in(git(dev, "show", f"reflexion/{a}:memory/lessons.jsonl")), [a])
        self.assertEqual(git(dev, "status", "--porcelain", "--", "memory/lessons.jsonl"), "",
                         "promote must not leave the working tree's shared tier modified")


class MergingTheReviewPrIsTheApproval(GitWorld):
    def test_store_merge_retires_the_local_copy_on_the_next_sync(self):
        store_remote = self.memory_remote("team-store")
        cfg = Config({**self.cfg.as_dict(),
                      "stores": [{"tier": "team", "prefix": "T", "url": str(store_remote)}]})
        dev = self.root / "dev"
        core.init_repo(dev)
        local_id = self.capture(dev, "Emit structured JSON logs from every service", "logging", cfg)
        core.sync(cfg, dev)  # clones the store into the cache

        exp = core.export(cfg, dev, [local_id], "team", push=True)
        self.assertTrue(exp["pr"]["pushed"], exp["pr"]["error"])
        remote_id = exp["exported"][0]["remote_id"]

        self.assertEqual(core.sync(cfg, dev)["retired"], [], "nothing merged yet: nothing retires")
        self.merge_review_branch(store_remote, exp["branch"])
        self.assertEqual(core.sync(cfg, dev)["retired"], [local_id])

        orig = {l["id"]: l for l in core.read_jsonl(core.local_path(dev))}[local_id]
        self.assertEqual(orig["status"], "retired")
        self.assertEqual(orig["superseded_by"], remote_id)
        cache = stores.store_dir(stores.resolve_store(cfg, "team"))
        merged = {l["id"]: l for l in core.read_jsonl(core.shared_path(cache))}
        self.assertEqual(merged[remote_id]["review"]["state"], "approved")
        ranked, tier = core.recall(cfg, dev, core.build_recall_context(cfg, axes={"tags": "logging"}))
        self.assertEqual([(l["id"], tier[l["id"]]) for l, _, _ in ranked], [(remote_id, "team")])

    def test_shared_promotion_merge_retires_the_local_copy_on_the_next_sync(self):
        remote = self.memory_remote("primary")
        dev = self.clone(remote, "dev")
        lid = self.capture(dev, "Page list endpoints at 50 by default", "pagination")
        res = core.promote(self.cfg, dev, lid, push=True)
        self.assertEqual(core.sync(self.cfg, dev)["retired"], [])
        self.merge_review_branch(remote, res["branch"])
        self.assertEqual(core.sync(self.cfg, dev)["retired"], [lid])
        shared = {l["id"]: l for l in core.read_jsonl(core.shared_path(dev))}
        self.assertEqual(shared[lid]["review"]["state"], "approved")


class RecallNeverTouchesTheNetwork(GitWorld):
    def _recall_recording_git(self, cfg, repo, notes):
        calls = []
        real = stores.git

        def recording(*args, **kwargs):
            calls.append(args[1:])
            return real(*args, **kwargs)

        with patch.object(stores, "git", recording):
            ranked, _ = core.recall(cfg, repo, core.build_recall_context(cfg, axes={"tags": "logging"}),
                                    notes=notes)
        return ranked, calls

    def test_recall_skips_an_uncached_store_without_cloning_and_sync_fetches_it(self):
        seed = {"id": "T-0001", "title": "Emit structured JSON logs", "category": "convention",
                "memory_type": "semantic", "lesson": "All services emit structured JSON logs.",
                "trigger": {"tags": ["logging"]}, "confidence": "high", "status": "active",
                "review": {"state": "approved"}, "created": core.today()}
        store_remote = self.memory_remote("team-store", seed=[seed])
        cfg = Config({**self.cfg.as_dict(),
                      "stores": [{"tier": "team", "prefix": "T", "url": str(store_remote)}]})
        dev = self.root / "dev"
        core.init_repo(dev)

        notes = []
        ranked, calls = self._recall_recording_git(cfg, dev, notes)
        self.assertEqual(ranked, [])
        self.assertFalse([c for c in calls if "clone" in c], calls)
        self.assertFalse(self.cache.exists(), "recall created the clone cache")
        self.assertTrue(any("sync" in n for n in notes), notes)

        core.sync(cfg, dev)
        notes = []
        ranked, calls = self._recall_recording_git(cfg, dev, notes)
        self.assertEqual([l["id"] for l, _, _ in ranked], ["T-0001"])
        self.assertEqual(notes, [])

    def test_recall_skips_an_unreachable_store_with_a_note(self):
        cfg = Config({**self.cfg.as_dict(), "stores": [
            {"tier": "team", "prefix": "T", "url": str(self.root / "no-such-store.git")}]})
        dev = self.root / "dev"
        core.init_repo(dev)
        self.capture(dev, "Emit structured JSON logs from every service", "logging", cfg)
        notes = []
        ranked, calls = self._recall_recording_git(cfg, dev, notes)
        self.assertEqual(len(ranked), 1)
        self.assertFalse([c for c in calls if "clone" in c], calls)
        self.assertEqual(len(notes), 1, notes)


class NothingLeavesTheLocalTierUnscrubbed(GitWorld):
    LOGIN = "alice"

    def setUp(self):
        super().setUp()
        login = patch.dict(os.environ, {"USER": self.LOGIN, "USERNAME": self.LOGIN})
        login.start()
        self.addCleanup(login.stop)

    def _dirty_local_lesson(self, repo):
        inside = repo / "src" / "app.py"
        lesson = {
            "id": "L-0001", "title": "Validate the payload before persisting", "category": "mistake",
            "memory_type": "episodic", "lesson": "Validate every inbound payload before it is saved.",
            "trigger": {"tags": ["validation"]}, "status": "active", "confidence": "high",
            "review": {"state": "local"}, "created": core.today(), "author": self.LOGIN,
            "source": {
                "anchors": [f"{inside}:12", r"C:\Users\alice\notes\scratch.md",
                            "/home/alice/tmp/repro.py:3", "https://example.com/pr/1", "src/rel.py:4"],
                "reflection_of": f"A bad payload reached {inside} because /home/alice/tmp/repro.py skipped it.",
            },
        }
        core.write_jsonl(core.local_path(repo), [lesson])
        return lesson

    def assert_scrubbed(self, record, repo):
        blob = json.dumps(record)
        self.assertEqual(record["author"], "unknown")
        self.assertEqual(record["source"]["anchors"],
                         ["src/app.py:12", "https://example.com/pr/1", "src/rel.py:4"])
        self.assertIn("src/app.py", record["source"]["reflection_of"])
        for leak in (str(repo), str(repo).replace("\\", "/"), self.LOGIN):
            self.assertNotIn(leak, blob)

    def test_capture_never_records_the_login_name(self):
        dev = self.root / "dev"
        core.init_repo(dev)
        lid = self.capture(dev, "Emit structured JSON logs from every service", "logging")
        self.assertEqual(core.show(self.cfg, dev, lid)["author"], "unknown")

    def test_export_to_a_store_is_scrubbed(self):
        store = self.root / "team-store"
        core.init_repo(store)
        cfg = Config({**self.cfg.as_dict(), "stores": [{"tier": "team", "prefix": "T", "path": str(store)}]})
        dev = self.root / "dev"
        core.init_repo(dev)
        self._dirty_local_lesson(dev)
        exp = core.export(cfg, dev, ["L-0001"], "team")
        remote_id = exp["exported"][0]["remote_id"]
        copy = {l["id"]: l for l in core.read_jsonl(core.shared_path(store))}[remote_id]
        self.assert_scrubbed(copy, dev)
        self.assertNotIn(self.LOGIN, (store / "memory" / "LESSONS.md").read_text(encoding="utf-8"))

    def test_promotion_to_the_shared_tier_is_scrubbed(self):
        remote = self.memory_remote("primary")
        dev = self.clone(remote, "dev")
        self._dirty_local_lesson(dev)
        res = core.promote(self.cfg, dev, "L-0001", push=True)
        self.assertTrue(res["pr"]["pushed"], res["pr"]["error"])
        pushed = git(dev, "show", f"origin/{res['branch']}:memory/lessons.jsonl")
        self.assert_scrubbed(json.loads(pushed), dev)
        self.assertNotIn(self.LOGIN, git(dev, "show", f"origin/{res['branch']}:memory/LESSONS.md"))

    def test_a_shared_capture_is_scrubbed(self):
        dev = self.root / "dev"
        core.init_repo(dev)
        core.capture(self.cfg, dev, {"title": "Keep fixtures beside their tests",
                                     "lesson": "Put each fixture next to the test that reads it.",
                                     "anchors": f"{dev / 'tests' / 'fixtures'},/home/alice/x.py",
                                     "shared": True})
        rec = core.read_jsonl(core.shared_path(dev))[0]
        self.assertEqual(rec["source"]["anchors"], ["tests/fixtures"])
        self.assertNotIn(self.LOGIN, json.dumps(rec))


if __name__ == "__main__":
    unittest.main()
