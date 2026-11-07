"""Coverage for the session-review skill and its script (``zethus/docs/session-review-guarantee.md``).

Every fixture here is invented in this file, and shaped like what each store really writes (the doc
says how each shape was checked). The ``MARKERS`` stand in for work details: they fill every field an
adapter touches, and none may reach the report, the script's output or any file it writes.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_zethus import KIT, SCRIPTS, FakeHome, frontmatter, install_mod, load, run

mod = load(SCRIPTS / "session-review.py")
SKILL = KIT / "skills" / "session-review" / "SKILL.md"
DOC = KIT / "docs" / "session-review-guarantee.md"

MARKERS = {
    "ask": "ZZASKMARKER", "say": "ZZSAYMARKER", "command": "ZZCOMMANDMARKER", "error": "ZZERRORMARKER",
    "file": "zzfilemarker.py", "path": "/srv/zzpathmarker/app", "repo": "zzrepomarker", "branch": "zzbranchmarker",
    "sid": "zzsessionidmarker", "title": "ZZTITLEMARKER", "user": "zzusernamemarker", "host": "zzhostmarker",
    "url": "https://zzurlmarker.example.com/x", "tool": "zzmcpmarker-lookup_thing", "model": "zzmodelmarker",
    "old": "ZZOLDMARKER", "new": "ZZNEWMARKER",
}
MARKER_RE = re.compile("|".join(("zzaskmarker", "zzsaymarker", "zzcommandmarker", "zzerrormarker", "zzfilemarker",
                                 "zzpathmarker", "zzrepomarker", "zzbranchmarker", "zzsessionidmarker", "zztitlemarker",
                                 "zzusernamemarker", "zzhostmarker", "zzurlmarker", "zzmcpmarker", "lookup_thing",
                                 "zzmodelmarker", "zzoldmarker", "zznewmarker")), re.I)
START = 1_790_000_000.0     # an arbitrary moment; dates are compared through the same conversion


def iso(seconds: float) -> str:
    return dt.datetime.fromtimestamp(START + seconds, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Cop:
    """Builds a Copilot CLI ``events.jsonl`` the shape a real session wrote."""

    def __init__(self):
        self.rows, self.t, self.n = [], 0.0, 0

    def row(self, type_: str, data: dict, gap: float = 1.0):
        self.t += gap
        self.rows.append({"type": type_, "timestamp": iso(self.t), "data": data})
        return self

    def ask(self, text: str, gap: float = 1.0):
        return self.row("user.message", {"content": text, "transformedContent": text}, gap)

    def say(self, text: str, final: bool = True, gap: float = 1.0):
        self.row("assistant.message", {"content": text, "toolRequests": [] if final else [{"name": "x"}]}, gap)
        return self.row("assistant.turn_end", {"turnId": "0"}, 0) if final else self

    def tool(self, name: str, args: dict | None = None, exit_code: int | None = None, output: str = "",
             success: bool = True, gap: float = 1.0, duration: float = 1.0, complete: bool = True):
        self.n += 1
        call = f"call{self.n}"
        self.row("tool.execution_start", {"toolCallId": call, "toolName": name, "arguments": args or {}}, gap)
        if complete:
            data = {"toolCallId": call, "success": success, "result": {"content": output}}
            if exit_code is not None:
                data["shellExecution"] = {"exitCode": exit_code}
            self.row("tool.execution_complete", data, duration)
        return self

    def shell(self, command: str, exit_code: int = 0, output: str = "", **kw):
        return self.tool("powershell", {"command": command}, exit_code, output, **kw)

    def edit(self, path: str = "src/a.py", old: str = "a", new: str = "b", **kw):
        return self.tool("edit", {"path": path, "old_str": old, "new_str": new}, **kw)

    def text(self) -> str:
        return "\n".join(json.dumps(r) for r in self.rows) + "\n"


class Store(FakeHome):
    """A fake home with stores in it, and helpers to run the script against them."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for var in ("COPILOT_HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "APPDATA"):
            os.environ.pop(var, None)
        self.out = Path(self._tmp.name) / "out"
        self.out.mkdir()
        self.report = self.out / "report.md"
        self.count = 0

    def copilot_session(self, body: "str | Cop", sid: str | None = None, age: int = 0) -> Path:
        self.count += 1
        folder = self.copilot / "session-state" / (sid or f"s{self.count}")
        folder.mkdir(parents=True)
        path = folder / "events.jsonl"
        path.write_text(body.text() if isinstance(body, Cop) else body, encoding="utf-8")
        stamp = START - age
        os.utime(path, (stamp, stamp))
        return path

    def scan(self, *argv: str) -> tuple[int, str]:
        return run(mod, "scan", *argv)

    def scan_all(self, *argv: str) -> tuple[int, str]:
        return self.scan("--select", "all", "--output", str(self.report), *argv)

    def text(self) -> str:
        return self.report.read_text(encoding="ascii")

    def analysed(self, *bodies: Cop) -> tuple[dict, list]:
        sessions = [self.read(b, i + 1) for i, b in enumerate(bodies)]
        return mod.analyse(sessions)[0], sessions

    def read(self, body: Cop, label: int = 1) -> "mod.Session":
        path = self.copilot_session(body)
        session, _ = mod.read_session(mod.Candidate(mod.STORES[0], [path]), label, 600)
        return session

    def count_of(self, key: str, *bodies: Cop) -> int:
        return sum(self.analysed(*bodies)[0][key].values())


# ------------------------------------------------------------------------------- adapters

