"""Phase -1: remediate existing issues, so the change starts from green (``zethus/docs/phase-minus-one.md``).

Ceryce's request, 2026-11-20 (paraphrased): before any planned change, run the repo's own gates and
fix whatever already fails them, so her change starts from green, instead of finding pre-existing
failures (checkstyle CRLF findings, say) only after making the change. These tests pin the survey
and its record and log, the green no-op, a CRLF finding fixed in Phase -1 with Phase 0 stacked on
it, an unfixable failure asked at sign-off through the Gate remediation rulings, the scope check
that keeps Phase -1 to the fix, the stop hook, and the prose beside them.
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
SCRIPTS = KIT / "scripts"
BASELINE = SCRIPTS / "baseline-gates.py"
GATES = SCRIPTS / "run-local-gates.py"
CHECK = SCRIPTS / "gate-remediation-check.py"
GUARD = KIT / "com.github.copilot" / "hooks" / "stop_guard.py"

sys.path.insert(0, str(SCRIPTS))
import _gate_rulings as gr  # noqa: E402


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod      # dataclasses look their module up while being defined
    spec.loader.exec_module(mod)
    return mod


baseline = load("baseline_gates", BASELINE)
check = load("gate_remediation_check_p1", CHECK)
guard = load("stop_guard_p1", GUARD)

# A checkstyle stand-in: fails on any tracked .java file with CRLF line endings, printing the
# absolute path the way the Maven plugin does, and the rule in brackets the way checkstyle does.
CHECKSTYLE = r'''
import os, subprocess, sys
bad = 0
for path in subprocess.run(["git", "ls-files", "*.java"], capture_output=True, text=True).stdout.split():
    data = open(path, "rb").read()
    for n, line in enumerate(data.split(b"\n"), 1):
        if line.endswith(b"\r"):
            print(f"[ERROR] {os.path.abspath(path)}:{n}: Line has Windows line ending (CRLF). [RegexpMultiline]")
            bad += 1
print(f"[INFO] checked, {bad} violation(s)")
sys.exit(1 if bad else 0)
'''

FOO_CRLF = b"class Foo {\r\n    int x = 1;\r\n}\r\n"
FOO_LF = FOO_CRLF.replace(b"\r\n", b"\n")


def git(root: Path, *args: str, check_ok: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=t@example.com",
                           "-c", "commit.gpgsign=false", *args], capture_output=True, text=True)
    if check_ok and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {proc.stderr}")
    return proc


class Repo:
    """A throwaway repo with a checkstyle gate and a passing test gate, its base committed."""

    def __init__(self, tc: unittest.TestCase, crlf: bool = True, extra_gates=()):
        self.tmp = tempfile.TemporaryDirectory()
        tc.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "repo"
        self.root.mkdir()
        self.log = Path(self.tmp.name) / "baseline.log"
        subprocess.run(["git", "init", "-q", "-b", "develop", str(self.root)], check=True)
        git(self.root, "config", "core.autocrlf", "false")
        (self.root / "tools").mkdir()
        (self.root / "tools" / "checkstyle.py").write_text(CHECKSTYLE, encoding="utf-8")
        (self.root / "src").mkdir()
        (self.root / "src" / "Foo.java").write_bytes(FOO_CRLF if crlf else FOO_LF)
        steps = [{"name": "checkstyle", "command": [sys.executable, "tools/checkstyle.py"]},
                 {"name": "unittest", "command": [sys.executable, "-c", "pass"]}, *extra_gates]
        (self.root / ".github").mkdir()
        (self.root / ".github" / "zethus.config.json").write_text(
            json.dumps({"gates": {"steps": steps}}), encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "base")
        self.base = git(self.root, "rev-parse", "HEAD").stdout.strip()

    def baseline(self, *args: str) -> tuple[int, str]:
        r = subprocess.run([sys.executable, str(BASELINE), "--repo", str(self.root), "--log", str(self.log),
                            *args], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def gates(self) -> tuple[int, str]:
        r = subprocess.run([sys.executable, str(GATES), "--repo", str(self.root)], capture_output=True, text=True)
        return r.returncode, r.stdout

    def record(self) -> dict:
        path = git(self.root, "rev-parse", "--git-path", "zethus/baseline-gates.json").stdout.strip()
        return json.loads((self.root / path).read_text(encoding="utf-8"))

    def commit(self, message: str):
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", message)


class Survey(unittest.TestCase):
    def test_a_green_base_is_a_no_op_said_in_one_line(self):
        repo = Repo(self, crlf=False)
        code, out = repo.baseline("survey")
        self.assertEqual(code, 0, out)
        lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1, out)
        self.assertIn("Phase -1: nothing to remediate", lines[0])
        self.assertIn("None — every local gate is green on the untouched base", lines[0])
        self.assertEqual(repo.record()["findings"], [])
        log = repo.log.read_text(encoding="utf-8")
        self.assertIn("start mode=survey", log)
        self.assertIn("gate checkstyle: PASS", log)
        self.assertIn("Phase -1 is a no-op", log)
        self.assertIn("exit 0", log)

    def test_it_refuses_a_tree_that_is_not_the_untouched_base(self):
        repo = Repo(self)
        (repo.root / "src" / "Foo.java").write_bytes(FOO_LF)
        code, out = repo.baseline("survey")
        self.assertEqual(code, 2, out)
        self.assertIn("not an untouched base", out)
        self.assertIn("refused", repo.log.read_text(encoding="utf-8"))

    def test_untracked_files_do_not_stop_the_survey(self):
        repo = Repo(self, crlf=False)
        (repo.root / "notes.txt").write_text("scratch", encoding="utf-8")
        self.assertEqual(repo.baseline("survey")[0], 0)

    def test_a_skipped_gate_is_not_a_green_base(self):
        repo = Repo(self, crlf=False, extra_gates=[{"name": "sonar", "command": "no-such-tool-zz scan"}])
        code, out = repo.baseline("survey")
        self.assertEqual(code, 3, out)
        self.assertIn("Not a full survey", out)
        self.assertNotIn("nothing to remediate", out)

    def test_a_failure_with_no_file_is_kept_as_one_gate_level_row(self):
        repo = Repo(self, crlf=False, extra_gates=[
            {"name": "integration", "command": [sys.executable, "-c", "import sys; print('boom'); sys.exit(3)"]}])
        code, out = repo.baseline("survey")
        self.assertEqual(code, 1, out)
        self.assertIn("| integration | — | exit 3 | fix |", out)


class CrlfFixedInPhaseMinusOneThenPhase0Stacks(unittest.TestCase):
    """The case from the request: checkstyle's CRLF finding on the base, fixed apart from the change."""

    def test_the_whole_flow(self):
        repo = Repo(self)
        # Stage 0: survey the untouched base.
        code, out = repo.baseline("survey")
        self.assertEqual(code, 1, out)
        self.assertIn("| checkstyle | `src/Foo.java` | RegexpMultiline (×3) | fix |", out)
        finding = repo.record()["findings"][0]
        self.assertEqual((finding["gate"], finding["file"], finding["rule"]),
                         ("checkstyle", "src/Foo.java", "RegexpMultiline"))
        self.assertEqual(repo.record()["head"], repo.base)
        log = repo.log.read_text(encoding="utf-8")
        for what in ("gate checkstyle: run", "gate checkstyle: FAIL", "finding: checkstyle | src/Foo.java:1 | "
                     "RegexpMultiline (x3) [layout]", "verdict: RED"):
            self.assertIn(what, log)

        # Phase -1: its own branch off the base, the fix alone.
        git(repo.root, "switch", "-q", "-c", "feature/retry-phase-minus-1")
        (repo.root / "src" / "Foo.java").write_bytes(FOO_LF)
        repo.commit("fix(style): phase -1 — LF line endings in Foo.java")
        code, out = repo.baseline("scope")
        self.assertEqual(code, 0, out)
        self.assertIn("| checkstyle | `src/Foo.java` | RegexpMultiline | changed |", out)
        self.assertIn("IN SCOPE", out)
        self.assertEqual(repo.record()["scope"]["findings"][0]["state"], "changed")
        self.assertIn("finding checkstyle | src/Foo.java | RegexpMultiline: changed",
                      repo.log.read_text(encoding="utf-8"))
        self.assertEqual(repo.gates()[0], 0, "Phase -1 pushes green")

        # Phase 0: stacked on Phase -1's branch; its diff against that branch is the change alone.
        git(repo.root, "switch", "-q", "-c", "feature/retry-phase-0", "feature/retry-phase-minus-1")
        (repo.root / "src" / "Bar.java").write_bytes(b"class Bar {\n}\n")
        repo.commit("feat(retry): phase 0 — pin today's behaviour")
        self.assertEqual(git(repo.root, "merge-base", "--is-ancestor", "feature/retry-phase-minus-1",
                             "feature/retry-phase-0", check_ok=False).returncode, 0)
        shown = git(repo.root, "diff", "--name-only", "feature/retry-phase-minus-1...feature/retry-phase-0").stdout
        self.assertEqual(shown.split(), ["src/Bar.java"], "Phase 0's PR shows the planned change alone")
        code, out = repo.gates()
        self.assertEqual(code, 0, "Phase 0 starts from green: " + out)

    def test_without_phase_minus_one_the_change_meets_the_red_base(self):
        repo = Repo(self)
        (repo.root / "src" / "Bar.java").write_bytes(b"class Bar {\n}\n")
        code, out = repo.gates()
        self.assertEqual(code, 1)
        self.assertIn("RED — fix before pushing: checkstyle", out)


