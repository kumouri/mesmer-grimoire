"""Phase 1: Zethus's own scripts feed the Mnemosyne capture spool (docs/lessons-capture-spec.md
§4.7, channel 1). new-adr.py emits an S1 (decision) candidate; run-local-gates.py emits an S2
(mistake) candidate when a gate that failed earlier in the branch now passes. Both are fail-open:
with capture off they record nothing and the script's own exit is unchanged.

Driven as real subprocesses with MNEMOSYNE_REPO pointing at a temp memory repo and the mnemosyne
package on PYTHONPATH. Offline: the only subprocesses are the two Zethus scripts and local git.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MNEMOSYNE_SRC = REPO / "mnemosyne" / "src"
SCRIPTS = REPO / "zethus" / "scripts"

if str(MNEMOSYNE_SRC) not in sys.path:
    sys.path.insert(0, str(MNEMOSYNE_SRC))

from mnemosyne import candidates as cd  # noqa: E402


class _Repo(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        (self.root / "memory").mkdir()
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True, stdin=subprocess.DEVNULL)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("MNEMOSYNE")}
        self.env.update(PYTHONPATH=str(MNEMOSYNE_SRC), MNEMOSYNE_REPO=str(self.root))

    def script(self, name, *args, expect=0, env=None):
        proc = subprocess.run([sys.executable, str(SCRIPTS / name), *args], cwd=str(self.root),
                              capture_output=True, text=True, env=env or self.env,
                              stdin=subprocess.DEVNULL)
        self.assertEqual(proc.returncode, expect, proc.stdout + proc.stderr)
        return proc

    def signals(self):
        return [c["signal"] for c in cd.candidates(self.root)]


class NewAdrEmitsS1(_Repo):
    def test_new_adr_records_an_s1_candidate(self):
        self.script("new-adr.py", "Use the outbox pattern", "--deciders", "Alice")
        (c,) = cd.candidates(self.root)
        self.assertEqual((c["signal"], c["host"]), ("S1", "zethus-script"))
        self.assertIn("outbox", c["evidence"]["adr"])
        self.assertEqual(c["evidence"]["path"], "docs/adr/" + c["evidence"]["adr"] + ".md")

    def test_capture_off_records_nothing_and_the_adr_still_writes(self):
        proc = self.script("new-adr.py", "A plain decision", "--deciders", "Alice",
                           env=dict(self.env, MNEMOSYNE_CAPTURE="off"))
        self.assertIn("created", proc.stdout)                 # the script itself is unaffected
        self.assertFalse(cd.capture_dir(self.root).exists())  # but nothing was recorded


class GatesEmitS2(_Repo):
    def setUp(self):
        super().setUp()
        (self.root / ".github").mkdir()
        # One gate whose pass/fail flips on a sentinel file, so a run can go red then green.
        cfg = {"gates": {"steps": [{"name": "guard", "command": [
            sys.executable, "-c", "import os, sys; sys.exit(0 if os.path.exists('ok') else 1)"]}]}}
        (self.root / ".github" / "zethus.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    def test_a_gate_that_goes_red_then_green_records_s2(self):
        self.script("run-local-gates.py", expect=1)           # red (no sentinel)
        self.assertEqual(self.signals(), [])                  # a red gate alone is not a lesson
        (self.root / "ok").write_text("", encoding="utf-8")
        self.script("run-local-gates.py", expect=0)           # green
        (c,) = cd.candidates(self.root)
        self.assertEqual((c["signal"], c["evidence"]["gate"]), ("S2", "guard"))

    def test_a_gate_green_from_the_start_records_nothing(self):
        (self.root / "ok").write_text("", encoding="utf-8")
        self.script("run-local-gates.py", expect=0)
        self.script("run-local-gates.py", expect=0)
        self.assertEqual(self.signals(), [])


if __name__ == "__main__":
    unittest.main()