class Adapters(Store):
    def only_session(self, store: str) -> "mod.Session":
        found = mod.discover([store], {})
        self.assertEqual(len(found), 1, store)
        session, _ = mod.read_session(found[0], 1, 600)
        return session

    def test_copilot_a_nonzero_exit_fails_even_though_success_says_true(self):
        """On the real store, a command exiting 128 is logged with ``success: true``."""
        self.copilot_session(Cop().ask("run it").shell("git x", 128, "fatal\n<shellId: 0 completed with exit code 128>").say("no"))
        act = self.only_session("copilot-cli").exchanges[0].actions[0]
        self.assertEqual((act.category, act.outcome), (mod.SHELL, mod.FAILED))

    def test_copilot_reads_the_exit_trailer_when_there_is_no_shell_field(self):
        self.copilot_session(Cop().ask("x").tool("bash", {"command": "y"}, output="z\n<shellId: 2 completed with exit code 3>"))
        self.assertEqual(self.only_session("copilot-cli").exchanges[0].actions[0].outcome, mod.FAILED)

    def test_copilot_a_program_printing_exit_code_is_not_a_failure(self):
        self.copilot_session(Cop().ask("x").shell("y", 0, "the exit code 3 was expected"))
        self.assertEqual(self.only_session("copilot-cli").exchanges[0].actions[0].outcome, mod.OK)

    def test_copilot_home_override_is_read(self):
        other = Path(self._tmp.name) / "elsewhere"
        (other / "session-state" / "s").mkdir(parents=True)
        (other / "session-state" / "s" / "events.jsonl").write_text(Cop().ask("x").text(), encoding="utf-8")
        with mock.patch.dict(os.environ, {"COPILOT_HOME": str(other)}):
            self.assertEqual(len(mod.discover(["copilot-cli"], {})), 1)

    def test_copilot_subagent_calls_are_not_the_session_agents(self):
        cop = Cop().ask("x")
        cop.row("tool.execution_start", {"toolCallId": "n", "toolName": "edit", "parentToolCallId": "p", "arguments": {}})
        self.copilot_session(cop.say("ok"))
        self.assertEqual(self.only_session("copilot-cli").exchanges[0].actions, [])

    def test_jetbrains_partitions_read_in_order_as_one_session(self):
        folder = self.copilot / "jb" / "sess"
        folder.mkdir(parents=True)
        first = Cop().row("partition.created", {}).row("user.message_rendered", {"content": "fix it"})
        second = Cop()
        second.t = 50
        second.shell("pytest", 0).say("done")
        (folder / "partition-10.jsonl").write_text(second.text(), encoding="utf-8")
        (folder / "partition-2.jsonl").write_text(first.text(), encoding="utf-8")
        session = self.only_session("jetbrains")
        self.assertEqual(session.reading, mod.READ_UNVERIFIED)
        self.assertEqual([ex.ask for ex in session.exchanges], [mod.CHANGE])
        self.assertEqual(session.exchanges[0].actions[0].category, mod.SHELL)

    def test_jetbrains_rendered_and_plain_spellings_count_once(self):
        folder = self.copilot / "jb" / "sess"
        folder.mkdir(parents=True)
        body = Cop().row("user.message_rendered", {"content": "fix it"}).ask("fix it").say("ok")
        (folder / "partition-1.jsonl").write_text(body.text(), encoding="utf-8")
        self.assertEqual(len(self.only_session("jetbrains").exchanges), 1)

    def vscode_state(self) -> dict:
        terminal = {"kind": "terminal", "commandLine": {"original": "npm test"}, "terminalCommandState": {"exitCode": 1}}
        return {"version": 3, "sessionId": "s", "creationDate": START * 1000, "customTitle": "t", "requests": [{
            "requestId": "r", "timestamp": START * 1000, "message": {"text": "add a flag", "parts": []},
            "response": [{"value": "ok"},
                         {"kind": "toolInvocationSerialized", "toolId": "run_in_terminal", "isComplete": True,
                          "toolSpecificData": terminal},
                         {"kind": "textEditGroup", "uri": {}, "edits": []},
                         {"kind": "markdownContent", "content": {"value": "fine"}}]}]}

    def vscode_folder(self) -> Path:
        folder = self.home / ".config" / "Code" / "User" / "workspaceStorage" / "abc" / "chatSessions"
        folder.mkdir(parents=True)
        return folder

    def check_vscode(self, session):
        self.assertEqual(session.reading, mod.READ_UNVERIFIED)
        ex = session.exchanges[0]
        self.assertEqual(ex.ask, mod.CHANGE)
        self.assertEqual([a.category for a in ex.actions], [mod.SHELL, mod.EDIT])
        self.assertEqual(ex.actions[0].outcome, mod.FAILED)
        self.assertEqual(ex.ended, mod.REPLY)

    def test_vscode_json(self):
        (self.vscode_folder() / "s.json").write_text(json.dumps(self.vscode_state()), encoding="utf-8")
        self.check_vscode(self.only_session("vscode"))

    def test_vscode_mutation_log_replays(self):
        state = self.vscode_state()
        requests = state.pop("requests")
        response = requests[0].pop("response")
        lines = [{"kind": 0, "v": {**state, "requests": []}},
                 {"kind": 2, "k": ["requests"], "v": [{**requests[0], "response": []}]},
                 {"kind": 2, "k": ["requests", 0, "response"], "v": response},
                 {"kind": 1, "k": ["customTitle"], "v": "renamed"},
                 {"kind": 3, "k": ["sessionId"]}]
        (self.vscode_folder() / "s.jsonl").write_text("\n".join(map(json.dumps, lines)), encoding="utf-8")
        self.check_vscode(self.only_session("vscode"))

    def test_vscode_finds_the_windows_folder_too(self):
        appdata = self.home / "AppData" / "Roaming"
        folder = appdata / "Code" / "User" / "globalStorage" / "emptyWindowChatSessions"
        folder.mkdir(parents=True)
        (folder / "s.json").write_text(json.dumps(self.vscode_state()), encoding="utf-8")
        with mock.patch.dict(os.environ, {"APPDATA": str(appdata)}):
            self.assertEqual(len(mod.discover(["vscode"], {})), 1)

    def claude_rows(self) -> list[dict]:
        base = {"sessionId": "s", "cwd": "/x", "gitBranch": "b", "version": "2"}
        def row(type_, content, t, **kw):
            return {**base, "type": type_, "timestamp": iso(t), "message": {"content": content, **kw.pop("message", {})}, **kw}
        return [
            {"type": "queue-operation", "operation": "enqueue", "timestamp": iso(0)},
            row("user", "fix the thing", 1),
            row("user", "<system-reminder>not an ask</system-reminder>", 1, isMeta=True),
            row("assistant", [{"type": "tool_use", "id": "a", "name": "Bash", "input": {"command": "pytest"}}], 2,
                message={"stop_reason": "tool_use"}),
            row("user", [{"type": "tool_result", "tool_use_id": "a", "is_error": True, "content": "Exit code 2\nboom"}], 3),
            row("assistant", [{"type": "tool_use", "id": "b", "name": "Edit",
                               "input": {"file_path": "/x/a.py", "old_string": "a", "new_string": "b"}}], 4),
            row("user", [{"type": "tool_result", "tool_use_id": "b", "content": "done"}], 5),
            row("assistant", [{"type": "text", "text": "all done"}], 6, message={"stop_reason": "end_turn"}),
            row("assistant", [{"type": "text", "text": "side work"}], 7, isSidechain=True),
            row("user", [{"type": "text", "text": "[Request interrupted by user]"}], 8),
        ]

    def write_claude(self, rows: list[dict]) -> None:
        folder = self.home / ".claude" / "projects" / "proj"
        folder.mkdir(parents=True)
        (folder / "s.jsonl").write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")

    def test_claude_code(self):
        self.write_claude(self.claude_rows())
        session = self.only_session("claude-code")
        self.assertEqual(session.reading, mod.READ_OK)
        self.assertEqual(len(session.exchanges), 1, "a meta line and a tool result aren't asks")
        ex = session.exchanges[0]
        self.assertEqual([a.category for a in ex.actions], [mod.SHELL, mod.EDIT])
        self.assertEqual(ex.actions[0].outcome, mod.FAILED)
        self.assertEqual(ex.actions[1].outcome, mod.OK)
        self.assertEqual(ex.ended, mod.INTERRUPTED)

    def test_claude_subagent_logs_are_not_sessions(self):
        self.write_claude(self.claude_rows())
        (self.home / ".claude" / "projects" / "proj" / "agent-1.jsonl").write_text("{}", encoding="utf-8")
        self.assertEqual(len(mod.discover(["claude-code"], {})), 1)

    def codex_file(self, rows: list[dict]) -> None:
        folder = self.home / ".codex" / "sessions" / "2026" / "11" / "06"
        folder.mkdir(parents=True)
        (folder / "rollout-2026-11-06T00-00-00-abc.jsonl").write_text("\n".join(map(json.dumps, rows)), encoding="utf-8")

    def test_codex_current_shape(self):
        def ev(t, **payload):
            return {"timestamp": iso(t), "type": "event_msg", "payload": payload}
        def item(t, **it):
            return ev(t, type="item_completed", item=it, started_at_ms=(START + t) * 1000, completed_at_ms=(START + t + 1) * 1000)
        self.codex_file([
            {"timestamp": iso(0), "type": "session_meta", "payload": {"id": "x", "cwd": "/x"}},
            {"timestamp": iso(1), "type": "response_item", "payload": {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "<environment_context>x</environment_context>"}]}},
            {"timestamp": iso(1), "type": "response_item", "payload": {"type": "message", "role": "user", "content": [
                {"type": "input_text", "text": "fix the thing"}]}},
            item(1, type="UserMessage", content=[{"type": "text", "text": "fix the thing"}]),
            {"timestamp": iso(2), "type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec",
                                                                       "call_id": "c", "input": "wrapper"}},
            item(2, type="CommandExecution", parsed_cmd=[{"type": "unknown", "cmd": "git nope"}], status="failed",
                 aggregated_output="fatal", exit_code=1, command=["pwsh", "-Command", "git nope"]),
            {"timestamp": iso(3), "type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch",
                                                                       "call_id": "p", "input": "*** Begin Patch\n*** Update File: a.md\n"}},
            {"timestamp": iso(4), "type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "p", "output": "ok"}},
            item(5, type="AgentMessage", content=[{"type": "Text", "text": "DONE"}]),
            {"timestamp": iso(5), "type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": "DONE"}]}},
            ev(6, type="task_complete", last_agent_message="DONE"),
        ])
        session = self.only_session("codex")
        self.assertEqual(session.reading, mod.READ_OK)
        self.assertEqual(len(session.exchanges), 1, "the mirrors count once")
        ex = session.exchanges[0]
        self.assertEqual([a.category for a in ex.actions], [mod.SHELL, mod.EDIT])
        self.assertEqual(ex.actions[0].outcome, mod.FAILED)
        self.assertTrue(ex.actions[1].doc_only, "the path is read out of the patch text")
        self.assertEqual(ex.ended, mod.REPLY)

    def test_codex_older_shape(self):
        def ev(t, **payload):
            return {"timestamp": iso(t), "type": "event_msg", "payload": payload}
        self.codex_file([
            {"timestamp": iso(0), "type": "session_meta", "payload": {"id": "x"}},
            ev(1, type="user_message", message="what is this?"),
            {"timestamp": iso(2), "type": "response_item", "payload": {"type": "function_call", "name": "shell",
                                                                       "arguments": json.dumps({"command": ["bash", "-c", "ls"]}), "call_id": "c"}},
            ev(3, type="exec_command_end", command=["bash", "-c", "ls"], exit_code=0, aggregated_output="a"),
            ev(4, type="agent_message", message="it is a thing"),
            ev(5, type="turn_aborted"),
        ])
        ex = self.only_session("codex").exchanges[0]
        self.assertEqual(ex.ask, mod.QUESTION)
        self.assertEqual(len(ex.actions), 1)
        self.assertEqual(ex.ended, mod.INTERRUPTED)


