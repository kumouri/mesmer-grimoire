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
                           "`read_powershell`", "`delay: 600`", "until the command exits",
                           "never thinking with neither",
                           "Don't end the turn", "30 minutes of waiting",
                           "A background command outlived the wait bound"):
                self.assertIn(phrase, text, f"{path.name}: {phrase}")

    def test_the_stop_table_has_the_bound_row(self):
        table = CANONICAL.read_text(encoding="utf-8").split(
            "You end a turn only at one of these points:", 1)[1].split("\n\n", 2)[1]
        self.assertIn("A background command outlived the wait bound", table)
        self.assertIn("The person moved a command to the background", table)

    def test_working_agreement_carries_the_short_form(self):
        text = flat(AGREEMENT)
        for phrase in ("still running in the background is not a stop", "`read_powershell`",
                       "`delay: 600`", "without narrating each wait", "never thinking with neither",
                       "the person moved the command to the background"):
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


PROGRESS = ("Stage 3 · Implement — merge upstream into the fork's develop\n\n"
            "Starting the merge; it may take a while.")
MOVED = ("<command with shellId: 16 moved to background by the user. The user has already seen a UI "
         "confirmation — do NOT respond to them about this and do NOT call any more tools for this "
         "command. Wait for the user's next instruction.>")
COMPLETED = {"type": "system.notification",
             "data": {"content": "<system_notification>\nShell command \"Merge upstream\" (shellId: 16) "
                                 "has completed.\n</system_notification>",
                      "kind": {"type": "shell_completed", "shellId": "16", "exitCode": 1}}}


class PersonMovedTheCommand(unittest.TestCase):
    """Ceryce's report, 2026-11-11 (paraphrased): the person moved a merge to the background, the
    Copilot CLI told the model not to call tools for it, the kit told it not to end the turn, and it
    thought in circles with no tool call. Rows below follow the CLI's ``events.jsonl`` (1.0.110-1)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sid = f"m{os.getpid()}-{id(self)}"
        counter = guard.refusals_file({"sessionId": self.sid})
        counter.unlink(missing_ok=True)
        self.addCleanup(counter.unlink, missing_ok=True)

    def event(self, tool_result: str | None, *after: dict, prompt: str = "") -> dict:
        """A progress message, the merge started, the given result for it, then a silent end."""
        rows = [{"type": "user.message", "data": {"content": "merge upstream"}},
                {"type": "assistant.message", "data": {"content": PROGRESS, "toolRequests": [
                    {"toolCallId": "c1", "name": "powershell", "arguments": {"command": "git merge up"}}]}},
                {"type": "tool.execution_start",
                 "data": {"toolCallId": "c1", "toolName": "powershell", "arguments": {"command": "git merge up"}}}]
        if tool_result is not None:
            rows.append({"type": "tool.execution_complete",
                         "data": {"toolCallId": "c1", "success": True, "result": {"content": tool_result}}})
        rows.append({"type": "assistant.message", "data": {"content": "", "toolRequests": []}})
        rows.extend(after)
        path = Path(self.tmp.name) / "events.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return {"sessionId": self.sid, "transcriptPath": str(path), "prompt": prompt}

    def test_the_silent_stop_is_let_through_while_the_person_moved_command_runs(self):
        ev = self.event(MOVED)
        self.assertTrue(guard.person_moved_wait(ev))
        self.assertEqual(guard.refuse(ev, guard.last_reply(ev)), "")
        self.assertEqual(guard.remind(ev), "")

    def test_the_same_stop_without_the_move_is_still_refused(self):
        """The control: a background command the model started is still a wait on the read."""
        ev = self.event("<command started in background with shellId: 16>")
        self.assertFalse(guard.person_moved_wait(ev))
        out = json.loads(guard.refuse(ev, guard.last_reply(ev)))
        self.assertEqual(out["decision"], "block")

    def test_the_exception_closes_when_the_command_completes(self):
        ev = self.event(MOVED, COMPLETED, {"type": "assistant.message", "data": {"content": PROGRESS}})
        self.assertFalse(guard.person_moved_wait(ev))
        self.assertEqual(json.loads(guard.refuse(ev, guard.last_reply(ev)))["decision"], "block")

    def test_a_final_read_also_closes_it(self):
        read = {"type": "tool.execution_complete",
                "data": {"toolCallId": "c9", "result": {"content": "x\n<shellId: 16 completed with exit code 1>"}}}
        self.assertFalse(guard.person_moved_wait(self.event(MOVED, read)))

    def test_the_other_wordings_for_a_person_moved_command(self):
        off_turn = ("<command with shellId: 16 is running in the background after the user moved it off "
                    "the main turn. Respond to the user now and stop calling tools for this command — you "
                    "will be notified when it completes.>")
        self.assertTrue(guard.person_moved_wait(self.event(off_turn)))
        steered_read = [{"type": "tool.execution_start",
                         "data": {"toolCallId": "r1", "toolName": "read_powershell",
                                  "arguments": {"shellId": "16", "delay": 600}}},
                        {"type": "tool.execution_complete",
                         "data": {"toolCallId": "r1", "result": {
                             "content": "Read interrupted by user steering; shell continues in background."}}}]
        ev = self.event("<command started in background with shellId: 16>", *steered_read)
        self.assertTrue(guard.person_moved_wait(ev), "the shell id comes from the read's arguments")
        self.assertFalse(guard.person_moved_wait(self.event(
            "<command started in background with shellId: 16>", *steered_read, COMPLETED)))

    def test_a_model_cannot_claim_the_exception_in_words(self):
        reply = (PROGRESS + "\n\nStopped at: Stage 3\nNext: resolve the merge\n"
                 "Why: the person moved the command to the background")
        ev = self.event("<command started in background with shellId: 16>")
        self.assertFalse(guard.person_moved_wait(ev))
        self.assertTrue(guard.refuse(ev, reply))

    def test_the_completion_notification_prompt_gets_no_reminder(self):
        bare_wait = {"type": "assistant.message", "data": {"content": BARE_WAIT}}
        typed = self.event(None, bare_wait, prompt="what's happening?")
        self.assertIn("resume the wait", json.loads(guard.remind(typed))["additionalContext"])
        notified = self.event(None, bare_wait, prompt=COMPLETED["data"]["content"])
        self.assertEqual(guard.remind(notified), "")


if __name__ == "__main__":
    unittest.main()
