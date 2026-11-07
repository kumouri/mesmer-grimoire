"""Zethus waits on a background command by blocking on the output read, and the stop guard agrees.

Ceryce's report, 2026-11-06 (paraphrased): a Copilot CLI session ran a few-minute install as a
background shell, and the model spent its reasoning working out how to wait, because the kit had no
rule. These tests pin the rule in every prompt, the real tool name in the Copilot copy, the guard's
treatment of the report after the wait bound (allowed) and of a bare "waiting on the background job"
(refused), and the record's correction.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "zethus"
CANONICAL = KIT / "com.github.copilot" / "agents" / "zethus.agent.md"
MIRROR = KIT / "agents" / "zethus.agent.md"
AGREEMENT = KIT / "copilot-instructions.md"
RECORD = KIT / "docs" / "never-stop-silently.md"
GUARD = KIT / "com.github.copilot" / "hooks" / "stop_guard.py"

spec = importlib.util.spec_from_file_location("stop_guard_wait", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


class RulePresent(unittest.TestCase):
    def test_agent_and_mirror_say_how_to_wait(self):
        for path in (CANONICAL, MIRROR):
            text = flat(path)
            for phrase in ("Waiting on a background command is work, not a stop",
                           "`read_powershell`", "long `delay`", "until the command exits",
                           "Don't end the turn", "30 minutes of waiting",
                           "A background command outlived the wait bound"):
                self.assertIn(phrase, text, f"{path.name}: {phrase}")

    def test_the_stop_table_has_the_bound_row(self):
        table = CANONICAL.read_text(encoding="utf-8").split(
            "You end a turn only at one of these points:", 1)[1].split("\n\n", 2)[1]
        self.assertIn("A background command outlived the wait bound", table)

    def test_working_agreement_carries_the_short_form(self):
        text = flat(AGREEMENT)
        for phrase in ("still running in the background is not a stop", "`read_powershell`",
                       "without narrating each wait"):
            self.assertIn(phrase, text)

    def test_the_record_is_corrected_by_addition(self):
        text = flat(RECORD)
        self.assertIn("nothing in the kit runs in the background", text.replace("\n", " "),
                      "the original sentence stays; the history is added to, not rewritten")
        self.assertIn("correction, 2026-11-06", text)
        self.assertIn("## Addendum, 2026-11-06: waiting on a background command", RECORD.read_text(encoding="utf-8"))


STOP_WITH_BOUND = ("Stage 3 · Implement — Phase 0, step 2 of 4: install dependencies\n\n"
                   "The install is still running.\n\n"
                   "Stopped at: Stage 3 · Implement — step 2 of 4\n"
                   "Next: Stage 3 · Implement — step 3, run the tests once the install exits\n"
                   "Why: the install is still running in the background after I waited 30 minutes")
BARE_WAIT = ("Stage 3 · Implement — Phase 0, step 2 of 4: install dependencies\n\n"
             "The install is running in the background.\n\n"
             "Stopped at: Stage 3 · Implement — step 2 of 4\n"
             "Next: Stage 3 · Implement — step 3, run the tests\n"
             "Why: waiting for the background install to finish")
NO_STOP_BLOCK = ("Stage 3 · Implement — Phase 0, step 2 of 4\n\n"
                 "I started the install in the background and will check back later.")


class StopGuardAndBackground(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sid = f"w{os.getpid()}-{id(self)}"
        counter = guard.refusals_file({"sessionId": self.sid})
        counter.unlink(missing_ok=True)
        self.addCleanup(counter.unlink, missing_ok=True)

    def event(self, reply: str) -> dict:
        path = Path(self.tmp.name) / "transcript.jsonl"
        rows = [{"type": "user.message", "data": {"content": "go"}},
                {"type": "assistant.message", "data": {"content": reply}}]
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return {"sessionId": self.sid, "transcriptPath": str(path)}

    def test_the_report_after_the_bound_is_a_real_stop(self):
        self.assertTrue(guard.is_real_stop(STOP_WITH_BOUND))
        self.assertEqual(guard.refuse(self.event(STOP_WITH_BOUND), STOP_WITH_BOUND), "")
        self.assertEqual(guard.remind(self.event(STOP_WITH_BOUND)), "")

    def test_a_bare_wait_is_still_the_silent_stop(self):
        self.assertFalse(guard.is_real_stop(BARE_WAIT))
        out = json.loads(guard.refuse(self.event(BARE_WAIT), BARE_WAIT))
        self.assertEqual(out["decision"], "block")
        self.assertIn("read_powershell", out["reason"])
        self.assertIn("not a stop", out["reason"])

    def test_a_duration_alone_opens_no_door(self):
        """A stated duration only counts when the Why names the running command."""
        reply = STOP_WITH_BOUND.replace(
            "the install is still running in the background after I waited 30 minutes",
            "phase 0 is committed and green; I waited 30 minutes for the gates")
        self.assertFalse(guard.is_real_stop(reply))

    def test_no_stop_block_about_a_background_command_is_refused_with_the_wait_reason(self):
        out = json.loads(guard.refuse(self.event(NO_STOP_BLOCK), NO_STOP_BLOCK))
        self.assertIn("block on the harness's output read", out["reason"])

    def test_the_next_prompt_reminder_says_to_resume_the_wait(self):
        out = json.loads(guard.remind(self.event(BARE_WAIT)))
        self.assertIn("resume the wait", out["additionalContext"])

    def test_refusals_stay_bounded(self):
        ev = self.event(BARE_WAIT)
        results = [guard.refuse(ev, BARE_WAIT) for _ in range(guard.MAX_REFUSALS + 1)]
        self.assertEqual([bool(r) for r in results], [True] * guard.MAX_REFUSALS + [False])


if __name__ == "__main__":
    unittest.main()
