"""CI coverage for lessons capture in shadow mode (docs/lessons-capture-spec.md, Phase 0).

The capture hooks detect signals and append candidates to memory/.capture/, log one decision per
invocation, and do nothing else: no lesson is stored, nothing is asked, no capture mode prints.
Event payloads below use the field names observed on real Claude Code, Copilot CLI and Codex
installs (spec §4.7.1), and every guard is driven with its variable set the way the host sets it.
Offline: the only subprocesses are the hook bridge, local git commands and the spool race's writers.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
MNEMOSYNE_SRC = REPO / "mnemosyne" / "src"
HOOK = REPO / "mnemosyne" / "plugin" / "hooks" / "mnemosyne_hook.py"

if str(MNEMOSYNE_SRC) not in sys.path:
    sys.path.insert(0, str(MNEMOSYNE_SRC))

from mnemosyne import candidates as cd  # noqa: E402
from mnemosyne import cli, core  # noqa: E402

# Built at run time so no credential-shaped literal sits in a tracked file.
FAKE_GITHUB_TOKEN = "gh" + "p_" + "A1b2C3d4" * 5
FAKE_CLOUD_KEY = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
HOST_ENV = ("MNEMOSYNE_CAPTURE", "MNEMOSYNE_REPO", "MNEMOSYNE_CONFIG", "COPILOT_CLI", "CLAUDECODE",
            "CLAUDE_CODE_ENTRYPOINT", "ZETHUS_CONFIG")


class SecretShapes(unittest.TestCase):
    def test_each_shape_is_found(self):
        samples = {
            "cloud-access-key": f"key {FAKE_CLOUD_KEY} here",
            "github-token": f"use {FAKE_GITHUB_TOKEN}",
            "github-pat": "github" + "_pat_" + "x" * 30,
            "sk-key": "s" + "k-" + "a" * 24,
            "slack-token": "xo" + "xb-" + "1234567890-abc",
            "private-key": "-----BEGIN RSA " + "PRIVATE KEY-----",
            "jwt": "ey" + "J" + "a" * 10 + ".ey" + "J" + "b" * 10 + "." + "c" * 10,
            "credential-assignment": "pass" + "word=hunter2hunter2",
        }
        for name, text in samples.items():
            self.assertEqual(core.find_secret(text), name, text)

    def test_ordinary_text_is_clean(self):
        for text in ("from now on always page at 50", "set max_token=1000 in the config",
                     "the token is rotated nightly", "", None):
            self.assertIsNone(core.find_secret(text))


class Detection(unittest.TestCase):
    def test_prompt_signals(self):
        sigs = {s: phrase for s, phrase, _ in cd.prompt_signals("No, from now on use tabs instead")}
        self.assertEqual(sigs, {"S4": "from now on", "S5": "No,"})
        self.assertEqual([s for s, _, _ in cd.prompt_signals("Don\u2019t squash that PR")], ["S5"])
        self.assertEqual(cd.prompt_signals("please add a test for the parser"), [])

    def test_excerpt_is_bounded_and_scrubbed(self):
        prompt = "x" * 500 + r" remember C:\Users\alice\secret-project\notes.md " + "y" * 500
        (_, _, snip), = cd.prompt_signals(prompt)
        self.assertLess(len(snip), 200)
        self.assertIn("<path>", snip)
        self.assertNotIn("alice", snip)

    def test_command_head(self):
        self.assertEqual(cd.command_head("npm test -- --watch"), "npm test")
        self.assertEqual(cd.command_head("python -m unittest discover -s tests"), "python unittest")
        self.assertEqual(cd.command_head("FOO=1 pytest --lf && echo done"), "pytest")
        self.assertEqual(cd.command_head(r"C:\Users\alice\py\python.exe --version"), "python.exe")  # no machine path

    def test_tool_outcome_per_host(self):
        claude_fail = {"hook_event_name": "PostToolUseFailure", "error": "Exit code 3\nfailing"}
        claude_ok = {"hook_event_name": "PostToolUse", "tool_response": {"stdout": "", "stderr": ""}}
        copilot_fail = {"toolName": "powershell", "toolResult": {
            "resultType": "success", "textResultForLlm": "fatal\n<shellId: 1 completed with exit code 128>"}}
        copilot_ok = {"toolName": "powershell", "toolResult": {
            "resultType": "success", "textResultForLlm": "ok\n<shellId: 2 completed with exit code 0>"}}
        copilot_denied = {"toolName": "powershell", "toolResult": {"resultType": "denied"}}
        copilot_claude_fmt = {"hook_event_name": "PostToolUse", "tool_result": json.dumps(
            {"text_result_for_llm": "x\n<shellId: 1 completed with exit code 2>"})}
        codex = {"hook_event_name": "PostToolUse", "turn_id": "t", "tool_response": "fatal: nope\n"}
        self.assertEqual(cd.tool_outcome(claude_fail), ("failure", 3))
        self.assertEqual(cd.tool_outcome(claude_ok), ("success", None))
        self.assertEqual(cd.tool_outcome(copilot_fail), ("failure", 128))
        self.assertEqual(cd.tool_outcome(copilot_ok), ("success", 0))
        self.assertEqual(cd.tool_outcome(copilot_denied), ("failure", None))
        self.assertEqual(cd.tool_outcome(copilot_claude_fmt), ("failure", 2))
        self.assertEqual(cd.tool_outcome(codex), (None, None))

    def test_written_paths_per_host(self):
        self.assertEqual(cd.written_paths({"tool_name": "Write", "tool_input": {"file_path": "a/b.md"}}),
                         ["a/b.md"])
        self.assertEqual(cd.written_paths({"tool_name": "Read", "tool_input": {"file_path": "a/b.md"}}), [])
        self.assertEqual(cd.written_paths({"toolName": "create", "toolArgs": {"path": "c.md"}}), ["c.md"])
        self.assertEqual(cd.written_paths({"toolName": "edit", "toolArgs": json.dumps({"path": "d.md"})}),
                         ["d.md"])
        patch = "*** Begin Patch\n*** Update File: docs/specs/x.md\n@@\n-a\n+b\n*** Add File: e.md\n*** End Patch"
        self.assertEqual(cd.written_paths({"tool_name": "apply_patch", "tool_input": {"command": patch}}),
                         ["docs/specs/x.md", "e.md"])
        self.assertEqual(cd.written_paths({"hook_event_name": "afterFileEdit", "file_path": "f.md"}), ["f.md"])

    def test_relative_and_watch(self):
        self.assertEqual(cd.relative_to(r"C:\Users\alice\proj\docs\specs\a.md", r"C:\Users\alice\proj"), "docs/specs/a.md")
        self.assertIsNone(cd.relative_to(r"C:\Users\bob\other\a.md", r"C:\Users\alice\proj"))
        self.assertIsNone(cd.relative_to("../a.md", "/w/proj"))
        self.assertEqual(cd.watch_match("docs/adr/0001-x.md", cd.DEFAULT_WATCH), "docs/adr/")
        self.assertEqual(cd.watch_match("docs/friction-log.md", cd.DEFAULT_WATCH), "docs/friction-log.md")
        self.assertIsNone(cd.watch_match("src/app.py", cd.DEFAULT_WATCH))

    def test_detect_host(self):
        self.assertEqual(cd.detect_host({"session_id": "s", "prompt_id": "p"}, {"CLAUDECODE": "1"}), "claude-code")
        self.assertEqual(cd.detect_host({"sessionId": "s", "toolName": "x"}, {}), "copilot-cli")
        # Copilot sets CLAUDE_PROJECT_DIR too, and its .github PascalCase hooks get snake_case stdin.
        self.assertEqual(cd.detect_host({"session_id": "s"}, {"COPILOT_CLI": "1", "CLAUDE_PROJECT_DIR": "x"}),
                         "copilot-cli")
        # Codex passes its parent's environment through, so its event shape must win.
        self.assertEqual(cd.detect_host({"session_id": "s", "turn_id": "t"}, {"CLAUDECODE": "1"}), "codex")
        self.assertEqual(cd.detect_host({"conversation_id": "c"}, {"CLAUDECODE": "1"}), "cursor")
        self.assertEqual(cd.detect_host({}, {}), "unknown")


class _Project(unittest.TestCase):
    """A temp project that is also its own memory repo, with a branch in .git/HEAD."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "memory").mkdir()
        (self.root / ".git").mkdir()
        (self.root / ".git" / "HEAD").write_text("ref: refs/heads/feat/demo\n", encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if k not in HOST_ENV}
        # CLAUDECODE is what Claude Code sets for its hooks (spec §4.7.1).
        self.env.update(PYTHONPATH=str(MNEMOSYNE_SRC), MNEMOSYNE_REPO=str(self.root), CLAUDECODE="1")

    def tearDown(self):
        self._td.cleanup()

    def ev(self, **kw):
        return dict({"session_id": "s1", "cwd": str(self.root)}, **kw)

    def hook(self, mode, event, *extra, env=None):
        proc = subprocess.run([sys.executable, str(HOOK), mode, *extra], input=json.dumps(event),
                              capture_output=True, text=True, env=env or self.env, cwd=str(self.root))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def capture(self, mode, event, **kw):
        return cd.capture_event(mode, event, env=self.env, **kw)

    def signals(self):
        return [c["signal"] for c in cd.candidates(self.root)]

    def lesson_files(self):
        return {p.name: p.read_bytes() for p in (core.local_path(self.root), core.shared_path(self.root))
                if p.exists()}