class Scope(unittest.TestCase):
    """Phase -1 never touches the planned change's files beyond the fix."""

    def setUp(self):
        self.repo = Repo(self)
        self.assertEqual(self.repo.baseline("survey")[0], 1)
        git(self.repo.root, "switch", "-q", "-c", "phase-minus-1")

    def test_a_planned_change_file_in_phase_minus_one_is_out_of_scope(self):
        (self.repo.root / "src" / "Foo.java").write_bytes(FOO_LF)
        (self.repo.root / "src" / "Bar.java").write_bytes(b"class Bar {\n}\n")
        self.repo.commit("mixed")
        code, out = self.repo.baseline("scope")
        self.assertEqual(code, 1, out)
        self.assertIn("src/Bar.java: no finding names it", out)
        self.assertIn("the planned change goes in Phase 0", out)
        self.assertIn("file src/Bar.java: OUT OF SCOPE", self.repo.log.read_text(encoding="utf-8"))

    def test_a_layout_file_changed_beyond_whitespace_is_out_of_scope(self):
        (self.repo.root / "src" / "Foo.java").write_bytes(FOO_LF.replace(b"x = 1", b"x = 2"))
        code, out = self.repo.baseline("scope")       # uncommitted work counts too
        self.assertEqual(code, 1, out)
        self.assertIn("changed in more than whitespace", out)

    def test_also_admits_a_file_the_fix_needs_and_the_spec_dir_is_always_in(self):
        (self.repo.root / "src" / "Foo.java").write_bytes(FOO_LF)
        (self.repo.root / ".gitattributes").write_text("*.java text eol=lf\n", encoding="utf-8")
        (self.repo.root / "docs" / "specs").mkdir(parents=True)
        (self.repo.root / "docs" / "specs" / "retry.md").write_text("# Retry\n", encoding="utf-8")
        self.assertEqual(self.repo.baseline("scope")[0], 1)
        code, out = self.repo.baseline("scope", "--also", ".gitattributes")
        self.assertEqual(code, 0, out)

    def test_scope_without_a_survey_is_a_usage_error(self):
        repo = Repo(self)
        code, out = repo.baseline("scope")
        self.assertEqual(code, 2)
        self.assertIn("no survey record", out)