class Categories(unittest.TestCase):
    def test_tools_map_to_a_category_and_anything_else_is_other(self):
        for tool, want in (("powershell", mod.SHELL), ("Bash", mod.SHELL), ("view", mod.READ), ("Read", mod.READ),
                           ("edit", mod.EDIT), ("apply_patch", mod.EDIT), ("Grep", mod.SEARCH), ("WebFetch", mod.WEB),
                           ("acme-search", mod.OTHER), ("mcp__secret__edit", mod.OTHER), ("", mod.OTHER)):
            self.assertEqual(mod.action(tool, None).category, want, tool)

    def test_an_action_holds_no_string_from_its_input(self):
        act = mod.action(MARKERS["tool"], 1.0, command=MARKERS["command"], path=MARKERS["path"],
                         output=MARKERS["error"], failed=True, before=MARKERS["old"], after=MARKERS["new"])
        self.assertIsNone(MARKER_RE.search(repr(act)))


# ------------------------------------------------------------------------------- pairing

class Pairing(unittest.TestCase):
    def test_ask_kinds(self):
        for text, want in (("Why does this fail?", mod.QUESTION), ("what is the retry limit", mod.QUESTION),
                           ("does it build?", mod.QUESTION), ("Fix the retry loop", mod.CHANGE),
                           ("Can you fix the retry loop?", mod.CHANGE), ("please add a flag", mod.CHANGE),
                           ("Run the tests", mod.RUN), ("could you check the build", mod.RUN),
                           ("stop", mod.STOP), ("wait, hold on", mod.STOP), ("No, that's the wrong file", mod.CORRECTION),
                           ("that's not what I meant", mod.CORRECTION), ("don't use that helper", mod.CORRECTION),
                           ("do the migration", mod.UNCLASSIFIED), ("bonjour tout le monde", mod.UNCLASSIFIED)):
            self.assertEqual(mod.classify_ask(text), want, text)

    def test_a_long_instruction_opening_with_stop_is_not_a_stop(self):
        text = "stop using the old client and move every caller over to the new one across the whole module"
        self.assertNotEqual(mod.classify_ask(text), mod.STOP)

    def ev(self, kind, ts=None, text="", act=None):
        return mod.Ev(kind, ts, text, act)

    def test_splits_on_asks_and_drops_what_came_before_the_first(self):
        exchanges = mod.pair([
            self.ev(mod.SAY, 0, "startup noise"),
            self.ev(mod.ASK, 1, "fix it"),
            self.ev(mod.ACT, act=mod.action("edit", 2.0, 3.0)),
            self.ev(mod.SAY, 4, "fixed"),
            self.ev(mod.ASK, 5, "why?"),
            self.ev(mod.SAY, 6, "because"),
        ], 600)
        self.assertEqual([ex.ask for ex in exchanges], [mod.CHANGE, mod.QUESTION])
        self.assertEqual(len(exchanges[0].actions), 1)
        self.assertEqual(exchanges[0].ended, mod.REPLY)
        self.assertTrue(exchanges[0].claims_done)

    def test_endings(self):
        act = mod.action("edit", 2.0, 3.0)
        silent = mod.pair([self.ev(mod.ASK, 1, "x"), self.ev(mod.ACT, act=act), self.ev(mod.ASK, 5, "y")], 600)
        self.assertEqual(silent[0].ended, mod.SILENT)
        self.assertEqual(silent[1].ended, mod.OPEN, "an ask with nothing after it is still open")
        at_eof = mod.pair([self.ev(mod.ASK, 1, "x"), self.ev(mod.ACT, act=act)], 600)
        self.assertEqual(at_eof[0].ended, mod.OPEN, "a file that just ends can't show why")
        broke = mod.pair([self.ev(mod.ASK, 1, "x"), self.ev(mod.ACT, act=act), self.ev(mod.BREAK, 9)], 600)
        self.assertEqual(broke[0].ended, mod.INTERRUPTED)
        self.assertEqual(broke[0].break_gap, 6.0)

    def test_an_exchange_holds_no_text(self):
        exchanges = mod.pair([self.ev(mod.ASK, 1, MARKERS["ask"]), self.ev(mod.SAY, 2, MARKERS["say"])], 600)
        self.assertIsNone(MARKER_RE.search(repr(exchanges)))


# ------------------------------------------------------------------------------- patterns

