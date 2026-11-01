"""CI coverage for lessons capture in shadow mode (docs/lessons-capture-spec.md, Phase 0).

The capture hooks detect signals and append candidates to memory/.capture/, log one decision per
invocation, and do nothing else: no lesson is stored, nothing is asked, no capture mode prints.
Event payloads below use the field names observed on real Claude Code, Copilot CLI and Codex
installs (spec §4.7.1), and every guard is driven with its variable set the way the host sets it.
Offline: the only subprocesses are the hook bridge itself and a local `git init`.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

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
