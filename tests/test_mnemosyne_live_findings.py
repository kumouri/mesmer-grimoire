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