class Patterns(Store):
    def test_parser_failure(self):
        fires = Cop().ask("x").shell("if (", 1, "ParserError: \nLine |\n   | Missing closing ')'").say("oops")
        self.assertEqual(self.count_of("parser", fires), 1)
        bash = Cop().ask("x").shell("ls", 2, "bash: syntax error near unexpected token `('").say("oops")
        self.assertEqual(self.count_of("parser", bash), 1)

    def test_parser_failure_negative(self):
        ran_and_failed = Cop().ask("x").shell("pytest", 1, "assertion failed").say("oops")
        program = Cop().ask("x").shell("node a.js", 1, "SyntaxError: Unexpected token").say("oops")
        printed_only = Cop().ask("x").shell("cat notes", 0, "syntax error near unexpected token").say("ok")
        self.assertEqual(self.count_of("parser", ran_and_failed, program, printed_only), 0)

    def test_retry(self):
        fires = Cop().ask("x").shell("npm test", 1, "e").shell("npm test", 1, "e").say("no")
        self.assertEqual(self.count_of("retry", fires), 1)
        tweaked = Cop().ask("x").shell("npm test a", 1, "e").shell("npm test b", 0).say("ok")
        self.assertEqual(self.count_of("retry", tweaked), 1, "same tool and command start")

    def test_retry_negative(self):
        read_between = Cop().ask("x").shell("npm test", 1, "e").tool("view", {"path": "a"}).shell("npm test", 0).say("ok")
        diagnosed = (Cop().ask("x").shell("npm test", 1, "e")
                     .say("The test fails because the fixture it reads is missing, so I will regenerate that first.", final=False)
                     .shell("npm test", 0).say("ok"))
        succeeded_first = Cop().ask("x").shell("npm test", 0).shell("npm test", 0).say("ok")
        other_command = Cop().ask("x").shell("npm test", 1, "e").shell("git status", 0).say("ok")
        self.assertEqual(self.count_of("retry", read_between, diagnosed, succeeded_first, other_command), 0)

    def test_edit_unverified(self):
        fires = Cop().ask("fix it").edit().say("done")
        self.assertEqual(self.count_of("unverified", fires), 1)
        only_git = Cop().ask("fix it").edit().shell("git status").say("done")
        self.assertEqual(self.count_of("unverified", only_git), 1)
        before_only = Cop().ask("fix it").shell("pytest").edit().say("done")
        self.assertEqual(self.count_of("unverified", before_only), 1)

    def test_edit_unverified_negative(self):
        ran = Cop().ask("fix it").edit().shell("pytest").say("done")
        failed_test_still_ran = Cop().ask("fix it").edit().shell("pytest", 1, "e").say("no")
        docs = Cop().ask("fix it").edit("README.md").say("done")
        cut_off = Cop().ask("fix it").edit().row("abort", {})
        self.assertEqual(self.count_of("unverified", ran, failed_test_still_ran, docs, cut_off), 0)

    def test_a_command_the_shell_refused_verifies_nothing(self):
        refused = Cop().ask("fix it").edit().shell("pytest (", 1, "ParserError: x").say("done")
        self.assertEqual(self.count_of("unverified", refused), 1)

    def background(self, cop: Cop) -> Cop:
        return cop.tool("powershell", {"command": "sleep", "mode": "async"}, output="<command started in background with shellId: 2>")

    def test_background_left_running(self):
        """What a real session did: start it async, say DONE, and only then get the notification."""
        fires = self.background(Cop().ask("x")).say("DONE.")
        fires.row("system.notification", {"content": "n", "kind": {"type": "shell_completed", "shellId": "2"}})
        self.assertEqual(self.count_of("background", fires), 1)
        polled_running = self.background(Cop().ask("x")).tool(
            "read_powershell", {"shellId": "2"}, output="<command with shellId: 2 is still running after 5 seconds>").say("later")
        self.assertEqual(self.count_of("background", polled_running), 1)

    def test_background_negative(self):
        waited = self.background(Cop().ask("x")).tool(
            "read_powershell", {"shellId": "2"}, output="\n<shellId: 2 completed with exit code 0>").say("finished")
        notified = self.background(Cop().ask("x"))
        notified.row("system.notification", {"kind": {"type": "shell_completed", "shellId": "2"}}).say("finished")
        foreground = Cop().ask("x").shell("sleep").say("finished")
        self.assertEqual(self.count_of("background", waited, notified, foreground), 0)

    def test_silent_end(self):
        fires = Cop().ask("x").shell("ls").ask("hello?")
        self.assertEqual(self.count_of("silent", fires), 1)

    def test_silent_end_negative(self):
        replied = Cop().ask("x").shell("ls").say("ok").ask("next")
        at_end_of_file = Cop().ask("x").shell("ls")
        interrupted = Cop().ask("x").shell("ls").row("abort", {}).ask("next")
        self.assertEqual(self.count_of("silent", replied, at_end_of_file, interrupted), 0)

    def test_stall(self):
        waiting_on_model = Cop().ask("x").say("late", gap=700)
        long_command = Cop().ask("x").shell("build", duration=700).say("ok")
        self.assertEqual(self.count_of("stall", waiting_on_model), 1)
        self.assertEqual(self.count_of("stall", long_command), 1)

    def test_stall_negative(self):
        user_was_away = Cop().ask("x").say("ok").ask("back", gap=7000).say("ok")
        idle_after_the_turn = Cop().ask("x").say("ok").row("system.notification", {}, gap=7000)
        quick = Cop().ask("x").shell("ls", gap=500, duration=5).say("ok", gap=500)
        self.assertEqual(self.count_of("stall", user_was_away, idle_after_the_turn, quick), 0)

    def test_stall_limit_is_a_parameter(self):
        body = Cop().ask("x").say("late", gap=120)
        path = self.copilot_session(body)
        candidate = mod.Candidate(mod.STORES[0], [path])
        self.assertEqual(mod.read_session(candidate, 1, 60)[0].exchanges[0].stalls, 1)
        self.assertEqual(mod.read_session(candidate, 1, 600)[0].exchanges[0].stalls, 0)

    def test_false_done(self):
        fires = Cop().ask("fix it").shell("pytest", 1, "e").say("All done!")
        self.assertEqual(self.count_of("false_done", fires), 1)

    def test_false_done_negative(self):
        green = Cop().ask("fix it").shell("pytest", 0).say("All done!")
        admitted = Cop().ask("fix it").shell("pytest", 1, "e").say("Done, but the tests failed.")
        no_claim = Cop().ask("fix it").shell("pytest", 1, "e").say("Here is where things stand.")
        recovered = Cop().ask("fix it").shell("pytest", 1, "e").shell("pytest", 0).say("Fixed.")
        self.assertEqual(self.count_of("false_done", green, admitted, no_claim, recovered), 0)

    def test_question_answered_with_edits(self):
        self.assertEqual(self.count_of("question_edit", Cop().ask("why is this slow?").edit().say("there")), 1)

    def test_question_answered_with_edits_negative(self):
        read_only = Cop().ask("why is this slow?").tool("view", {"path": "a"}).say("because")
        asked_for_it = Cop().ask("fix the slow query").edit().say("there")
        self.assertEqual(self.count_of("question_edit", read_only, asked_for_it), 0)

    def test_change_answered_with_only_talk(self):
        talk = Cop().ask("add a retry").say("You could add a retry in the client.")
        read_only = Cop().ask("add a retry").tool("view", {"path": "a"}).say("It goes in the client.")
        self.assertEqual(self.count_of("change_talk", talk, read_only), 2)

    def test_change_answered_with_only_talk_negative(self):
        edited = Cop().ask("add a retry").edit().say("added")
        clarifying = Cop().ask("add a retry").say("Which client do you mean?")
        unanswered = Cop().ask("add a retry").ask("also a flag").edit().say("ok")
        self.assertEqual(self.count_of("change_talk", edited, clarifying, unanswered), 0)

    def test_run_request_not_run(self):
        self.assertEqual(self.count_of("run_not_run", Cop().ask("run the tests").say("They should pass.")), 1)

    def test_run_request_not_run_negative(self):
        self.assertEqual(self.count_of("run_not_run", Cop().ask("run the tests").shell("pytest").say("green")), 0)

    def test_stop_ignored(self):
        self.assertEqual(self.count_of("stop_ignored", Cop().ask("stop").edit().say("ok")), 1)

    def test_stop_ignored_negative(self):
        stopped = Cop().ask("wait").say("Stopped.")
        read_only = Cop().ask("wait").tool("view", {"path": "a"}).say("Stopped.")
        self.assertEqual(self.count_of("stop_ignored", stopped, read_only), 0)

    def test_correction_counts_and_says_after_what_and_how_soon(self):
        body = (Cop().ask("fix it").edit().say("done").ask("No, that's the wrong file", gap=30).say("sorry")
                .ask("fix it").shell("x").row("abort", {}, gap=120).ask("try again"))
        session = self.read(body)
        self.assertEqual(mod.d_correction(session), 2)
        _, prior, soon = mod.analyse([session])
        self.assertEqual((prior[mod.EDIT], prior[mod.SHELL], prior[mod.TALK]), (1, 1, 0))
        self.assertEqual((soon["under1"], soon["under10"]), (1, 1))

    def test_correction_after_an_interrupt_counts_once(self):
        body = Cop().ask("fix it").shell("x").row("abort", {}).ask("no, the other one").say("ok")
        self.assertEqual(mod.d_correction(self.read(body)), 1)

    def test_correction_negative(self):
        self.assertEqual(self.count_of("correction", Cop().ask("fix it").edit().say("ok").ask("thanks, now add a flag").say("ok")), 0)

    def test_flip_flop(self):
        fires = Cop().ask("x").edit(old="A", new="B").edit(old="B", new="A").edit(old="A", new="B").say("ok")
        self.assertEqual(self.count_of("flip", fires), 1)

    def test_flip_flop_negative(self):
        one_revert = Cop().ask("x").edit(old="A", new="B").edit(old="B", new="A").say("ok")
        moving_on = Cop().ask("x").edit(old="A", new="B").edit(old="B", new="C").edit(old="C", new="D").say("ok")
        two_files = Cop().ask("x").edit("a.py", "A", "B").edit("b.py", "B", "A").edit("c.py", "A", "B").say("ok")
        self.assertEqual(self.count_of("flip", one_revert, moving_on, two_files), 0)

    def test_recurring_failure(self):
        one = Cop().ask("x").shell("npm test", 1, "error at line 12").say("no")
        two = Cop().ask("y").shell("npm test", 1, "error at line 99").say("no")
        results, _ = self.analysed(one, two)
        self.assertEqual(results["recurring"], {1: 1, 2: 1})
        self.assertEqual(results["recurring_total"], {0: 1})

    def test_recurring_failure_negative(self):
        once = Cop().ask("x").shell("npm test", 1, "e").say("no")
        different = Cop().ask("y").shell("cargo build", 1, "e2").say("no")
        same_session_only = Cop().ask("z").shell("make", 1, "e3").shell("make", 1, "e3").say("no")
        results, _ = self.analysed(once, different, same_session_only)
        self.assertEqual(results["recurring"], {})


# ------------------------------------------------------------------------------- reading failures

class Unreadable(Store):
    def good(self) -> Cop:
        return Cop().ask("fix it").shell("pytest").say("ok")

    def test_a_malformed_line_is_skipped_and_said(self):
        self.copilot_session(self.good().text() + "{not json\n")
        code, _ = self.scan_all()
        self.assertEqual(code, 0)
        text = self.text()
        self.assertIn("| partly read |", text)
        self.assertIn("Only partly read, so its counts are too low: Session 1.", text)
        self.assertIn("Exchanges: 1.", text)

    def test_junk_is_could_not_read_and_never_clean(self):
        self.copilot_session("this is not a session\n\x00\x01 at all\n")
        code, out = self.scan_all()
        self.assertEqual(code, 0)
        text = self.text()
        self.assertIn("| could not read |", text)
        self.assertIn("Could not read, so its failures are unknown, not zero: Session 1.", text)
        self.assertIn("Nothing could be read", text)
        self.assertNotIn("No pattern fired", text)
        self.assertIn("could not read", out)

    def test_one_unreadable_session_stays_named_beside_a_clean_one(self):
        self.copilot_session(self.good(), age=10)
        self.copilot_session("garbage\n", age=20)
        self.scan_all()
        text = self.text()
        self.assertIn("Read: 1. Partly read: 0. Could not read: 1.", text)
        self.assertIn("Could not read, so its failures are unknown, not zero: Session 2.", text)
        self.assertIn("No pattern fired in what could be read.", text)

    def test_a_format_with_no_recognisable_events_is_could_not_read(self):
        self.copilot_session('{"type": "brand.new.event", "data": {}}\n')
        self.scan_all()
        self.assertIn("| could not read |", self.text())

    def test_renamed_tool_events_show_as_partly_read_not_as_talk_only(self):
        body = Cop().ask("fix it")
        body.row("tool.started_v2", {"toolName": "edit"}).say("ok")
        self.copilot_session(body)
        self.scan_all()
        self.assertIn("| partly read |", self.text())

    def test_a_session_with_no_asks_says_nothing_was_checked(self):
        self.copilot_session(Cop().row("session.start", {}))
        self.scan_all()
        self.assertIn("No exchanges found, so nothing was checked: Session 1.", self.text())
        self.assertNotIn("No pattern fired", self.text())

    def test_a_file_that_cannot_be_opened_is_could_not_read(self):
        path = self.copilot_session(self.good())
        session, _ = mod.read_session(mod.Candidate(mod.STORES[0], [path.parent / "gone.jsonl"]), 1, 600)
        self.assertEqual(session.reading, mod.READ_NONE)
        self.assertEqual(session.reason, "cannot open the file")

    def test_an_unverified_format_is_said_in_the_report(self):
        folder = self.copilot / "jb" / "s"
        folder.mkdir(parents=True)
        (folder / "partition-1.jsonl").write_text(self.good().text(), encoding="utf-8")
        self.scan_all()
        self.assertIn("Read with a format that was not checked on a real session: Session 1.", self.text())

    def test_an_error_while_parsing_never_shows_its_message(self):
        path = self.copilot_session(self.good())
        store = mod.Store("copilot-cli", True, lambda: [], lambda r: [], mock.Mock(side_effect=ValueError(MARKERS["error"])))
        session, title = mod.read_session(mod.Candidate(store, [path]), 1, 600)
        self.assertEqual(session.reading, mod.READ_NONE)
        self.assertEqual(title, "")
        self.assertIsNone(MARKER_RE.search(repr(session)))


