"""CI coverage for the mnemosyne reflexion-memory engine.

Wraps mnemosyne's own zero-dependency self-test into the repo unittest suite, plus checks that the
bundled configs load, the public API round-trips on a temp repo, a save that dies mid-write leaves
the old store intact, concurrent writer processes lose no update and a dead lock holder never
wedges the store, `promote` stages (and with push, pushes) the same review PR from every surface,
and the plugin no longer registers the dead SessionEnd nudge. The review loop itself (ids, merges,
offline recall, scrubbing) is in test_mnemosyne_review_flow.py; the MCP stdio round trip is in
test_mnemosyne_mcp_stdio.py.
"""
from __future__ import annotations

import importlib
import inspect
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
MNEMOSYNE_SRC = REPO / "mnemosyne" / "src"
PLUGIN_HOOKS = REPO / "mnemosyne" / "plugin" / "hooks"

if str(MNEMOSYNE_SRC) not in sys.path:
    sys.path.insert(0, str(MNEMOSYNE_SRC))


class MnemosyneSelfTest(unittest.TestCase):
    def test_selftest_passes(self):
        from mnemosyne.cli import run_selftest

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_selftest()
        self.assertEqual(rc, 0, msg="mnemosyne selftest failed:\n" + buf.getvalue())
        self.assertIn("ALL PASS", buf.getvalue())


class BundledConfigs(unittest.TestCase):
    def test_default_and_software_eng_load(self):
        from mnemosyne.config import load_named_example

        default = load_named_example("default")
        self.assertEqual(default.axis_names, ["tags"])

        se = load_named_example("software-eng")
        self.assertIn("components", se.axis_names)
        self.assertIn("endpoint_patterns", se.axis_names)


class PublicApiRoundTrip(unittest.TestCase):
    def test_capture_then_recall(self):
        import mnemosyne as mn

        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "memory").mkdir()
            saved = mn.capture(
                "Prefer feature flags for risky rollouts",
                "Wrap risky changes behind a feature flag and roll out gradually.",
                confidence="high", tags="feature-flag,rollback", repo=d,
            )
            self.assertEqual(saved["action"], "saved")

            hits = mn.recall("how should we do a risky rollout?", repo=d)
            self.assertTrue(any(h["id"] == saved["id"] for h in hits))


def _lesson(i):
    return {"id": f"L-{i:04d}", "title": f"lesson {i}", "lesson": "x" * 200}