def spec_text(status="DRAFT", phases="| 0 | Add the test | None | x |", pre=None, gate="None — nothing deferred."):
    body = (f"# S\n\n**Status:** {status} · **Owner:** o\n\n## Phases\n\n"
            f"| Phase | What | Behaviour change | Verified by |\n|---|---|---|---|\n{phases}\n\n")
    if pre is not None:
        body += f"## Pre-existing gate failures\n\n{pre}\n\n"
    return body + f"## Gate remediation\n\n{gate}\n\n## Test plan\n\nt\n"


P1_ROW = "| -1 | Remediate existing issues: fix the pre-existing gate failures | None | scope |\n| 0 | Add the test | None | x |"
PRE_TABLE = "| Gate | File | Rule | Phase -1 |\n|---|---|---|---|\n"
FIX = PRE_TABLE + "| checkstyle | `src/Foo.java` | RegexpMultiline | fix |"
ASK = PRE_TABLE + "| maven verify | `src/test/FooTest.java` | testParse fails | ask |"


def ruling(gate="maven verify", approved="PENDING", kind="push-red"):
    return (f"| Gate | Remediation phase | Ruling | Approved |\n|---|---|---|---|\n"
            f"| {gate} | Phase -1 | {kind} | {approved} |")


class SpecSection(unittest.TestCase):
    def problems(self, text):
        return check.check_spec(text, None)

    def test_none_is_a_complete_answer(self):
        self.assertEqual(self.problems(spec_text(pre="None — every local gate is green on the untouched base (abc1234).")), [])

    def test_a_draft_without_the_section_fails_and_an_older_signed_spec_does_not(self):
        self.assertTrue(any("Pre-existing gate failures" in p for p in self.problems(spec_text())))
        self.assertEqual(self.problems(spec_text("SIGNED-OFF")), [])

    def test_fix_rows_need_a_phase_minus_one_row(self):
        self.assertTrue(any("no Phase -1 row" in p for p in self.problems(spec_text(pre=FIX))))
        self.assertEqual(self.problems(spec_text(phases=P1_ROW, pre=FIX)), [])

    def test_the_phase_minus_one_row_is_not_a_later_remediation_phase(self):
        self.assertEqual(gr.remediation_phase_rows(spec_text(phases=P1_ROW)), [])
        self.assertEqual(gr.remediation_phase_rows(spec_text(phases="| 2 | Remediate the lint findings | None | x |")),
                         ["| 2 | Remediate the lint findings | None | x |"])

    def test_an_unreadable_action_fails(self):
        out = self.problems(spec_text(phases=P1_ROW, pre=FIX.replace("| fix |", "| later |")))
        self.assertTrue(any("is not `fix` or `ask`" in p for p in out), out)

    def test_an_unfixable_failure_is_asked_at_sign_off(self):
        out = self.problems(spec_text(pre=ASK))
        self.assertTrue(any("needs a Gate remediation row" in p for p in out), out)
        self.assertEqual(self.problems(spec_text(pre=ASK, gate=ruling())), [], "PENDING is the question, in a draft")
        out = self.problems(spec_text("SIGNED-OFF", pre=ASK, gate=ruling()))
        self.assertTrue(any("not approved" in p for p in out), "signed off with the question unanswered")
        self.assertEqual(self.problems(spec_text("SIGNED-OFF", pre=ASK, gate=ruling(approved="yes — Ceryce, 2026-11-20"))), [])

    def test_both_templates_carry_the_section_and_the_phase_minus_one_row(self):
        for name in ("spec-minimum.md", "spec-full.md"):
            text = (KIT / "templates" / name).read_text(encoding="utf-8").replace("{{status}}", "DRAFT")
            self.assertIn("## Pre-existing gate failures", text, name)
            self.assertTrue(gr.has_phase_minus_one(text), name)
            self.assertIn("baseline-gates.py survey", text, name)
            out = self.problems(text)
            self.assertTrue(any("Pre-existing gate failures is neither" in p for p in out),
                            f"{name}: unedited, the placeholder must not pass")


