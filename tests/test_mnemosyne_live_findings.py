"""Regressions for live capture findings, using synthetic public-safe lessons."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mnemosyne" / "src"))
from mnemosyne import core, cli, candidates
from mnemosyne.config import load_named_example


def pair():
    common = {"category": "mistake", "trigger": {"tags": ["analysis", "binary", "pinning"]}}
    return [dict(common, title="Pin a binary before analysis",
                 lesson="Before chaining analysis commands, pin a copy of the binary file. Record the digest each run claims and verify addresses against that copy before further investigation. Keep the evidence with the report."),
            dict(common, title="Check binary identity between analysis commands",
                 lesson="When a binary file may change, pin a copy and record the digest each analysis run claims.")]


class ParaphraseEscape(unittest.TestCase):
    def test_paraphrase_reinforces_and_distinct_same_category_banks(self):
        cfg = load_named_example("default")
        a, b = pair()
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            core.init_repo(repo)
            self.assertEqual(core.capture(cfg, repo, a)["action"], "saved")
            self.assertEqual(core.capture(cfg, repo, b)["action"], "reinforced")
            for title, text in [
                ("Preserve symbols", "Archive debugging symbols before stripping release artifacts for analysis."),
                ("Limit analysis resources", "Set a memory ceiling for binary analysis workers and queue large files."),
                ("Save analysis notes", "Record analysis findings in a report and copy the evidence file to an archive."),
            ]:
                other = dict(a, title=title, lesson=text)
                self.assertLess(core.lesson_similarity(a, other), cfg.dup_threshold)
                self.assertEqual(core.capture(cfg, repo, other)["action"], "saved")
            rows = core.read_jsonl(core.local_path(repo))
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[0]["reinforced"], 1)

    def test_metadata_alone_cannot_merge(self):
        a, b = pair()
        b.update(title="Encrypt backups", lesson="Rotate encryption keys on a monthly schedule.")
        self.assertLess(core.lesson_similarity(a, b), .6)

    def test_recall_grey_band_hint_is_read_only(self):
        cfg = load_named_example("default")
        a, b = pair()
        # Put this known pair below the configured reinforce threshold.
        cfg.dup_threshold = .9
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            core.init_repo(repo)
            core.capture(cfg, repo, a, force=True)
            core.capture(cfg, repo, b, force=True)
            before = core.local_path(repo).read_bytes()
            ranked, tier = core.recall(cfg, repo, {"query": "binary analysis", "tags": ["binary", "analysis"]}, bump=False)
            text = core.render_digest(cfg, ranked, repo, tier, "text", 4000)
            self.assertIn("possible duplicate?", text)
            self.assertEqual(core.local_path(repo).read_bytes(), before)
            self.assertFalse(core.usage_path(repo).exists())


class AuthorProvenance(unittest.TestCase):
    def test_identity_resolution_and_neutral_floor(self):
        import subprocess
        cfg = load_named_example("default")
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"MNEMOSYNE_AUTHOR": "", "GIT_AUTHOR_NAME": ""}):
            repo = Path(d)
            core.init_repo(repo)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "alice"], check=True)
            for identity, expected in [({}, "alice"), ({"MNEMOSYNE_AUTHOR": "bob"}, "bob")]:
                with patch.dict(os.environ, identity):
                    result = core.capture(cfg, repo, pair()[0], force=True)
                    self.assertEqual(core.show(cfg, repo, result["id"])["author"], expected)
            # No git identity (including a user's global config) must still capture.
            with patch.object(core, "git", return_value=(1, "", "")):
                for identity, expected in [({"GIT_AUTHOR_NAME": "carol"}, "carol"), ({}, "unknown")]:
                    with patch.dict(os.environ, identity):
                        result = core.capture(cfg, repo, pair()[0], force=True)
                        self.assertEqual(core.show(cfg, repo, result["id"])["author"], expected)


class PromoteWithoutOrigin(unittest.TestCase):
    def test_local_branch_and_review_state_survive_without_bad_next_steps(self):
        from tests.test_mnemosyne_review_flow import GIT_ENV, git
        cfg = load_named_example("default")
        for push in (False, True):
            with self.subTest(push=push), tempfile.TemporaryDirectory() as d, patch.dict(os.environ, GIT_ENV):
                repo = Path(d)
                git(repo, "init", "-q")
                core.init_repo(repo)
                git(repo, "add", "-A")
                git(repo, "commit", "-q", "-m", "initialize")
                saved = core.capture(cfg, repo, pair()[0])
                original = git(repo, "rev-parse", "HEAD")
                result = core.promote(cfg, repo, saved["id"], push=push)
                buf = io.StringIO()
                with redirect_stdout(buf):
                    cli._print_shared_promote(result, push)
                text = buf.getvalue()
                self.assertNotIn("gh pr create", text)
                self.assertNotIn("push -u", text)
                self.assertIn("No origin remote", text)
                self.assertIn(result["branch"], text)
                self.assertEqual(git(repo, "rev-parse", "HEAD"), original)
                local = core.show(cfg, repo, saved["id"])
                self.assertEqual(local["review"]["state"], "proposed")
                shared = git(repo, "show", result["branch"] + ":memory/lessons.jsonl")
                import json
                self.assertEqual(json.loads(shared)["review"]["state"], "approved")
                self.assertEqual(git(repo, "remote"), "")


class InstructionCandidateNoise(unittest.TestCase):
    def test_repeat_is_session_and_repo_scoped_beyond_event_window(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            memory = base / "memory-repo"
            core.init_repo(memory)
            one, two = base / "one", base / "two"
            one.mkdir(); two.mkdir()
            env = {"MNEMOSYNE_REPO": str(memory)}
            def capture(root, session, text):
                # These invocations represent distinct events, not two hook registrations.
                with patch.object(candidates, "first_fire", return_value=True):
                    return candidates.capture_event("prompt", {"session_id": session, "prompt": text},
                                                    root=root, env=env)
            self.assertEqual(capture(one, "s1", "Always validate boundary conditions.")["decision"], "candidate")
            self.assertEqual(capture(one, "s1", "Always validate boundary conditions.\nA different task.")["decision"], "duplicate-instruction")
            self.assertEqual(capture(one, "s2", "Always validate boundary conditions.")["decision"], "candidate")
            self.assertEqual(capture(two, "s1", "Always validate boundary conditions.")["decision"], "candidate")
            self.assertEqual(capture(one, "s1", "Always validate array bounds.")["decision"], "candidate")
            self.assertEqual(len(candidates.candidates(memory)), 4)
            for _ in range(2):
                self.assertEqual(capture(one, "", "Always retain diagnostics.")["decision"], "candidate")

    def test_own_standing_text_suppresses_only_exact_instruction(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            core.init_repo(repo)
            (repo / "AGENTS.md").write_text("Never publish unreviewed changes.\n", encoding="utf-8")
            for session in ("first", "second"):
                result = candidates.capture_event("prompt", {"session_id": session,
                    "prompt": "Never publish unreviewed changes.\nReview this patch."}, root=repo, env={})
                self.assertEqual(result["decision"], "duplicate-instruction")
                self.assertEqual(result["candidates"], [])
            result = candidates.capture_event("prompt", {"session_id": "third",
                "prompt": "Never publish unreviewed changes without checking the release notes."}, root=repo, env={})
            self.assertEqual(result["decision"], "candidate")


    def test_instruction_suppression_keeps_recall_running(self):
        import importlib.util
        bridge_path = Path(__file__).resolve().parents[1] / "mnemosyne/plugin/hooks/mnemosyne_hook.py"
        spec = importlib.util.spec_from_file_location("live_bridge", bridge_path)
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            core.init_repo(repo)
            event = {"cwd": str(repo), "session_id": "session", "prompt": "Always check boundaries."}
            with patch.dict(os.environ, {"MNEMOSYNE_REPO": str(repo)}), \
                    patch.object(candidates, "first_fire", return_value=True), \
                    patch("mnemosyne.recall", return_value="RECALL: L-0001") as recall, \
                    redirect_stdout(io.StringIO()):
                bridge.do_prompt(event, None)
                bridge.do_prompt(event, None)
            self.assertEqual(recall.call_count, 2)

    def test_unavailable_instruction_guard_fails_open(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            core.init_repo(repo)
            (candidates.ensure_capture_dir(repo) / "instructions").write_text("unavailable")
            for _ in range(2):
                self.assertIsNone(candidates.instruction_repeat(repo, repo, "s", "Always check inputs."))