class AtomicWrites(unittest.TestCase):
    """A save that fails part-way must leave the previous store byte-for-byte intact."""

    def setUp(self):
        from mnemosyne import core

        self.core = core
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Path(self._tmp.name) / "memory" / "lessons.jsonl"
        core.write_jsonl(self.store, [_lesson(i) for i in range(1, 4)])
        self.before = self.store.read_bytes()

    def tearDown(self):
        self._tmp.cleanup()

    def _assert_old_store_survives(self):
        self.assertEqual(self.store.read_bytes(), self.before)
        self.assertEqual([p.name for p in self.store.parent.iterdir()], ["lessons.jsonl"],
                         "the failed save left a temp file behind")
        self.assertEqual(len(self.core.read_jsonl(self.store)), 3)

    def test_crash_mid_write_keeps_old_store(self):
        real_fdopen = os.fdopen

        def torn_fdopen(fd, *args, **kwargs):
            fh = real_fdopen(fd, *args, **kwargs)
            real_write = fh.write

            def write(text):
                real_write(text[: len(text) // 2])  # half the bytes land, then the "crash"
                raise OSError("simulated crash mid-write")

            fh.write = write
            return fh

        with patch.object(self.core.os, "fdopen", torn_fdopen):
            with self.assertRaises(OSError):
                self.core.write_jsonl(self.store, [_lesson(i) for i in range(1, 50)])
        self._assert_old_store_survives()

    def test_failure_before_the_swap_keeps_old_store(self):
        for target in ("fsync", "replace"):
            with self.subTest(failing=target):
                with patch.object(self.core.os, target, side_effect=OSError(f"simulated {target} failure")):
                    with self.assertRaises(OSError):
                        self.core.write_jsonl(self.store, [_lesson(9)])
                self._assert_old_store_survives()

    def test_process_killed_mid_save_keeps_old_store(self):
        # A real crash runs no cleanup: kill the child after the new bytes are written but before
        # the swap. The old store must still be whole; only a gitignored temp file may remain.
        child = textwrap.dedent(f"""
            import os, sys
            sys.path.insert(0, {str(MNEMOSYNE_SRC)!r})
            from pathlib import Path
            from mnemosyne import core
            core.os.fsync = lambda fd: os._exit(9)
            core.write_jsonl(Path({str(self.store)!r}),
                             [{{"id": "L-%04d" % i, "lesson": "y" * 200}} for i in range(1, 500)])
        """)
        proc = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 9, proc.stderr)
        self.assertEqual(self.store.read_bytes(), self.before)
        leftovers = [p.name for p in self.store.parent.iterdir() if p.name != "lessons.jsonl"]
        self.assertTrue(all(n.startswith(".lessons.jsonl.") and n.endswith(".tmp") for n in leftovers),
                        leftovers)

    def test_successful_save_replaces_content(self):
        self.core.write_jsonl(self.store, [_lesson(7)])
        self.assertEqual([l["id"] for l in self.core.read_jsonl(self.store)], ["L-0007"])
        self.assertEqual([p.name for p in self.store.parent.iterdir()], ["lessons.jsonl"])


class StoreLock(unittest.TestCase):
    """Concurrent saves serialise on the store lock; a dead holder never wedges it; waits are bounded."""

    def setUp(self):
        import mnemosyne as mn

        self.mn = mn
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)  # cleanups run LIFO: after any lock-holding child is reaped
        self.repo = Path(self._tmp.name) / "memory-repo"
        mn.core.init_repo(self.repo)
        self.lock = mn.core.lock_path(self.repo)

    def _child(self, body):
        return textwrap.dedent(f"""
            import os, sys, time
            sys.path.insert(0, {str(MNEMOSYNE_SRC)!r})
            from pathlib import Path
            import mnemosyne as mn
            REPO = {str(self.repo)!r}
        """) + textwrap.dedent(body)

    def _hold_lock_in_child(self):
        """Start a process that takes the lock and sleeps; return (proc, the pid that holds it)."""
        proc = subprocess.Popen(
            [sys.executable, "-c", self._child("""
                with mn.core.store_lock(REPO):
                    print(os.getpid(), flush=True)
                    time.sleep(120)
            """)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        line = proc.stdout.readline()
        proc.stdout.close()
        self.assertTrue(line.strip(), "lock-holding child exited before taking the lock")
        return proc, int(line)

    def test_two_concurrent_writer_processes_lose_no_lesson(self):
        n = 15
        go = Path(self._tmp.name) / "go"
        # Each writer pauses between reading the store and replacing it. Without the lock that
        # widened window loses lessons on every run; with it the two writers must take turns.
        writer = self._child(f"""
            tag = sys.argv[1]
            real_write = mn.core.write_jsonl
            def slow_write(*args, **kwargs):
                time.sleep(0.02)
                return real_write(*args, **kwargs)
            mn.core.write_jsonl = slow_write
            while not Path({str(go)!r}).exists():
                time.sleep(0.005)
            for i in range({n}):
                mn.capture(f"writer {{tag}} rule {{i}}",
                           f"Writer {{tag}} must apply rule {{i}} to its own module.",
                           force=True, repo=REPO)
        """)
        procs = [subprocess.Popen([sys.executable, "-c", writer, tag], stderr=subprocess.PIPE, text=True)
                 for tag in ("a", "b")]
        go.touch()  # release both writers at once so their saves overlap
        for p in procs:
            _, err = p.communicate(timeout=180)
            self.assertEqual(p.returncode, 0, err)

        lessons = self.mn.core.read_jsonl(self.mn.core.local_path(self.repo))
        titles = {l["title"] for l in lessons}
        expected = {f"writer {t} rule {i}" for t in ("a", "b") for i in range(n)}
        self.assertEqual(titles, expected, f"lost {len(expected - titles)} of {2 * n} lessons")
        self.assertEqual(len({l["id"] for l in lessons}), 2 * n, "two saves were given the same id")
        md = (self.repo / "memory" / "LESSONS.md").read_text(encoding="utf-8")
        self.assertIn(f"**{2 * n} active lesson(s)**", md)

    def test_stale_lockfile_from_a_dead_pid_is_recovered(self):
        dead = subprocess.Popen([sys.executable, "-c", "import os; print(os.getpid())"],
                                stdout=subprocess.PIPE, text=True)
        dead_pid = int(dead.communicate()[0])
        self.lock.write_text(json.dumps({"pid": dead_pid, "since": "2026-01-01T00:00:00"}), encoding="utf-8")

        saved = self.mn.capture("Recovered", "A dead holder's lockfile must not block a save.",
                                force=True, repo=self.repo)
        self.assertEqual(saved["action"], "saved")
        self.assertEqual(self.mn.core.lock_holder(self.lock)["pid"], os.getpid())

    def test_holder_killed_while_holding_does_not_wedge_the_lock(self):
        proc, _ = self._hold_lock_in_child()
        proc.kill()  # a crash: no release, no cleanup
        proc.wait()
        with self.mn.core.store_lock(self.repo, timeout=10):
            pass

    def test_wait_is_bounded_and_names_the_holder(self):
        seed = self.mn.capture("Prefer feature flags for risky rollouts",
                               "Wrap risky changes behind a feature flag and roll out gradually.",
                               tags="feature-flag,rollback", repo=self.repo)
        _, holder_pid = self._hold_lock_in_child()
        start = time.monotonic()
        with self.assertRaises(self.mn.LockTimeout) as cm:
            with self.mn.core.store_lock(self.repo, timeout=0.3):
                self.fail("took a lock another process holds")
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(cm.exception.holder["pid"], holder_pid)
        self.assertIn(f"pid {holder_pid}", str(cm.exception))
        self.assertEqual(cm.exception.code, 4)

        with patch.dict(os.environ, {"MNEMOSYNE_LOCK_TIMEOUT": "0.2"}):
            with self.assertRaises(self.mn.LockTimeout):
                self.mn.capture("Blocked", "A save must wait for the lock, then fail clearly.",
                                force=True, repo=self.repo)
            # recall's usage bump is best-effort: a held lock skips it rather than failing recall
            hits = self.mn.recall("how should we do a risky rollout?", repo=self.repo)
        self.assertIn(seed["id"], [h["id"] for h in hits])
        self.assertEqual(self.mn.core.read_usage(self.repo), {})
        self.assertEqual([l["id"] for l in self.mn.core.read_jsonl(self.mn.core.local_path(self.repo))],
                         [seed["id"]])


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class PromoteParity(unittest.TestCase):
    """CLI, API and MCP `promote` share one engine path that stages the review PR."""

    def setUp(self):
        import mnemosyne as mn

        self.mn = mn
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.remote = root / "remote.git"
        self.repo = root / "memory-repo"
        self.repo.mkdir()
        _git(root, "init", "-q", "--bare", str(self.remote))
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "alice@example.com")
        _git(self.repo, "config", "user.name", "alice")
        _git(self.repo, "config", "commit.gpgsign", "false")
        _git(self.repo, "remote", "add", "origin", str(self.remote))
        mn.core.init_repo(self.repo)
        mn.core.render_lessons_md(mn.load_config(None, self.repo), self.repo)
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "init")
        self.ids = [
            mn.capture(f"Rule {n}", f"Always apply rule {n} when touching the {n} module.",
                       tags=f"rule-{n}", repo=self.repo)["id"]
            for n in ("alpha", "beta")
        ]

    def tearDown(self):
        self._tmp.cleanup()

    def test_promote_commits_the_branch_and_returns_the_push_step(self):
        res = self.mn.promote(self.ids[0], repo=self.repo)
        pr = res["pr"]
        branch = f"reflexion/{self.ids[0]}"
        self.assertTrue(pr["is_git"])
        self.assertFalse(pr["pushed"])
        self.assertEqual(pr["branch"], branch)
        self.assertEqual(len(pr["commands"]), 1)
        self.assertIn(f"push -u origin {branch}", pr["commands"][0])
        files = subprocess.run(["git", "-C", str(self.repo), "show", "--name-only", "--format=", branch],
                               capture_output=True, text=True, check=True).stdout.split()
        self.assertEqual(sorted(files), ["memory/LESSONS.md", "memory/lessons.jsonl"],
                         "local.jsonl is gitignored; the review commit must not carry it")

    def test_push_creates_branch_commits_and_pushes(self):
        res = self.mn.promote(self.ids[0], push=True, repo=self.repo)
        self.assertTrue(res["pr"]["pushed"], res["pr"]["error"])
        branch = f"reflexion/{self.ids[0]}"
        heads = subprocess.run(["git", "ls-remote", "--heads", str(self.remote), branch],
                               capture_output=True, text=True, check=True).stdout
        self.assertIn(branch, heads)
        shown = subprocess.run(["git", "-C", str(self.repo), "show", f"{branch}:memory/lessons.jsonl"],
                               capture_output=True, text=True, check=True).stdout
        self.assertIn(self.ids[0], shown)

    def test_push_failure_is_reported_not_swallowed(self):
        _git(self.repo, "remote", "set-url", "origin", str(Path(self._tmp.name) / "missing.git"))
        res = self.mn.promote(self.ids[0], push=True, repo=self.repo)
        self.assertFalse(res["pr"]["pushed"])
        self.assertIn("git push failed", res["pr"]["error"])

    def test_cli_push_flag_uses_the_same_engine_path(self):
        from mnemosyne.cli import main as cli_main

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli_main(["--repo", str(self.repo), "--format", "json", "promote", self.ids[0], "--push"])
        self.assertEqual(rc, 0)
        out = json.loads(buf.getvalue())
        self.assertTrue(out["results"][0]["pr"]["pushed"], out)

    def _load_mcp_server(self):
        # Stub the optional `mcp` dependency so the tool functions import as plain callables.
        fastmcp = types.ModuleType("mcp.server.fastmcp")

        class FastMCP:
            def __init__(self, name):
                self.name = name

            def tool(self):
                return lambda fn: fn

            def run(self):
                pass

        fastmcp.FastMCP = FastMCP
        stubs = {"mcp": types.ModuleType("mcp"), "mcp.server": types.ModuleType("mcp.server"),
                 "mcp.server.fastmcp": fastmcp}
        with patch.dict(sys.modules, stubs):
            sys.modules.pop("mnemosyne.mcp_server", None)
            try:
                return importlib.import_module("mnemosyne.mcp_server")
            finally:
                sys.modules.pop("mnemosyne.mcp_server", None)

    def test_mcp_promote_takes_the_cli_options_and_stages_the_pr(self):
        server = self._load_mcp_server()
        params = inspect.signature(server.promote).parameters
        self.assertEqual(list(params), ["lesson_ids", "to", "push"])
        with patch.dict(os.environ, {"MNEMOSYNE_REPO": str(self.repo)}):
            res = server.promote(",".join(self.ids))
        self.assertTrue(res["same_repo"])
        self.assertEqual([r["id"] for r in res["results"]], self.ids)
        for r in res["results"]:
            self.assertEqual(len(r["pr"]["commands"]), 1)
            self.assertFalse(r["pr"]["pushed"])


class SessionEndNudgeRemoved(unittest.TestCase):
    """Claude Code discards SessionEnd output, so the plugin must not register a nudge there."""

    def test_hooks_json_has_no_session_end(self):
        hooks = json.loads((PLUGIN_HOOKS / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        self.assertNotIn("SessionEnd", hooks)
        self.assertEqual(set(hooks), {"SessionStart", "UserPromptSubmit"})

    def test_stale_session_end_mode_is_a_silent_no_op(self):
        # Give the hook everything the old nudge needed (an importable engine and a memory repo),
        # so silence proves the mode is gone rather than that the hook failed open.
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "memory").mkdir()
            env = dict(os.environ, PYTHONPATH=str(MNEMOSYNE_SRC), MNEMOSYNE_REPO=d)
            proc = subprocess.run([sys.executable, str(PLUGIN_HOOKS / "mnemosyne_hook.py"), "session-end"],
                                  input="{}", capture_output=True, text=True, env=env)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "")


if __name__ == "__main__":
    unittest.main()