class UnfixableRuledAtSignOffThroughTheGateVerdict(unittest.TestCase):
    """An `ask` row's ruling is read by run-local-gates like any other phase's."""

    def setUp(self):
        self.repo = Repo(self, crlf=False, extra_gates=[
            {"name": "maven verify", "command": [sys.executable, "-c", "import sys; sys.exit(1)"]}])

    def spec(self, gate_section: str):
        d = self.repo.root / "docs" / "specs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "change.md").write_text(spec_text("SIGNED-OFF", pre=ASK, gate=gate_section), encoding="utf-8")

    def test_an_approved_push_red_for_phase_minus_one_is_exit_4(self):
        self.spec(ruling(approved="yes — Ceryce, 2026-11-20"))
        code, out = self.repo.gates()
        self.assertEqual(code, 4, out)
        self.assertIn("GREEN except gate(s) the approved plan lets stay red: maven verify", out)

    def test_a_pending_or_non_waiving_ruling_waives_nothing(self):
        for section in (ruling(), ruling(approved="yes — Ceryce, 2026-11-20", kind="other: fix the test as ruled")):
            with self.subTest(section=section):
                self.spec(section)
                self.assertEqual(self.repo.gates()[0], 1)


PHASE_MINUS_ONE_ASK = """Stage 3 · Implement — Phase -1, step 1 of 3: fix the pre-existing checkstyle findings

The survey found checkstyle failing on the untouched base: CRLF line endings in src/Foo.java.

Stopped at: Stage 3 · Implement — Phase -1
Next: convert the line endings
Why: waiting for your approval to fix the pre-existing checkstyle failures in Phase -1
"""
ORIENT_ASK = """Stage 1 · Research — step 2 of 4: read the retry loop

The base already fails checkstyle (CRLF in src/Foo.java), unrelated to your change.

Stopped at: Stage 1 · Research
Next: Stage 2 · Spec
Why: do you want me to fix these, or leave them red? waiting for your answer
"""
SIGN_OFF_ASK = """Stage 2 · Spec — step 4 of 4: waiting for sign-off

Pre-existing gate failures: maven verify fails on the untouched base (FooTest.testParse). Phase -1
can't fix it safely: the test and the code disagree. Approve pushing with it red, or name the fix.

Stopped at: Stage 2 · Spec
Next: Stage 3 · Implement — Phase -1
Why: waiting for your sign-off and your ruling on the pre-existing maven verify failure
"""
DECISION_MID_PHASE = """Stage 3 · Implement — Phase -1, step 2 of 3: the build compiles again

With the build fixed, FooTest.testParse fails on the base too. Should it expect the old format or
the new one? The code and the test disagree, and neither the spec nor the history settles it.

Stopped at: Stage 3 · Implement — Phase -1
Next: apply your answer, then the gates
Why: waiting for your decision on which behaviour FooTest.testParse should pin
"""


class StopHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sid = f"p1{os.getpid()}-{id(self)}"
        counter = guard.refusals_file({"sessionId": self.sid})
        counter.unlink(missing_ok=True)
        self.addCleanup(counter.unlink, missing_ok=True)

    def event(self, reply: str) -> dict:
        path = Path(self.tmp.name) / "t.jsonl"
        path.write_text(json.dumps({"type": "assistant.message", "data": {"content": reply}}), encoding="utf-8")
        return {"sessionId": self.sid, "transcriptPath": str(path)}

    def test_asking_leave_to_fix_a_pre_existing_failure_is_refused(self):
        for reply in (PHASE_MINUS_ONE_ASK, ORIENT_ASK):
            with self.subTest(reply=reply.splitlines()[0]):
                self.assertTrue(guard.asks_about_pre_existing(reply))
                out = json.loads(guard.refuse(self.event(reply), reply))
                self.assertEqual(out["decision"], "block")
                self.assertIn("Phase -1's to fix", out["reason"])
                self.assertIn("baseline-gates.py scope", out["reason"])
                (guard.refusals_file({"sessionId": self.sid})).unlink(missing_ok=True)

    def test_the_sign_off_stop_and_a_real_decision_are_untouched(self):
        for reply in (SIGN_OFF_ASK, DECISION_MID_PHASE):
            with self.subTest(reply=reply.splitlines()[0]):
                self.assertFalse(guard.asks_about_pre_existing(reply))
                self.assertEqual(guard.refuse(self.event(reply), reply), "")

    def test_prompt_mode_tells_the_next_turn_to_fix_it(self):
        out = json.loads(guard.remind(self.event(PHASE_MINUS_ONE_ASK)))
        self.assertIn("already on the base", out["additionalContext"])

    def test_it_cannot_trap_a_session(self):
        ev = self.event(PHASE_MINUS_ONE_ASK)
        got = [bool(guard.refuse(ev, PHASE_MINUS_ONE_ASK)) for _ in range(guard.MAX_REFUSALS + 1)]
        self.assertEqual(got, [True] * guard.MAX_REFUSALS + [False])


