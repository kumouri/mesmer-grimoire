"""Zethus doesn't end a turn at a progress point (``zethus/docs/never-stop-silently.md``).

Ceryce's report, 2026-11-03 (paraphrased): a session ended after Phase 0 with an update that the phase
was committed and the gates green, and never started Phase 1. Prose already said so; these tests pin
the rule in every generated prompt, that no stop-and-report wording at a phase boundary remains, and
that the ``agentStop`` guard refuses such a turn, boundedly.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "zethus"
CANONICAL = KIT / "com.github.copilot" / "agents" / "zethus.agent.md"
MIRROR = KIT / "agents" / "zethus.agent.md"
GUARD = KIT / "com.github.copilot" / "hooks" / "stop_guard.py"

spec = importlib.util.spec_from_file_location("stop_guard", GUARD)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

RULE_PHRASES = (
    "a progress update",
    "approval wall",
    "can't answer with a citation",
    "Gather every wall, then present them together",
    "keep doing every other piece of work",
    "Committed and green is not done",
)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def prompts() -> dict[str, str]:
    return {"agent": CANONICAL.read_text(encoding="utf-8"),
            "agent (plugin-root mirror)": MIRROR.read_text(encoding="utf-8"),
            "working agreement": (KIT / "copilot-instructions.md").read_text(encoding="utf-8")}


class RulePresent(unittest.TestCase):
    def test_agent_and_mirror_carry_the_whole_rule(self):
        for name in ("agent", "agent (plugin-root mirror)"):
            text = flat(prompts()[name]).lower()
            for phrase in RULE_PHRASES:
                self.assertIn(flat(phrase).lower(), text, f"{name}: {phrase}")

    def test_working_agreement_carries_the_short_form(self):
        text = flat(prompts()["working agreement"])
        for phrase in ("never a stop", "progress update never ends a turn", "approval wall",
                       "can't answer with a citation", "present all of those together",
                       "unpushed means push"):
            self.assertIn(phrase, text)

    def test_the_stop_table_names_both_walls_and_the_goal(self):
        agent = prompts()["agent"]
        table = agent.split("You end a turn only at one of these points:", 1)[1].split("\n\n", 2)[1]
        for row in ("approval wall", "A question you can't answer with a citation", "The goal is complete"):
            self.assertIn(row, table)
        self.assertNotIn("| The PR is open and the spec has no further phase |", table,
                         "the old row assumed the push and PR had happened")

    def test_sign_off_gates_are_untouched(self):
        agent = flat(prompts()["agent"])
        self.assertIn("**A person has explicitly signed off.**", agent)
        self.assertIn("a person still merges", agent)
        self.assertIn("This removes no approval", agent)

    def test_no_phase_boundary_stop_and_report_wording(self):
        """No prompt or stage skill tells the agent to stop, report or check in after a phase, a
        commit or a green gate."""
        bad = re.compile(r"(?i)\b(stop|pause|wait|check in|report back|hand (?:it )?back)\b[^.\n]{0,60}"
                         r"\b(after|once|when)\b[^.\n]{0,40}\b(phase|commit(?:ted)?|gates?)\b")
        files = list(prompts().items()) + [
            (p.parent.name, p.read_text(encoding="utf-8")) for p in (KIT / "skills").glob("*/SKILL.md")]
        for name, text in files:
            for m in bad.finditer(text):
                self.fail(f"{name}: {m.group(0)!r}")

    def test_session_start_announces_the_plugin_version(self):
        hook = KIT / "com.github.copilot" / "hooks" / "session_start.py"
        out = subprocess.run([sys.executable, str(hook)], input=json.dumps({"cwd": tempfile.gettempdir()}),
                             capture_output=True, text=True)
        version = json.loads((KIT / "plugin.json").read_text(encoding="utf-8"))["version"]
        self.assertIn(f"Plugin version: {version}", json.loads(out.stdout)["additionalContext"])


STOP = "Stopped at: Stage 2 · Spec\nNext: Stage 3\nWhy: waiting for your sign-off on the spec"
PROGRESS = ("Stage 3 · Implement — Phase 0 done\n\nPhase 0 is committed with no errors and passed the "
            "local gates.\nNext: Phase 1, step 1: write the test that pins the retry delay")


class StopGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sid = f"t{os.getpid()}-{id(self)}"
        counter = guard.refusals_file({"sessionId": self.sid})
        counter.unlink(missing_ok=True)
        self.addCleanup(counter.unlink, missing_ok=True)

    def event(self, reply: str) -> dict:
        path = Path(self.tmp.name) / "transcript.jsonl"
        rows = [{"type": "user.message", "data": {"content": "go"}},
                {"type": "assistant.message", "data": {"content": reply}}]
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return {"sessionId": self.sid, "transcriptPath": str(path)}

    def test_refuses_a_progress_report_and_names_the_next_action(self):
        out = json.loads(guard.refuse(self.event(PROGRESS), PROGRESS))
        self.assertEqual(out["decision"], "block")
        self.assertIn("Phase 1, step 1", out["reason"])

    def test_lets_a_real_stop_through(self):
        reply = "Stage 2 · Spec\n" + STOP
        self.assertEqual(guard.refuse(self.event(reply), reply), "")

    def test_a_why_that_only_reports_progress_is_not_a_stop(self):
        reply = "Stage 3 · x\nStopped at: Phase 0\nNext: Phase 1\nWhy: phase 0 is committed and green"
        self.assertTrue(guard.refuse(self.event(reply), reply))

    def test_ignores_turns_that_are_not_zethus(self):
        self.assertEqual(guard.refuse(self.event("All done."), "All done."), "")

    def test_is_bounded_so_it_cannot_trap_a_session(self):
        ev = self.event(PROGRESS)
        results = [guard.refuse(ev, PROGRESS) for _ in range(guard.MAX_REFUSALS + 2)]
        self.assertEqual([bool(r) for r in results], [True] * guard.MAX_REFUSALS + [False, False])

    def test_reads_the_transcript_and_fails_open(self):
        self.assertEqual(guard.last_reply(self.event(PROGRESS)), PROGRESS)
        self.assertEqual(guard.last_reply({"transcriptPath": "/no/such/file"}), "")
        r = subprocess.run([sys.executable, str(GUARD), "stop"], input="not json",
                           capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_main_blocks_end_to_end_and_prompt_mode_reminds(self):
        ev = json.dumps(self.event(PROGRESS))
        r = subprocess.run([sys.executable, str(GUARD), "stop"], input=ev, capture_output=True, text=True)
        self.assertEqual(json.loads(r.stdout)["decision"], "block")
        r = subprocess.run([sys.executable, str(GUARD), "prompt"], input=ev, capture_output=True, text=True)
        self.assertIn("progress point", json.loads(r.stdout)["additionalContext"])

    def test_registered_for_both_events_in_both_layouts(self):
        for root in (KIT / "com.github.copilot", KIT):
            hooks = json.loads((root / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
            for event, mode in (("agentStop", "stop"), ("userPromptSubmitted", "prompt")):
                (entry,) = hooks[event]
                for shell in ("bash", "powershell"):
                    self.assertIn("com.github.copilot/hooks/stop_guard.py", entry[shell])
                    self.assertTrue(entry[shell].endswith(f" {mode}"), entry[shell])


if __name__ == "__main__":
    unittest.main()