# ------------------------------------------------------------------------------- selection

class Selection(Store):
    def setUp(self):
        super().setUp()
        self.old = self.copilot_session(Cop().ask("OLDEST SESSION TITLE"), age=300)
        self.mid = self.copilot_session(Cop().ask("MIDDLE SESSION TITLE"), age=200)
        self.new = self.copilot_session(Cop().ask("NEWEST SESSION TITLE"), age=100)

    def listing(self) -> tuple[list[str], str]:
        code, out = run(mod, "list")
        self.assertEqual(code, 0, out)
        key = re.search(r"Listing key: (\w+)", out).group(1)
        return [ln for ln in out.splitlines() if re.match(r"\s+\d+  ", ln)], key

    def handle(self, line: str) -> str:
        return re.search(r"copilot-cli\s+(\w{8})", line).group(1)

    def scanned_labels(self) -> int:
        return int(re.search(r"Sessions selected: (\d+)", self.text()).group(1))

    def test_the_list_is_newest_first_numbered_with_titles_on_screen(self):
        rows, _ = self.listing()
        self.assertEqual(len(rows), 3)
        for row, title, number in zip(rows, ("NEWEST", "MIDDLE", "OLDEST"), (1, 2, 3)):
            self.assertIn(f"{title} SESSION TITLE", row)
            self.assertTrue(row.strip().startswith(str(number)))
        self.assertRegex(rows[0], r"\d{4}-\d{2}-\d{2}  \d{2}:\d{2}  \d+m\s+1  copilot-cli")

    def test_a_title_with_terminal_escapes_is_cleaned_for_the_screen(self):
        self.copilot_session(Cop().ask("hello\x1b[31m there\x07"), age=50)
        rows, _ = self.listing()
        self.assertNotIn("\x1b", "\n".join(rows))
        self.assertNotIn("\x07", "\n".join(rows))

    def test_an_unreadable_session_is_listed_as_such(self):
        self.copilot_session("garbage\n", age=50)
        rows, _ = self.listing()
        self.assertIn("(could not read)", rows[0])

    def test_the_list_is_limited_by_a_flag_and_says_what_it_hid(self):
        code, out = run(mod, "list", "--limit", "2")
        self.assertEqual(code, 0)
        self.assertIn("1 older session(s) not shown", out)
        self.assertNotIn("OLDEST", out)

    def test_nothing_is_scanned_without_a_selection(self):
        with self.assertRaises(SystemExit):
            self.scan("--output", str(self.report))
        self.assertFalse(self.report.exists())

    def test_select_by_handle(self):
        rows, _ = self.listing()
        code, out = self.scan("--select", self.handle(rows[1]), "--output", str(self.report))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.scanned_labels(), 1)
        self.assertIn("Session 1 = #2", out)

    def test_select_by_number_and_range_with_the_listing_key(self):
        _, key = self.listing()
        code, out = self.scan("--select", "1,2-3", "--listing", key, "--output", str(self.report))
        self.assertEqual(code, 0, out)
        self.assertEqual(self.scanned_labels(), 3)

    def test_numbers_without_the_key_are_refused(self):
        code, out = self.scan("--select", "1", "--output", str(self.report))
        self.assertEqual(code, 2)
        self.assertIn("--listing", out)
        self.assertFalse(self.report.exists())

    def test_a_new_session_cant_shift_the_numbers_onto_the_wrong_one(self):
        _, key = self.listing()
        self.copilot_session(Cop().ask("BRAND NEW"), age=1)
        code, out = self.scan("--select", "1", "--listing", key, "--output", str(self.report))
        self.assertEqual(code, 1)
        self.assertIn("List them again", out)
        self.assertFalse(self.report.exists())

    def test_handles_survive_a_new_session(self):
        rows, _ = self.listing()
        self.copilot_session(Cop().ask("BRAND NEW"), age=1)
        code, _ = self.scan("--select", self.handle(rows[0]), "--output", str(self.report))
        self.assertEqual(code, 0)
        self.assertEqual(self.scanned_labels(), 1)

    def test_all_is_explicit_and_scans_them_all(self):
        code, _ = self.scan_all()
        self.assertEqual(code, 0)
        self.assertEqual(self.scanned_labels(), 3)

    def test_a_bad_token_or_number_refuses_the_whole_scan(self):
        _, key = self.listing()
        for spec in ("nonsense", "1,nonsense", "9", "0", "3-1"):
            code, _ = self.scan("--select", spec, "--listing", key, "--output", str(self.report))
            self.assertEqual(code, 2, spec)
            self.assertFalse(self.report.exists(), spec)

    def test_the_session_limit_refuses_and_can_be_raised(self):
        code, out = self.scan_all("--max-sessions", "2")
        self.assertEqual(code, 1)
        self.assertIn("--max-sessions", out)
        self.assertFalse(self.report.exists())
        self.assertEqual(self.scan_all("--max-sessions", "3")[0], 0)

    def test_limits_come_from_the_config_too(self):
        repo = Path(self._tmp.name) / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / ".copilot").mkdir()
        (repo / ".copilot" / "zethus.config.json").write_text(json.dumps({"sessionReview": {"maxSessions": 1}}), encoding="utf-8")
        cwd = os.getcwd()
        os.chdir(repo)
        self.addCleanup(os.chdir, cwd)
        self.assertEqual(self.scan_all()[0], 1)
        self.assertEqual(self.scan_all("--max-sessions", "9")[0], 0, "a flag beats the config")

    def test_a_bad_limit_is_a_usage_error(self):
        self.assertEqual(self.scan_all("--max-sessions", "0")[0], 2)

    def test_no_sessions_at_all(self):
        shutil.rmtree(self.copilot)
        code, out = run(mod, "list")
        self.assertEqual(code, 0)
        self.assertIn("No local sessions found", out)
        self.assertEqual(self.scan_all()[0], 2)


# ------------------------------------------------------------------------------- output path