class Findings(unittest.TestCase):
    """The output shapes the survey reads a file and a rule from."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        self.tracked = {"src/a.py", "src/App.java", "web/app.js", "README.md"}

    def one(self, output: str):
        found = baseline.extract("g", output, self.root, self.tracked)
        self.assertEqual(len(found), 1, found)
        return found[0].file, found[0].rule

    def test_each_shape(self):
        abs_java = (self.root / "src" / "App.java").as_posix()
        cases = {
            "src/a.py:3:1: E501 Line too long (120 > 100)": ("src/a.py", "E501"),
            f"[WARN] {abs_java}:[10,5] (whitespace) WhitespaceAround: '=' is not preceded": ("src/App.java", "WhitespaceAround"),
            f"[ERROR] {abs_java}:1: Line has trailing spaces. [RegexpSingleline]": ("src/App.java", "RegexpSingleline"),
            "web/app.js: line 3, col 5, Error - 'x' is unused. (no-unused-vars)": ("web/app.js", "no-unused-vars"),
            "src/App.java:12: error: cannot find symbol": ("src/App.java", "cannot find symbol"),
            "README.md:4: trailing whitespace.": ("README.md", "trailing whitespace."),
        }
        for line, want in cases.items():
            with self.subTest(line=line):
                self.assertEqual(self.one(line), want)

    def test_eslint_stylish_names_the_file_on_its_own_line(self):
        out = "web/app.js\n  3:5  error  'x' is defined but never used  no-unused-vars\n\n1 problem"
        self.assertEqual(self.one(out), ("web/app.js", "no-unused-vars"))

    def test_untracked_and_info_lines_are_not_findings(self):
        out = "[INFO] src/App.java:1: compiled\ntarget/out.jar:1: built\n"
        self.assertEqual(baseline.extract("g", out, self.root, self.tracked), [])

    def test_layout_rules_are_recognised(self):
        self.assertTrue(baseline.Finding("g", "f", "RegexpMultiline", text="Line has CRLF").layout)
        self.assertTrue(baseline.Finding("g", "f", "FileTabCharacter").layout)
        self.assertFalse(baseline.Finding("g", "f", "E501", text="Line too long").layout)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class ProseBesideTheCode(unittest.TestCase):
    def test_agent_mirror_and_instructions_describe_phase_minus_one(self):
        for path in (KIT / "com.github.copilot" / "agents" / "zethus.agent.md", KIT / "agents" / "zethus.agent.md"):
            text = flat(path.read_text(encoding="utf-8"))
            for phrase in ("Phase -1: remediate existing issues", "baseline-gates.py survey", "untouched base",
                           "Phase -1 is a no-op", "once, at sign-off", "baseline-gates.py scope",
                           "Pre-existing gate failures", "Remediation phase `Phase -1`", "phase-minus-one.md"):
                self.assertIn(phrase, text, f"{path.name}: {phrase}")
        text = flat((KIT / "copilot-instructions.md").read_text(encoding="utf-8"))
        for phrase in ("Phase -1 remediates existing issues", "baseline-gates.py survey", "in one line",
                       "never mixed with the planned change", "asked once, at sign-off", "Phase 0 then stacks on it"):
            self.assertIn(phrase, text, phrase)

    def test_skills_carry_their_half(self):
        implement = flat((KIT / "skills" / "implement-phase" / "SKILL.md").read_text(encoding="utf-8"))
        for phrase in ("## Phase -1: remediate existing issues", "baseline-gates.py scope", "Change no behaviour",
                       "naming `phase -1`"):
            self.assertIn(phrase, implement, phrase)
        self.assertIn("baseline-gates.py scope", (KIT / "skills" / "pre-push-gates" / "SKILL.md").read_text(encoding="utf-8"))
        for skill in ("write-spec-full", "write-spec-minimum"):
            text = flat((KIT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8"))
            for phrase in ("Pre-existing gate failures", "baseline-gates.py survey", "Remediation phase `Phase -1`",
                           "start Phase -1 if the spec has one"):
                self.assertIn(phrase, text, f"{skill}: {phrase}")

    def test_the_decision_note_exists_and_is_linked(self):
        self.assertTrue((KIT / "docs" / "phase-minus-one.md").is_file())
        for doc in ("README.md", "docs/gate-remediation-in-the-plan.md", "docs/never-stop-silently.md",
                    "copilot-instructions.md"):
            self.assertIn("phase-minus-one.md", (KIT / doc).read_text(encoding="utf-8"), doc)

    def test_the_pr_template_has_a_place_for_what_was_already_red(self):
        self.assertIn("## Phase -1: what was already red", (KIT / "templates" / "pr.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