class HookBridgeShadowMode(_Project):
    def test_prompt_records_candidates_and_prints_nothing(self):
        out = self.hook("prompt", self.ev(hook_event_name="UserPromptSubmit",
                                          prompt="No, from now on always page at 50 instead."))
        self.assertEqual(out, "")  # no lessons to recall, and capture never prints
        cands = cd.candidates(self.root)
        self.assertEqual(sorted(c["signal"] for c in cands), ["S4", "S5"])
        c = cands[0]
        self.assertEqual((c["mode"], c["host"], c["session"]), ("shadow", "claude-code", "s1"))
        self.assertEqual(c["context"], {"repo": self.root.name, "branch": "feat/demo"})
        (log,) = cd.decisions(self.root)
        self.assertEqual((log["mode"], log["decision"]), ("prompt", "candidate"))
        self.assertEqual(self.lesson_files(), {})  # nothing stored as a lesson

    def test_host_flag_names_the_host(self):
        self.hook("prompt", self.ev(prompt="remember this"), "--host", "copilot-cli")
        self.assertEqual(cd.candidates(self.root)[0]["host"], "copilot-cli")

    def test_a_prompt_with_a_credential_is_dropped_whole(self):
        self.hook("prompt", self.ev(prompt=f"always use token {FAKE_GITHUB_TOKEN} for the API"))
        self.assertEqual(cd.candidates(self.root), [])
        (log,) = cd.decisions(self.root)
        self.assertEqual(log["decision"], "dropped")
        self.assertIn("github-token", log["detail"])
        spool = "".join(p.read_text(encoding="utf-8") for p in cd.capture_dir(self.root).glob("*.jsonl"))
        self.assertNotIn(FAKE_GITHUB_TOKEN, spool)

    def test_capture_off_writes_nothing(self):
        env = dict(self.env, MNEMOSYNE_CAPTURE="off")
        self.hook("prompt", self.ev(prompt="from now on always rebase"), env=env)
        self.hook("stop", self.ev(hook_event_name="Stop"), env=env)
        self.assertFalse(cd.capture_dir(self.root).exists())

    def test_project_config_can_disable_capture(self):
        (self.root / ".github").mkdir()
        (self.root / ".github" / "zethus.config.json").write_text(
            json.dumps({"memory": {"enabled": False}}), encoding="utf-8")
        self.hook("prompt", self.ev(prompt="from now on always rebase"))
        self.assertFalse(cd.capture_dir(self.root).exists())

    def test_no_memory_repo_is_silent(self):
        with tempfile.TemporaryDirectory() as bare:
            env = {k: v for k, v in self.env.items() if k != "MNEMOSYNE_REPO"}
            for mode in cd.MODES:
                proc = subprocess.run([sys.executable, str(HOOK), mode],
                                      input=json.dumps({"cwd": bare, "prompt": "always x"}),
                                      capture_output=True, text=True, env=env, cwd=bare)
                self.assertEqual((proc.returncode, proc.stdout), (0, ""))
            self.assertEqual(list(Path(bare).iterdir()), [])

    def test_garbage_stdin_is_silent(self):
        for payload in ("not json", "[1, 2]", ""):
            proc = subprocess.run([sys.executable, str(HOOK), "post-tool"], input=payload,
                                  capture_output=True, text=True, env=self.env, cwd=str(self.root))
            self.assertEqual((proc.returncode, proc.stdout), (0, ""))

    def test_stop_never_blocks(self):
        self.hook("prompt", self.ev(prompt="remember: we page at 50"))
        for active in (False, True):  # the guard, set both ways Claude Code sets it
            out = self.hook("stop", self.ev(hook_event_name="Stop", stop_hook_active=active))
            self.assertEqual(out, "")
        stops = [r for r in cd.decisions(self.root) if r["mode"] == "stop"]
        self.assertEqual([r["decision"] for r in stops], ["would-block", "would-block"])
        self.assertEqual([r["stop_hook_active"] for r in stops], [False, True])
        self.assertEqual(stops[0]["pending_session"], 1)

    def test_stop_with_nothing_pending(self):
        out = self.hook("stop", self.ev(hook_event_name="Stop", stop_hook_active=False))
        self.assertEqual(out, "")
        self.assertEqual(cd.decisions(self.root)[-1]["decision"], "nothing-pending")

    def test_pre_compact_and_session_start_print_nothing(self):
        self.assertEqual(self.hook("pre-compact", self.ev(hook_event_name="PreCompact", trigger="manual")), "")
        self.assertEqual(self.hook("session-start", self.ev(hook_event_name="SessionStart", source="startup")), "")
        self.assertEqual([r["decision"] for r in cd.decisions(self.root)], ["flushed", "session-start"])
        self.assertNotIn("local.jsonl", self.lesson_files())

    def test_spool_is_ignored_by_git(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            subprocess.run(["git", "init", "-q", str(root)], check=True, stdin=subprocess.DEVNULL)
            (root / "memory").mkdir()
            (root / "memory" / "lessons.jsonl").write_text("", encoding="utf-8")
            env = dict(self.env, MNEMOSYNE_REPO=str(root))
            subprocess.run([sys.executable, str(HOOK), "prompt"], env=env, cwd=str(root), text=True,
                           input=json.dumps({"session_id": "s", "cwd": str(root), "prompt": "always x"}),
                           capture_output=True, check=True)
            self.assertTrue((cd.capture_dir(root) / "candidates.jsonl").exists())
            status = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
                                    capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout
            self.assertNotIn(".capture", status)
            self.assertIn("memory/lessons.jsonl", status)


class PostToolSignals(_Project):
    def test_s6_from_claude_code_events(self):
        self.capture("post-tool", self.ev(hook_event_name="PostToolUseFailure", tool_name="Bash",
                                          tool_input={"command": "npm test -- --watch"},
                                          error="Exit code 1\nboom", is_interrupt=False))
        self.assertEqual(cd.decisions(self.root)[-1]["decision"], "noted-failure")
        self.capture("post-tool", self.ev(hook_event_name="PostToolUse", tool_name="Bash",
                                          tool_input={"command": "npm test"},
                                          tool_response={"stdout": "ok", "stderr": "", "interrupted": False}))
        (c,) = cd.candidates(self.root)
        self.assertEqual((c["signal"], c["evidence"]["head"], c["evidence"]["failed_exit"]), ("S6", "npm test", 1))
        self.assertNotIn("boom", json.dumps(c))  # pointers only, never tool output

    def test_s6_needs_the_same_session_and_command(self):
        self.capture("post-tool", self.ev(hook_event_name="PostToolUseFailure", tool_name="Bash",
                                          tool_input={"command": "npm test"}, error="Exit code 1"))
        self.capture("post-tool", self.ev(hook_event_name="PostToolUse", tool_name="Bash", session_id="other",
                                          tool_input={"command": "npm test"}, tool_response={"stdout": ""}))
        self.capture("post-tool", self.ev(hook_event_name="PostToolUse", tool_name="Bash",
                                          tool_input={"command": "npm run lint"}, tool_response={"stdout": ""}))
        self.assertEqual(self.signals(), [])

    def test_s6_from_copilot_cli_events(self):
        base = {"sessionId": "c1", "cwd": str(self.root), "toolName": "powershell"}
        self.capture("post-tool", dict(base, toolArgs={"command": "git rev-parse --verify main"}, toolResult={
            "resultType": "success", "textResultForLlm": "fatal\n<shellId: 1 completed with exit code 128>"}))
        self.capture("post-tool", dict(base, toolArgs={"command": "git rev-parse HEAD"}, toolResult={
            "resultType": "success", "textResultForLlm": "abc\n<shellId: 2 completed with exit code 0>"}))
        (c,) = cd.candidates(self.root)
        self.assertEqual((c["signal"], c["host"], c["evidence"]["failed_exit"]), ("S6", "copilot-cli", 128))

    def test_codex_reports_no_outcome(self):
        rec = self.capture("post-tool", self.ev(hook_event_name="PostToolUse", turn_id="t1", tool_name="Bash",
                                                tool_input={"command": "git rev-parse nope"},
                                                tool_response="fatal: Needed a single revision\n"))
        self.assertEqual((rec["host"], rec["decision"]), ("codex", "no-signal"))
        self.assertIn("no tool outcome", rec["detail"])

    def test_watched_path_write(self):
        abs_path = str(self.root / "docs" / "specs" / "retry.md")
        self.capture("post-tool", self.ev(hook_event_name="PostToolUse", tool_name="Write",
                                          tool_input={"file_path": abs_path, "content": "x"}, tool_response={}))
        self.capture("post-tool", self.ev(hook_event_name="PostToolUse", tool_name="Read",
                                          tool_input={"file_path": abs_path}, tool_response={}))
        (c,) = cd.candidates(self.root)
        self.assertEqual((c["signal"], c["evidence"]["path"], c["evidence"]["watch"]),
                         ("S9-S11", "docs/specs/retry.md", "docs/specs/"))
        self.assertNotIn(str(self.root), json.dumps(c["evidence"]))

    def test_watch_list_comes_from_project_config(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "amphion.config.json").write_text(
            json.dumps({"memory": {"watch": ["notes/decisions.md"]}}), encoding="utf-8")
        for path in ("notes/decisions.md", "docs/specs/a.md"):
            self.capture("post-tool", self.ev(tool_name="Edit", tool_input={"file_path": path}, tool_response={}))
        self.assertEqual([c["evidence"]["path"] for c in cd.candidates(self.root)], ["notes/decisions.md"])

    def test_fresh_eyes_skill(self):
        self.capture("post-tool", self.ev(hook_event_name="PostToolUse", tool_name="Skill",
                                          tool_input={"skill": "fresh-eyes-investigation"},
                                          tool_response={"success": True}))
        self.assertEqual(self.signals(), ["S8"])

    def test_hook_bodies_stay_inside_the_budget(self):
        recs = [self.capture("prompt", self.ev(prompt="from now on always page at 50")),
                self.capture("post-tool", self.ev(tool_name="Write", tool_input={"file_path": "docs/adr/1.md"},
                                                  tool_response={})),
                self.capture("stop", self.ev(stop_hook_active=False)),
                self.capture("pre-compact", self.ev())]
        for rec in recs:
            self.assertLess(rec["ms"], 200, rec)  # spec §4.7: each hook bounded at 200 ms

    def test_nothing_is_ever_stored_as_a_lesson(self):
        before = self.lesson_files()
        self.capture("prompt", self.ev(prompt="from now on, never squash. No, use merge commits instead."))
        self.capture("post-tool", self.ev(tool_name="Write", tool_input={"file_path": "docs/adr/2.md"},
                                          tool_response={}))
        self.capture("stop", self.ev(stop_hook_active=False))
        self.assertEqual(self.lesson_files(), before)
        self.assertEqual(len(cd.candidates(self.root)), 3)


class CandidateCli(_Project):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(["--repo", str(self.root), *argv])
        return rc, out.getvalue(), err.getvalue()

    def test_add_list_label_stats(self):
        ids = []
        for _ in range(2):
            rc, out, _ = self.run_cli("--format", "json", "candidate", "add", "--signal", "S4",
                                      "--evidence", '{"match": "always"}')
            self.assertEqual(rc, 0)
            ids.append(json.loads(out)["id"])
        self.assertEqual(self.run_cli("candidate", "label", ids[0], "lesson")[0], 0)
        self.assertEqual(self.run_cli("candidate", "label", ids[1], "noise", "--note", "chit-chat")[0], 0)
        rc, out, _ = self.run_cli("--format", "json", "candidate", "stats")
        (s4,) = json.loads(out)["signals"]
        self.assertEqual((s4["count"], s4["lesson"], s4["noise"], s4["precision"]), (2, 1, 1, 0.5))
        rc, out, _ = self.run_cli("candidate", "list")
        self.assertIn("CANDIDATES: 2 (0 pending, 2 labelled)", out)
        self.assertIn("note: chit-chat", out)
        rc, out, _ = self.run_cli("candidate", "list", "--pending")
        self.assertIn("CANDIDATES: 0", out)

    def test_label_rejects_an_unknown_id(self):
        rc, _, err = self.run_cli("candidate", "label", "C-00000000-000000", "lesson")
        self.assertEqual(rc, 2)
        self.assertIn("no candidate", err)

    def test_add_refuses_a_credential(self):
        rc, _, err = self.run_cli("candidate", "add", "--signal", "S6",
                                  "--evidence", json.dumps({"head": FAKE_CLOUD_KEY}))
        self.assertEqual(rc, 2)
        self.assertIn("cloud-access-key", err)
        self.assertFalse((cd.capture_dir(self.root) / "candidates.jsonl").exists())

    def test_doctor(self):
        rc, out, _ = self.run_cli("doctor")
        self.assertIn("no capture activity", out)
        self.capture("prompt", self.ev(prompt="from now on always page at 50"))
        self.capture("stop", self.ev(stop_hook_active=False))
        rc, out, _ = self.run_cli("doctor", "--last", "5")
        self.assertEqual(rc, 0)
        self.assertIn("self-ignored: yes", out)
        self.assertIn("would-block", out)
        self.assertIn("candidate S4", out)

    def test_decision_log_rotates(self):
        old = cd.DECISION_LOG_MAX
        cd.DECISION_LOG_MAX = 200
        try:
            for _ in range(6):
                self.capture("pre-compact", self.ev())
        finally:
            cd.DECISION_LOG_MAX = old
        self.assertTrue((cd.capture_dir(self.root) / "decisions.1.jsonl").exists())
        kept = cd.decisions(self.root)
        self.assertTrue(1 <= len(kept) < 6)  # the current log and one rotation; older ones go
        self.assertEqual(kept[-1]["mode"], "pre-compact")

    def test_doctor_counts_lines_written_past_a_busy_lock(self):
        self.capture("stop", self.ev(stop_hook_active=False))
        cd.log_decision(self.root, {"mode": "stop", "decision": "nothing-pending", "contended": True})
        self.assertEqual(cd.doctor(self.root)["contended"], 1)
        self.assertIn("1 line(s) written past a busy lock", self.run_cli("doctor")[1])


# Run as a process by the tests below: wait for `go`, then write through the real engine calls.
SPOOL_WRITER = r"""
import os, sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from mnemosyne import candidates as cd
repo, tag, lines, cap = Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
cd.DECISION_LOG_MAX = cap
Path(repo, "ready-" + tag).touch()
while not Path(repo, "go").exists():
    time.sleep(0.0005)
for i in range(lines):
    cd.add_candidate(repo, "S4", session=f"{tag}-{i}")
    cd.log_decision(repo, {"decision": "x", "session": f"{tag}-{i}", "note": "café " * 40})
"""


class SpoolConcurrency(unittest.TestCase):
    """The races are between processes, so `race` starts real ones. A lost line is a failure."""

    WRITERS = 8

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        (self.root / "memory").mkdir()
        cd.ensure_capture_dir(self.root)

    def race(self, lines, cap=cd.DECISION_LOG_MAX):
        """Start the writers, hold them until all are up, release them together."""
        (self.root / "go").unlink(missing_ok=True)
        for ready in self.root.glob("ready-*"):
            ready.unlink()
        tags = [f"w{n}" for n in range(self.WRITERS)]
        runs = [subprocess.Popen([sys.executable, "-c", SPOOL_WRITER, str(MNEMOSYNE_SRC), str(self.root),
                                  tag, str(lines), str(cap)]) for tag in tags]
        deadline = time.time() + 60
        while len(list(self.root.glob("ready-*"))) < len(tags) and time.time() < deadline:
            time.sleep(0.005)
        (self.root / "go").touch()
        for run in runs:
            self.assertEqual(run.wait(timeout=120), 0)
        return tags

    def test_concurrent_writers_lose_no_line_in_either_file(self):
        tags = self.race(lines=100)
        expected = sorted(f"{tag}-{i}" for tag in tags for i in range(100))
        self.assertEqual(sorted(c["session"] for c in cd.candidates(self.root)), expected)
        self.assertEqual(sorted(d["session"] for d in cd.decisions(self.root)), expected)

    def test_writers_racing_a_rotation_keep_the_rotated_log(self):
        """Two runs past the limit once both rotated: the second moved a near-empty log over the
        full one it had just kept. One rotation here, so every line must survive it."""
        log = cd.capture_dir(self.root) / cd.DECISIONS
        for attempt in range(3):
            seeded = [f"old-{attempt}-{i}" for i in range(300)]
            (cd.capture_dir(self.root) / "decisions.1.jsonl").unlink(missing_ok=True)
            log.write_text("".join(json.dumps({"session": s}) + "\n" for s in seeded), encoding="utf-8")
            cap = log.stat().st_size - 1
            tags = self.race(lines=1, cap=cap)
            kept = [d["session"] for d in cd.decisions(self.root)]
            self.assertEqual(sorted(kept), sorted(seeded + [f"{tag}-0" for tag in tags]))
            self.assertTrue((cd.capture_dir(self.root) / "decisions.1.jsonl").exists())

    def full_log(self):
        d = cd.capture_dir(self.root)
        (d / cd.DECISIONS).write_text('{"session":"full"}\n' * 20, encoding="utf-8")
        return d, d / cd.DECISIONS, d / "decisions.1.jsonl"

    def test_a_run_that_lost_the_rotation_does_not_rotate_again(self):
        """The interleaving that clobbered the kept log: this run saw a full log, then a rival
        rotated before this run got as far as the lock."""
        d, log, kept = self.full_log()
        real = core._try_os_lock

        def rival_rotates_first(fd):
            if not kept.exists():
                os.replace(log, kept)
                log.write_text('{"session":"after"}\n', encoding="utf-8")
            return real(fd)

        with mock.patch.object(cd, "DECISION_LOG_MAX", 100), \
                mock.patch.object(core, "_try_os_lock", side_effect=rival_rotates_first):
            cd.log_decision(self.root, {"session": "mine"})
        sessions = [r["session"] for r in cd.decisions(self.root)]
        self.assertEqual(sessions, ["full"] * 20 + ["after", "mine"])

    def test_a_run_that_cannot_lock_leaves_the_rotation_to_the_next(self):
        d, log, kept = self.full_log()
        holder = os.open(str(d / cd.ROTATE_LOCK), os.O_RDWR | os.O_CREAT)
        self.addCleanup(os.close, holder)
        self.assertTrue(core._try_os_lock(holder))
        with mock.patch.object(cd, "DECISION_LOG_MAX", 100):
            cd.log_decision(self.root, {"session": "mine"})
            self.assertFalse(kept.exists())
            core._os_unlock(holder)
            cd.log_decision(self.root, {"session": "next"})
        self.assertTrue(kept.exists())
        self.assertEqual([r["session"] for r in cd.decisions(self.root)], ["full"] * 20 + ["mine", "next"])

    def test_a_line_is_written_whole_and_unconverted(self):
        path = cd.capture_dir(self.root) / cd.DECISIONS
        cd.log_decision(self.root, {"note": "café"})
        cd.log_decision(self.root, {"note": "x" * 70_000})
        raw = path.read_bytes()
        self.assertEqual(raw.count(b"\n"), 2)
        self.assertNotIn(b"\r", raw)
        self.assertEqual(cd.decisions(self.root)[0]["note"], "café")

    def test_a_reader_never_blocks_an_append(self):
        path = cd.capture_dir(self.root) / cd.DECISIONS
        cd.log_decision(self.root, {"session": "a"})
        with open(path, encoding="utf-8") as reader:
            cd.log_decision(self.root, {"session": "b"})
            self.assertIn('"a"', reader.read())
        self.assertEqual([d["session"] for d in cd.decisions(self.root)], ["a", "b"])

    def test_a_torn_multibyte_line_is_skipped_on_read(self):
        path = cd.capture_dir(self.root) / cd.DECISIONS
        path.write_bytes(b'{"session":"a"}\n{"session":"caf\xc3\n{"session":"b"}\n')
        self.assertEqual([d["session"] for d in cd.decisions(self.root)], ["a", "b"])

    @unittest.skipIf(os.name == "nt", "Windows appends take no lock: the kernel picks the offset")
    def test_a_held_lock_delays_a_write_but_never_drops_it(self):
        path = cd.capture_dir(self.root) / cd.DECISIONS
        holder = os.open(f"{path}.lock", os.O_RDWR | os.O_CREAT)
        self.addCleanup(os.close, holder)
        self.assertTrue(core._try_os_lock(holder))
        with mock.patch.object(cd, "SPOOL_LOCK_WAIT", 0.05):
            t0 = time.perf_counter()
            cd.log_decision(self.root, {"session": "a"})
            waited = time.perf_counter() - t0
        self.assertLess(waited, 1)
        self.assertEqual([(d["session"], d["contended"]) for d in cd.decisions(self.root)], [("a", True)])

    @unittest.skipIf(os.name == "nt", "Windows appends take no lock: the kernel picks the offset")
    def test_a_filesystem_without_locks_still_gets_the_line(self):
        with mock.patch.object(core, "_try_os_lock", side_effect=OSError("no locks here")):
            cd.log_decision(self.root, {"session": "a"})
        self.assertEqual([d["session"] for d in cd.decisions(self.root)], ["a"])


class DoubleFire(_Project):
    """A repo's .github/hooks/mnemosyne.json and the user-level ~/.copilot/hooks copy both present:
    the host runs a bridge from each for one event (spec §4.7, Phase 2's exit criterion)."""

    def setUp(self):
        super().setUp()
        self.addCleanup(self._td.cleanup)     # after any open handle below has closed
        self.copies = []
        for folder in (self.root / ".github" / "hooks", self.root / "home" / ".copilot" / "hooks"):
            folder.mkdir(parents=True)
            self.copies.append(shutil.copy(HOOK, folder))
        self.env = {k: v for k, v in self.env.items() if k != "CLAUDECODE"}
        self.env["COPILOT_CLI"] = "1"

    def ev(self, **kw):
        return dict({"sessionId": "c1", "cwd": str(self.root)}, **kw)

    def fire_both(self, mode, event):
        for script in self.copies:
            proc = subprocess.run([sys.executable, script, mode], input=json.dumps(event),
                                  capture_output=True, text=True, env=self.env, cwd=str(self.root))
            self.assertEqual((proc.returncode, proc.stderr), (0, ""))

    def verdicts(self):
        return [d["decision"] for d in cd.decisions(self.root)]

    def bridge(self):
        spec = importlib.util.spec_from_file_location("mnemosyne_hook_double_fire", HOOK)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def age_markers(self):
        old = time.time() - cd.FIRE_WINDOW - 1
        for marker in (cd.capture_dir(self.root) / cd.FIRED).iterdir():
            os.utime(marker, (old, old))

    def test_both_files_record_one_candidate_for_each_mode(self):
        self.fire_both("prompt", self.ev(prompt="from now on always rebase"))
        self.assertEqual(self.signals(), ["S4"])
        self.assertEqual(self.verdicts(), ["candidate", "duplicate"])
        tool = self.ev(toolName="create", toolArgs={"path": "docs/adr/0001-x.md"})
        self.fire_both("post-tool", tool)
        self.assertEqual(self.signals(), ["S4", "S9-S11"])
        for mode, verdict in (("session-start", "session-start"), ("stop", "would-block"),
                              ("pre-compact", "flushed")):
            self.fire_both(mode, self.ev())
            self.assertEqual(self.verdicts()[-2:], [verdict, "duplicate"], mode)

    def test_runs_at_the_same_moment_still_claim_once(self):
        event = json.dumps(self.ev(prompt="from now on always rebase"))
        runs = [subprocess.Popen([sys.executable, HOOK, "prompt"], stdin=subprocess.PIPE, text=True,
                                 env=self.env, cwd=str(self.root)) for _ in range(6)]
        for run in runs:
            run.stdin.write(event)
            run.stdin.close()
        for run in runs:
            self.assertEqual(run.wait(timeout=60), 0)
        self.assertEqual(self.signals(), ["S4"])       # only the claim's winner writes the spool
        self.assertEqual(sorted(self.verdicts()), ["candidate"] + ["duplicate"] * 5)  # and all logged

    def test_the_second_run_prints_no_recall_and_syncs_nothing(self):
        bridge = self.bridge()
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch("mnemosyne.recall", return_value="L-0001 rebase first") as recall, \
                redirect_stdout(io.StringIO()) as out:
            for _ in range(2):
                bridge.do_prompt(self.ev(prompt="how do we merge"), None)
        self.assertEqual(recall.call_count, 1)
        self.assertEqual(out.getvalue().count("L-0001"), 1)
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(core, "sync") as sync, \
                mock.patch.object(core, "sync_has_work", return_value=True):
            for _ in range(2):
                bridge.do_session_start(self.ev(), None)
        self.assertEqual(sync.call_count, 1)

    def test_a_bridge_from_before_the_guard_is_covered_for_capture(self):
        """Only the engine changes: a committed copy calls capture_event and ignores the result."""
        for _ in range(2):
            self.capture("prompt", self.ev(prompt="from now on always rebase"))
        self.assertEqual(self.signals(), ["S4"])

    def test_one_event_matches_across_the_two_hook_formats(self):
        # Copilot 1.0.88 ran both, with snake_case stdin and its shell renamed to Bash (§4.7.1).
        copilot = self.ev(toolName="powershell", toolArgs={"command": "npm test"}, toolResult={
            "resultType": "success", "textResultForLlm": "x\n<shellId: 1 completed with exit code 2>"})
        claude = {"session_id": "c1", "cwd": str(self.root), "hook_event_name": "PostToolUse",
                  "tool_name": "Bash", "tool_input": {"command": "npm test"}, "tool_result": json.dumps(
                      {"text_result_for_llm": "x\n<shellId: 1 completed with exit code 2>"})}
        self.assertEqual(cd.fire_key("post-tool", copilot, self.root), cd.fire_key("post-tool", claude, self.root))

    def test_different_events_are_not_duplicates(self):
        prompt = self.ev(prompt="from now on always rebase")
        self.capture("prompt", prompt)
        self.capture("prompt", dict(prompt, sessionId="c2"))             # another session
        self.capture("prompt", dict(prompt, prompt="from now on squash"))   # another prompt
        self.capture("stop", self.ev())                                  # another mode
        self.capture("stop", self.ev(stop_hook_active=True))             # the re-fire after a block
        self.assertNotIn(cd.DUPLICATE, self.verdicts())

    def test_a_command_that_fails_then_passes_is_two_events(self):
        base = self.ev(toolName="powershell", toolArgs={"command": "npm test"})
        for code in (1, 0):
            self.capture("post-tool", dict(base, toolResult={
                "resultType": "success", "textResultForLlm": f"<shellId: 1 completed with exit code {code}>"}))
        self.assertEqual(self.signals(), ["S6"])

    def test_a_real_repeat_after_the_window_counts_again(self):
        event = self.ev(prompt="from now on always rebase")
        self.capture("prompt", event)
        self.age_markers()
        self.capture("prompt", event)
        self.assertEqual(self.signals(), ["S4", "S4"])
        self.assertEqual(self.verdicts(), ["candidate", "candidate"])

    def test_expired_markers_are_cleared(self):
        for n in range(5):
            self.capture("prompt", self.ev(prompt=f"prompt {n}"))
        self.age_markers()
        self.capture("prompt", self.ev(prompt="one more"))
        self.assertEqual(len(list((cd.capture_dir(self.root) / cd.FIRED).iterdir())), 1)

    def test_a_guard_that_cannot_claim_lets_the_event_through(self):
        (cd.ensure_capture_dir(self.root) / cd.FIRED).write_text("not a folder", encoding="utf-8")
        for _ in range(2):
            self.capture("prompt", self.ev(prompt="from now on always rebase"))
        self.assertEqual(self.signals(), ["S4", "S4"])

    def test_a_session_less_event_falls_back_to_the_project(self):
        event = {"cwd": str(self.root), "prompt": "from now on always rebase"}
        self.capture("prompt", event)
        self.capture("prompt", event)
        self.assertEqual(self.signals(), ["S4"])
        with tempfile.TemporaryDirectory() as other:
            self.assertNotEqual(cd.fire_key("prompt", event, self.root), cd.fire_key("prompt", event, Path(other)))

    def test_the_markers_are_never_committed(self):
        self.capture("prompt", self.ev(prompt="x"))
        self.assertTrue(cd.is_self_ignored(self.root))
        self.assertEqual(list((cd.capture_dir(self.root) / cd.FIRED).iterdir())[0].stat().st_size, 0)


class SessionStartSkipsIdleSync(unittest.TestCase):
    """session-start syncs only when there is something to pull. In a local-only memory repo,
    sync's git children cost ~300 ms on Windows (658 ms -> 147 ms measured 2026-11-01)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name) / "mem"
        core.init_repo(self.repo)
        self.git("init", "-q")
        spec = importlib.util.spec_from_file_location("mnemosyne_hook_under_test", HOOK)
        self.bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.bridge)
        env = {k: v for k, v in os.environ.items() if k not in HOST_ENV}
        env["MNEMOSYNE_REPO"] = str(self.repo)
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def git(self, *args, cwd=None):
        subprocess.run(["git", "-C", str(cwd or self.repo), *args], check=True,
                       capture_output=True, stdin=subprocess.DEVNULL)

    def session_start(self):
        with mock.patch.object(core, "sync") as sync:
            self.bridge.do_session_start({"hook_event_name": "SessionStart"}, None)
        return sync.called

    def test_no_remote_no_store_skips_sync(self):
        self.assertFalse(core.has_remote(self.repo))
        self.assertFalse(self.session_start())

    def test_a_remote_brings_sync_back(self):
        self.git("remote", "add", "origin", "https://example.invalid/memory.git")
        self.assertTrue(core.has_remote(self.repo))
        self.assertTrue(self.session_start())

    def test_a_store_brings_sync_back(self):
        (self.repo / "mnemosyne.config.json").write_text(json.dumps(
            {"stores": [{"tier": "team", "prefix": "T", "path": str(self.repo / "team")}]}),
            encoding="utf-8")
        self.assertTrue(self.session_start())

    def test_a_plain_folder_has_no_remote(self):
        with tempfile.TemporaryDirectory() as plain:
            self.assertFalse(core.has_remote(Path(plain)))

    def test_a_linked_worktree_reads_the_common_config(self):
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com",
                 "commit", "-q", "--allow-empty", "-m", "init")
        self.git("remote", "add", "origin", "https://example.invalid/memory.git")
        linked = Path(self._td.name) / "linked"
        self.git("worktree", "add", "-q", "--detach", str(linked))
        self.assertTrue(core.has_remote(linked))


class PluginRegistration(unittest.TestCase):
    def test_hooks_json_registers_each_mode_once(self):
        hooks = json.loads((HOOK.parent / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        expected = {"SessionStart": "session-start", "UserPromptSubmit": "prompt", "PostToolUse": "post-tool",
                    "PostToolUseFailure": "post-tool", "Stop": "stop", "PreCompact": "pre-compact"}
        self.assertEqual(set(hooks), set(expected))
        for event, mode in expected.items():
            (group,) = hooks[event]
            (entry,) = group["hooks"]
            self.assertTrue(entry["command"].endswith(f'mnemosyne_hook.py" {mode}'), entry["command"])


if __name__ == "__main__":
    unittest.main()