class OutputPath(Store):
    def setUp(self):
        super().setUp()
        self.copilot_session(Cop().ask("fix it").say("ok"))
        self.repo = Path(self._tmp.name) / "repo"
        (self.repo / ".git").mkdir(parents=True)

    def test_refuses_a_path_inside_a_git_tree_at_any_depth(self):
        (self.repo / "docs").mkdir()
        for target in (self.repo / "r.md", self.repo / "docs" / "r.md"):
            code, out = self.scan("--select", "all", "--output", str(target))
            self.assertEqual(code, 1)
            self.assertIn("--allow-inside-git", out)
            self.assertFalse(target.exists())

    def test_a_worktree_counts_too(self):
        worktree = Path(self._tmp.name) / "wt"
        worktree.mkdir()
        (worktree / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        self.assertEqual(self.scan("--select", "all", "--output", str(worktree / "r.md"))[0], 1)

    def test_the_override_is_allowed(self):
        target = self.repo / "r.md"
        code, _ = self.scan("--select", "all", "--output", str(target), "--allow-inside-git")
        self.assertEqual(code, 0)
        self.assertTrue(target.exists())

    def test_the_default_path_is_outside_any_git_tree_and_never_overwrites(self):
        code, _ = self.scan("--select", "all")
        self.assertEqual(code, 0)
        first = self.home / "session-review-reports" / "session-review.md"
        self.assertTrue(first.exists())
        self.assertFalse(mod.inside_git_tree(first.resolve()))
        self.assertEqual(self.scan("--select", "all")[0], 0)
        self.assertTrue((self.home / "session-review-reports" / "session-review-2.md").exists())

    def test_the_default_path_is_refused_when_home_itself_is_a_git_tree(self):
        (self.home / ".git").mkdir()
        code, out = self.scan("--select", "all")
        self.assertEqual(code, 1)
        self.assertIn("--output", out)
        self.assertFalse((self.home / "session-review-reports").exists())

    def test_an_existing_file_needs_overwrite(self):
        self.report.write_text("mine", encoding="utf-8")
        code, _ = self.scan_all()
        self.assertEqual(code, 1)
        self.assertEqual(self.report.read_text(encoding="utf-8"), "mine")
        self.assertEqual(self.scan_all("--overwrite")[0], 0)
        self.assertNotEqual(self.report.read_text(encoding="utf-8"), "mine")

    def test_a_missing_folder_is_refused_rather_than_created(self):
        target = self.out / "nope" / "r.md"
        self.assertEqual(self.scan("--select", "all", "--output", str(target))[0], 1)
        self.assertFalse(target.parent.exists())


# ------------------------------------------------------------------------------- the guarantee

def canary_copilot() -> Cop:
    m = MARKERS
    cop = Cop()
    cop.row("session.start", {
        "sessionId": m["sid"], "copilotVersion": m["model"], "selectedModel": m["model"], "producer": m["user"],
        "context": {"cwd": m["path"], "gitRoot": m["path"], "repository": m["repo"], "branch": m["branch"],
                    "headCommit": m["host"], "hostname": m["host"], "user": m["user"]}})
    cop.ask(f"Why is {m['ask']} in {m['file']} at {m['url']}?").tool(m["tool"], {"query": m["ask"], "host": m["host"]},
                                                                      output=m["error"], success=False)
    cop.row("assistant.message", {"content": m["say"], "model": m["model"], "toolRequests": [
        {"name": m["tool"], "arguments": {"path": m["path"]}, "intentionSummary": m["say"]}]})
    cop.edit(f"{m['path']}/{m['file']}", m["old"], m["new"]).edit(f"{m['path']}/{m['file']}", m["new"], m["old"])
    cop.edit(f"{m['path']}/{m['file']}", m["old"], m["new"])
    cop.shell(f"{m['command']} --user {m['user']} {m['url']}", 7, f"{m['error']} at {m['path']} on {m['host']}")
    cop.shell(f"{m['command']} --user {m['user']} {m['url']}", 7, f"{m['error']} at {m['path']} on {m['host']}")
    cop.shell(f"{m['command']} (", 1, f"ParserError: {m['error']}")
    cop.tool("powershell", {"command": m["command"], "mode": "async"}, output=m["error"])
    cop.say(f"All done with {m['repo']} on {m['branch']}, see {m['url']}. {m['title']}")
    cop.ask(f"No, {m['ask']} is wrong").row("abort", {"reason": m["error"]})
    cop.row("session.shutdown", {"codeChanges": {"filesModified": [m["file"], m["path"]]}})
    return cop


def canary_rows_claude() -> list[dict]:
    m = MARKERS
    base = {"sessionId": m["sid"], "cwd": m["path"], "gitBranch": m["branch"], "version": m["model"]}
    return [
        {**base, "type": "ai-title", "aiTitle": m["title"]},
        {**base, "type": "user", "timestamp": iso(1), "message": {"content": f"Why {m['ask']} in {m['file']}?"}},
        {**base, "type": "assistant", "timestamp": iso(2), "message": {"model": m["model"], "content": [
            {"type": "text", "text": m["say"]},
            {"type": "tool_use", "id": "a", "name": m["tool"], "input": {"command": m["command"], "url": m["url"]}},
            {"type": "tool_use", "id": "b", "name": "Bash", "input": {"command": f"{m['command']} {m['user']}"}},
            {"type": "tool_use", "id": "c", "name": "Edit", "input": {"file_path": m["path"], "old_string": m["old"], "new_string": m["new"]}}]}},
        {**base, "type": "user", "timestamp": iso(3), "message": {"content": [
            {"type": "tool_result", "tool_use_id": "b", "is_error": True, "content": f"Exit code 3\n{m['error']} {m['host']}"}]}},
        {**base, "type": "assistant", "timestamp": iso(4), "message": {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": f"Done with {m['repo']}"}]}},
    ]


def canary_rows_codex() -> list[dict]:
    m = MARKERS
    def ev(t, **payload):
        return {"timestamp": iso(t), "type": "event_msg", "payload": payload}
    return [
        {"timestamp": iso(0), "type": "session_meta", "payload": {"id": m["sid"], "cwd": m["path"], "cli_version": m["model"],
                                                                  "git": {"branch": m["branch"], "repository_url": m["url"]},
                                                                  "creator_user_id": m["user"], "base_instructions": m["repo"]}},
        ev(1, type="item_completed", item={"type": "UserMessage", "content": [{"type": "text", "text": f"Why {m['ask']}?"}]}),
        {"timestamp": iso(2), "type": "response_item", "payload": {"type": "function_call", "name": m["tool"], "call_id": "c",
                                                                   "arguments": json.dumps({"q": m["ask"]})}},
        {"timestamp": iso(3), "type": "response_item", "payload": {"type": "function_call_output", "call_id": "c", "output": m["error"]}},
        ev(4, type="item_completed", item={"type": "CommandExecution", "parsed_cmd": [{"cmd": m["command"]}], "cwd": m["path"],
                                           "status": "failed", "exit_code": 1, "aggregated_output": f"{m['error']} {m['host']}",
                                           "process_id": m["sid"]}),
        ev(5, type="item_completed", item={"type": "AgentMessage", "content": [{"type": "Text", "text": f"Done {m['say']}"}]}),
        ev(6, type="task_complete", last_agent_message=m["say"]),
    ]


def canary_vscode() -> dict:
    m = MARKERS
    return {"version": 3, "sessionId": m["sid"], "creationDate": START * 1000, "customTitle": m["title"],
            "requesterUsername": m["user"], "responderUsername": m["host"], "workingDirectory": m["path"], "requests": [{
                "requestId": m["sid"], "timestamp": START * 1000, "modelId": m["model"], "agent": {"id": m["tool"]},
                "message": {"text": f"Fix {m['ask']} in {m['file']}"},
                "variableData": {"variables": [{"value": m["url"]}]},
                "response": [
                    {"value": m["say"]},
                    {"kind": "toolInvocationSerialized", "toolId": m["tool"], "invocationMessage": m["command"],
                     "pastTenseMessage": m["error"], "resultError": m["error"],
                     "toolSpecificData": {"kind": "terminal", "commandLine": {"original": m["command"]},
                                          "terminalCommandState": {"exitCode": 1}}},
                    {"kind": "textEditGroup", "uri": {"path": m["path"]}, "edits": [[{"text": m["new"]}]]}]}]}


class Canary(Store):
    """Marker strings in every field an adapter touches. None may come out."""

    def setUp(self):
        super().setUp()
        self.copilot_session(canary_copilot(), sid=MARKERS["sid"] + "-copilot", age=1)
        jb = self.copilot / "jb" / (MARKERS["sid"] + "-jb")
        jb.mkdir(parents=True)
        (jb / "partition-1.jsonl").write_text(canary_copilot().text(), encoding="utf-8")
        claude = self.home / ".claude" / "projects" / ("-srv-" + MARKERS["repo"])
        claude.mkdir(parents=True)
        (claude / (MARKERS["sid"] + ".jsonl")).write_text("\n".join(map(json.dumps, canary_rows_claude())), encoding="utf-8")
        codex = self.home / ".codex" / "sessions" / "2026" / "11" / "06"
        codex.mkdir(parents=True)
        (codex / f"rollout-x-{MARKERS['sid']}.jsonl").write_text("\n".join(map(json.dumps, canary_rows_codex())), encoding="utf-8")
        vscode = self.home / ".config" / "Code" / "User" / "workspaceStorage" / MARKERS["repo"] / "chatSessions"
        vscode.mkdir(parents=True)
        (vscode / (MARKERS["sid"] + ".json")).write_text(json.dumps(canary_vscode()), encoding="utf-8")
        (self.copilot / "session-state" / (MARKERS["sid"] + "-copilot") / "workspace.yaml").write_text(
            f"cwd: {MARKERS['path']}\nbranch: {MARKERS['branch']}\nname: {MARKERS['title']}\n", encoding="utf-8")

    def tree(self) -> dict[str, tuple[bytes, int]]:
        root = Path(self._tmp.name)
        return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in root.rglob("*") if p.is_file()}

    def test_the_fixtures_really_are_full_of_markers(self):
        """Guards the test itself: a marker no fixture holds would pass for the wrong reason."""
        everything = "\n".join(b.decode("utf-8", "replace") + " " + name for name, (b, _) in self.tree().items())
        for key, value in MARKERS.items():
            self.assertIn(value, everything, key)
        self.assertEqual(len(mod.discover(None, {})), 5)

    def test_no_marker_reaches_the_report_or_the_scan_output(self):
        code, out = self.scan_all()
        self.assertEqual(code, 0, out)
        text = self.text()
        self.assertEqual(MARKER_RE.findall(text), [])
        self.assertEqual(MARKER_RE.findall(out), [])
        self.assertIn("Sessions selected: 5.", text, "every adapter fed this report")
        self.assertIn("Read: 5. Partly read: 0. Could not read: 0.", text)
        self.assertIn("Read with a format that was not checked on a real session: Session", text)
        self.assertRegex(text, r"Actions: shell [1-9]")
        self.assertRegex(text, r"other [1-9]\d*\.", "the tool is reported, only as a category")

    def test_the_patterns_really_fired_on_the_canary_text(self):
        """Without this, an adapter that dropped everything would pass the canary."""
        self.scan_all()
        text = self.text()
        for name in ("Command failed at the parser", "Retried straight after its own error",
                     "Turn ended with a background command running", "Flip-flopped between two edits",
                     "User corrected or interrupted the agent", "Same failure in more than one session"):
            self.assertTrue(f"### {name}" in text or f"{name}: count" in text, name)

    def test_the_analysis_holds_no_marker_either(self):
        for candidate in mod.discover(None, {}):
            session, title = mod.read_session(candidate, 1, 600)
            self.assertEqual(MARKER_RE.findall(repr(session)), [], candidate.store.name)

    def test_it_writes_one_file_and_changes_nothing_else(self):
        before = self.tree()
        code, _ = self.scan_all()
        self.assertEqual(code, 0)
        after = self.tree()
        self.assertEqual(set(after) - set(before), {str(self.report.relative_to(Path(self._tmp.name)))})
        for name, value in before.items():
            self.assertEqual(after[name], value, "a session file changed")

    def test_only_the_report_file_holds_report_text_and_no_marker_in_any_new_file(self):
        before = set(self.tree())
        self.scan("--select", "all")
        new = set(self.tree()) - before
        self.assertEqual(len(new), 1)
        for name in new:
            body = (Path(self._tmp.name) / name).read_text(encoding="ascii")
            self.assertEqual(MARKER_RE.findall(body), [])

    def test_the_list_may_show_a_title_and_it_stays_on_screen(self):
        before = self.tree()
        code, out = run(mod, "list")
        self.assertEqual(code, 0)
        self.assertIn(MARKERS["title"], out, "the list is where a title belongs")
        self.assertEqual(self.tree(), before, "listing writes nothing")

    def test_no_date_leaves_no_date(self):
        code, _ = self.scan_all("--no-date")
        self.assertEqual(code, 0)
        text = self.text()
        self.assertIsNone(re.search(r"\d{4}-\d{2}-\d{2}", text))
        self.assertIn("Dates left out on request.", text)
        self.assertEqual(MARKER_RE.findall(text), [])

    def test_a_date_is_there_otherwise_and_nothing_finer(self):
        self.scan_all()
        text = self.text()
        self.assertRegex(text, r"\| Session 1 \| \d{4}-\d{2}-\d{2} \|")
        self.assertIsNone(re.search(r"\d{1,2}:\d{2}", text), "no time of day")

    def test_no_network_and_nothing_spawned(self):
        boom = AssertionError("must not be called")
        with mock.patch("socket.socket", side_effect=boom), mock.patch("subprocess.Popen", side_effect=boom), \
                mock.patch("os.system", side_effect=boom):
            code, out = self.scan_all()
            self.assertEqual(code, 0, out)
            self.assertEqual(run(mod, "list")[0], 0)


class FailClosed(Store):
    def setUp(self):
        super().setUp()
        self.copilot_session(Cop().ask("fix it").say("ok"))

    def good_report(self) -> str:
        sessions = [mod.read_session(mod.discover(None, {})[0], 1, 600)[0]]
        return mod.render(sessions, 10, True, 90, 12)

    def test_a_real_report_passes(self):
        mod.check_report(self.good_report(), True)

    def test_every_kind_of_stray_text_is_refused(self):
        good = self.good_report()
        strays = (
            "A line nobody wrote into the vocabulary.",
            MARKERS["command"],
            "C:\\Users\\alice\\project\\app.py",
            "https://example.com/internal",
            "powershell",                                       # a real tool name, not a category
            "| Session 1 | 2026-11-06 | 1m | 3 | read | extra |",
            "Count: 3. Sessions: Session 1, zzrepomarker.",
            "Actions: shell 1, file read 2, file edit 3, search 4, web 5, zzmcp 6.",
            "Session 1 fixed the thing.",
            "Dates: 2026-11-06 to feature/branch.",
            "| zzhost | 1 | 0 | 0 | 0 | 0 | 0 |",
            "### Long stall (feature/thing)",
            "How to read it: heuristic. Usually a quoting problem in zzrepomarker.",
            "Read: caf\u00e9",
        )
        for stray in strays:
            for text in (good + stray + "\n", stray + "\n" + good):
                with self.assertRaises(mod.GuaranteeError, msg=stray):
                    mod.check_report(text, True)

    def test_a_marker_appended_to_an_allowed_line_is_refused(self):
        lines = self.good_report().splitlines()
        for i, line in enumerate(lines):
            if line:
                broken = lines[:i] + [line + " " + MARKERS["repo"]] + lines[i + 1:]
                with self.assertRaises(mod.GuaranteeError, msg=line):
                    mod.check_report("\n".join(broken) + "\n", True)

    def test_a_date_is_refused_when_dates_were_asked_off(self):
        with self.assertRaises(mod.GuaranteeError):
            mod.check_report(self.good_report(), False)

    def test_the_script_refuses_writes_nothing_and_names_no_text(self):
        real = mod.render
        def leaky(*args, **kwargs):
            return real(*args, **kwargs) + MARKERS["ask"] + "\n"
        with mock.patch.object(mod, "render", leaky):
            code, out = self.scan_all()
        self.assertEqual(code, 1)
        self.assertFalse(self.report.exists())
        self.assertIn("refused", out)
        self.assertEqual(MARKER_RE.findall(out), [])

    def test_the_default_folder_isnt_even_made_when_it_refuses(self):
        real = mod.render
        with mock.patch.object(mod, "render", lambda *a, **k: real(*a, **k) + MARKERS["ask"] + "\n"):
            self.assertEqual(self.scan("--select", "all")[0], 1)
        self.assertFalse((self.home / "session-review-reports").exists())

    def test_an_internal_error_prints_no_message_and_no_traceback(self):
        with mock.patch.object(mod, "render", side_effect=ValueError(MARKERS["error"])):
            code, out = self.scan_all()
        self.assertEqual(code, 1)
        self.assertFalse(self.report.exists())
        self.assertEqual(MARKER_RE.findall(out), [])
        self.assertNotIn("Traceback", out)

    def test_the_vocabulary_has_no_room_for_free_text(self):
        """No hole in a template may accept letters beyond the fixed names."""
        for hole, pattern in mod._PH.items():
            self.assertNotRegex(pattern, r"\\w|\\S|\.\*|\.\+|\[\^", hole)


class Shape(Store):
    def fire_everything(self) -> Cop:
        return (Cop().ask("fix it").shell("x", 1, "ParserError: y").shell("npm test", 1, "e").shell("npm test", 1, "e")
                .edit(old="A", new="B").edit(old="B", new="A").edit(old="A", new="B")
                .tool("powershell", {"command": "z", "mode": "async"}).shell("npm test", 1, "e").say("All done!", gap=900)
                .ask("why is it slow?").edit().say("there").ask("add a retry").say("It goes in the client.")
                .ask("run the tests").say("They should pass.").ask("stop").edit().say("ok").ask("no, that's wrong")
                .say("sorry").ask("fix").shell("y").ask("again").shell("y").row("abort", {}).ask("x").say("ok"))

    def test_every_pattern_has_definition_reading_and_says_heuristic(self):
        self.assertEqual(len({p.key for p in mod.PATTERNS}), len(mod.PATTERNS))
        for p in mod.PATTERNS:
            self.assertTrue(p.what[0].startswith("What it is: "), p.key)
            self.assertTrue(p.read[0].startswith("How to read it: heuristic"), p.key)
            self.assertIn(p.kind, ("mistake", "process"), "Mnemosyne's categories")
            for line in (*p.what, *p.read):
                self.assertLessEqual(len(line), mod.WIDTH, line)
                self.assertTrue(line.isascii(), line)

    def test_the_brief_list_is_covered(self):
        keys = {p.key for p in mod.PATTERNS}
        self.assertLessEqual({"parser", "retry", "unverified", "background", "silent", "stall", "false_done",
                              "question_edit", "change_talk", "correction", "flip", "recurring"}, keys)

    def test_a_report_with_everything_fired_fits_two_screens_and_passes(self):
        self.copilot_session(self.fire_everything(), age=1)
        self.copilot_session(self.fire_everything(), age=2)
        code, out = self.scan_all()
        self.assertEqual(code, 0, out)
        text = self.text()
        self.assertLessEqual(text.count("\n"), mod.DEFAULTS["maxReportLines"])
        self.assertLessEqual(max(len(ln) for ln in text.splitlines()), mod.WIDTH)
        fired = sum(f"### {p.name}" in text or f"{p.name}: count" in text for p in mod.PATTERNS)
        self.assertEqual(fired, len(mod.PATTERNS), "every pattern fired on this fixture")

    def test_a_tight_line_limit_shortens_lowest_counts_first_and_says_so(self):
        self.copilot_session(self.fire_everything(), age=1)
        self.copilot_session(self.fire_everything(), age=2)
        code, out = self.scan_all("--max-lines", "50")
        self.assertEqual(code, 0, out)
        text = self.text()
        self.assertLessEqual(text.count("\n"), 50)
        self.assertRegex(text, r"Shortened to fit: \d+ patterns")
        self.assertRegex(text, r"[A-Z][\w ,-]+: count \d+\. Sessions: Session 1")

    def test_a_limit_too_small_refuses_rather_than_cutting(self):
        self.copilot_session(self.fire_everything())
        code, out = self.scan_all("--max-lines", "5")
        self.assertEqual(code, 1)
        self.assertIn("--max-lines", out)
        self.assertFalse(self.report.exists())

    def test_many_sessions_collapse_the_table_and_keep_the_unreadable_ones_named(self):
        for i in range(14):
            self.copilot_session(Cop().ask("fix it").say("ok"), age=i + 1)
        self.copilot_session("garbage\n", age=100)
        code, _ = self.scan_all()
        self.assertEqual(code, 0)
        text = self.text()
        self.assertNotIn("| Session 2 |", text)
        self.assertRegex(text, r"Dates: \d{4}-\d{2}-\d{2} to \d{4}-\d{2}-\d{2}\.")
        self.assertIn("Could not read, so its failures are unknown, not zero: Session 15.", text)
        self.assertEqual(self.scan("--select", "all", "--output", str(self.out / "b.md"), "--max-table-rows", "20")[0], 0)
        self.assertIn("| Session 2 |", (self.out / "b.md").read_text(encoding="ascii"))

    def test_session_lists_wrap_and_still_pass(self):
        for i in range(30):
            self.copilot_session("garbage\n", age=i + 1)
        code, out = self.scan_all()
        self.assertEqual(code, 0, out)
        self.assertLessEqual(max(len(ln) for ln in self.text().splitlines()), mod.WIDTH)

    def test_a_zero_finding_report_doesnt_claim_health(self):
        self.copilot_session(Cop().ask("what is this?").say("a thing"))
        self.scan_all()
        text = self.text()
        self.assertIn("No pattern fired in what could be read. These detectors undercount, so that isn't health.", text)
        self.assertNotIn("Not seen:", text)

    def test_the_durations_are_whole_minutes(self):
        self.assertEqual(mod._duration(59), "0m")
        self.assertEqual(mod._duration(3660), "1h 1m")
        self.assertEqual(mod._duration(90000), "1d 1h 0m")


# ------------------------------------------------------------------------------- the kit

class Script(unittest.TestCase):
    def test_it_imports_only_what_it_needs_and_nothing_that_reaches_out(self):
        tree = ast.parse((SCRIPTS / "session-review.py").read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names.add((node.module or "").split(".")[0])
        allowed = {"__future__", "argparse", "collections", "dataclasses", "datetime", "hashlib", "json", "os", "pathlib",
                   "re", "sys", "_common"}
        self.assertEqual(names - allowed, set())

    def test_the_only_write_mode_open_is_the_report(self):
        text = (SCRIPTS / "session-review.py").read_text(encoding="utf-8")
        tree = ast.parse(text)
        writes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "open" and len(node.args) > 1:
                writes.append(ast.get_source_segment(text, node.args[1]))
        self.assertEqual(writes, ['"w" if overwrite else "x"'])

    def test_it_leaves_no_bytecode_beside_the_kit(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = Path(tmp) / "scripts"
            kit.mkdir()
            for name in ("session-review.py", "_common.py"):
                shutil.copyfile(SCRIPTS / name, kit / name)
            home = Path(tmp) / "home"
            home.mkdir()
            env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
            env.pop("PYTHONDONTWRITEBYTECODE", None)
            done = subprocess.run([sys.executable, str(kit / "session-review.py"), "list"], cwd=tmp, env=env,
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertFalse((kit / "__pycache__").exists())


class Skill(unittest.TestCase):
    def setUp(self):
        self.text = " ".join(SKILL.read_text(encoding="utf-8").split())

    def test_frontmatter(self):
        fm = frontmatter(SKILL)
        self.assertEqual(fm["name"], "session-review")
        self.assertLessEqual(len(fm["description"]), 1024)

    def test_it_says_how_to_handle_the_report(self):
        for rule in ("exactly as written", "Don't summarise", "one or two screens", "photographed",
                     "--no-date", "never reaches the report"):
            self.assertIn(rule, self.text, rule)

    def test_selection_uses_the_question_tool_and_defaults_to_nothing(self):
        for rule in ("question tool", "No option is preselected", "scans nothing", "Don't assume all"):
            self.assertIn(rule, self.text, rule)
        self.assertIn("ask-with-the-question-tool.md", self.text)

    def test_it_forbids_reading_the_sessions_directly(self):
        self.assertIn("Don't open a session file yourself", self.text)

    def test_it_states_what_was_and_wasnt_verified(self):
        for store in ("Copilot CLI", "JetBrains", "VS Code", "Claude Code", "Codex", "cloud agent"):
            self.assertIn(store, self.text, store)
        self.assertIn("Not verified", self.text)
        self.assertIn("could not read", self.text)

    def test_docs_point_at_it(self):
        readme = (KIT / "README.md").read_text(encoding="utf-8")
        self.assertIn("skills/session-review/SKILL.md", readme)
        self.assertIn("scripts/session-review.py", readme)
        self.assertIn("docs/session-review-guarantee.md", readme)
        self.assertIn("sessionReview", readme)
        guarantee = " ".join(DOC.read_text(encoding="utf-8").split())
        self.assertIn("What it can't catch", guarantee)
        self.assertIn("Not verified", guarantee)
        config = json.loads((KIT / "zethus.config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(config["sessionReview"], mod.DEFAULTS)


class Routes(FakeHome):
    """It installs and runs through every route the kit supports."""

    def run_installed(self, script: Path) -> str:
        env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home)}
        for var in ("COPILOT_HOME", "ZETHUS_CONFIG"):
            env.pop(var, None)
        done = subprocess.run([sys.executable, str(script), "list"], cwd=self.home, env=env,
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def seed_session(self) -> None:
        folder = self.copilot / "session-state" / "s1"
        folder.mkdir(parents=True)
        (folder / "events.jsonl").write_text(Cop().ask("INSTALLED ROUTE").say("ok").text(), encoding="utf-8")

    def test_plugin_layout(self):
        """The plugin root is the kit folder, so the skill's two-folders-up note reaches the script."""
        self.assertTrue(SKILL.is_file())
        self.assertTrue((SKILL.parent.parent.parent / "scripts" / "session-review.py").is_file())
        self.assertIn("<kit root>/scripts/session-review.py", SKILL.read_text(encoding="utf-8"))
        self.seed_session()
        self.assertIn("INSTALLED ROUTE", self.run_installed(SCRIPTS / "session-review.py"))

    def test_repo_mode(self):
        target = self.home / "repo"
        target.mkdir()
        code, out = run(install_mod, "--target", str(target))
        self.assertEqual(code, 0, out)
        skill = (target / ".github/skills/session-review/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("python .github/zethus/scripts/session-review.py", skill)
        self.assertNotIn("<kit root>", skill)
        self.seed_session()
        self.assertIn("INSTALLED ROUTE", self.run_installed(target / ".github/zethus/scripts/session-review.py"))

    def test_user_mode_and_its_uninstall(self):
        with mock.patch.object(install_mod, "PLATFORM", "linux"):
            code, out = run(install_mod, "--user")
            self.assertEqual(code, 0, out)
            installed = self.copilot / "zethus/scripts/session-review.py"
            skill = (self.copilot / "skills/session-review/SKILL.md").read_text(encoding="utf-8")
            self.assertIn(f"python {installed.as_posix()}", skill)
            self.seed_session()
            self.assertIn("INSTALLED ROUTE", self.run_installed(installed))
            code, _ = run(install_mod, "--user", "--uninstall")
            self.assertEqual(code, 0)
            self.assertFalse(installed.exists())
            self.assertFalse((self.copilot / "skills/session-review").exists())


if __name__ == "__main__":
    unittest.main()
