"""Local gates bind every push, and a plan that defers one says so (``zethus/docs/gate-remediation-in-the-plan.md``).

Ceryce's report, 2026-11-04 (paraphrased): a plan put SonarQube remediation after phase 0, SonarQube
is a local gate, so phase 0 couldn't push, and the agent stopped to ask leave to move the fix. These
tests pin the three enforcement points (the spec check, the gate verdict, the stop hook) and the
prose that sits beside them.
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
GATES = SCRIPTS / "run-local-gates.py"
CHECK = SCRIPTS / "gate-remediation-check.py"
GUARD = KIT / "com.github.copilot" / "hooks" / "stop_guard.py"

sys.path.insert(0, str(SCRIPTS))
import _gate_rulings as gr  # noqa: E402


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = load("stop_guard_gr", GUARD)
check = load("gate_remediation_check", CHECK)


def spec_text(status: str = "SIGNED-OFF", section: str | None = None, phases: str = "| 0 | Add the test | None | x |") -> str:
    body = f"# S\n\n**Status:** {status} · **Owner:** o\n\n## Phases\n\n| Phase | What | Behaviour change | Verified by |\n|---|---|---|---|\n{phases}\n\n"
    if section is not None:
        body += f"## Gate remediation\n\n{section}\n\n"
    return body + "## Test plan\n\nt\n"


def table(gate: str = "sonarqube", ruling: str = "push-red", approved: str = "yes — Ceryce, 2026-11-05") -> str:
    return (f"| Gate | Remediation phase | Ruling | Approved |\n|---|---|---|---|\n"
            f"| {gate} | Phase 2 | {ruling} | {approved} |")


NONE = "None — no phase remediates anything a local gate checks."
SONAR_PHASE = "| 2 | Remediate the SonarQube findings | None | x |"


class SpecCheck(unittest.TestCase):
    def problems(self, text: str, names=None) -> list[str]:
        return check.check_spec(text, names)

    def test_none_is_a_complete_answer_and_asks_nothing_new(self):
        self.assertEqual(self.problems(spec_text(section=NONE)), [])

    def test_a_spec_without_the_section_fails(self):
        self.assertTrue(any("no `## Gate remediation`" in p for p in self.problems(spec_text())))

    def test_none_beside_a_remediation_phase_fails(self):
        out = self.problems(spec_text(section=NONE, phases=SONAR_PHASE))
        self.assertTrue(any("says None" in p for p in out), out)

    def test_a_table_beside_a_remediation_phase_is_fine(self):
        self.assertEqual(self.problems(spec_text(section=table(), phases=SONAR_PHASE)), [])

    def test_pending_is_fine_in_a_draft_and_fails_once_signed_off(self):
        pending = table(approved="PENDING")
        self.assertEqual(self.problems(spec_text("DRAFT", pending, SONAR_PHASE)), [])
        out = self.problems(spec_text("SIGNED-OFF", pending, SONAR_PHASE))
        self.assertTrue(any("not approved" in p for p in out), out)

    def test_an_unreadable_ruling_and_a_bare_other_fail(self):
        self.assertTrue(any("not one of" in p for p in self.problems(spec_text(section=table(ruling="later")))))
        self.assertTrue(any("must name the equivalent" in p
                            for p in self.problems(spec_text(section=table(ruling="other")))))
        self.assertEqual(self.problems(spec_text(section=table(ruling="other: split the finding list"))), [])

    def test_a_gate_the_repo_does_not_have_fails(self):
        out = self.problems(spec_text(section=table(gate="sonar")), names={"sonarqube", "unittest"})
        self.assertTrue(any("not one of this repo's gates" in p for p in out), out)

    def test_both_templates_carry_the_section_and_fail_until_filled_in(self):
        for name in ("spec-minimum.md", "spec-full.md"):
            text = (KIT / "templates" / name).read_text(encoding="utf-8").replace("{{status}}", "DRAFT")
            self.assertIn("## Gate remediation", text, name)
            for ruling in gr.RULINGS:
                self.assertIn(ruling, text, f"{name}: {ruling}")
            self.assertEqual(len(self.problems(text)), 1, f"{name}: unedited, the placeholder must not pass")
            filled = re.sub(r"\| Gate \|.*?\| PENDING \|", NONE, text, flags=re.S)
            self.assertEqual(self.problems(filled), [], name)

    def test_the_cli_exits_1_on_a_problem_and_0_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            bad, good = root / "bad.md", root / "good.md"
            bad.write_text(spec_text(), encoding="utf-8")
            good.write_text(spec_text(section=NONE), encoding="utf-8")
            run = lambda f: subprocess.run([sys.executable, str(CHECK), "--repo", str(root), str(f)],
                                           capture_output=True, text=True)
            self.assertEqual(run(bad).returncode, 1)
            self.assertEqual(run(good).returncode, 0)


class GateVerdict(unittest.TestCase):
    """A red SonarQube-shaped gate, with and without a recorded ruling, through the real script."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / ".github").mkdir()
        self.set_gates(red=("sonarqube",))

    def set_gates(self, red=()):
        fail = [sys.executable, "-c", "import sys; sys.exit(1)"]
        ok = [sys.executable, "-c", "pass"]
        steps = [{"name": "unittest", "command": ok}] + [{"name": n, "command": fail} for n in red]
        (self.root / ".github" / "zethus.config.json").write_text(
            json.dumps({"gates": {"steps": steps}}), encoding="utf-8")

    def spec(self, text: str, name: str = "change.md"):
        d = self.root / "docs" / "specs"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text, encoding="utf-8")

    def run_gates(self):
        r = subprocess.run([sys.executable, str(GATES), "--repo", str(self.root)],
                           capture_output=True, text=True)
        return r.returncode, r.stdout

    def test_red_with_no_ruling_is_exit_1_and_says_to_fix_it_in_this_phase(self):
        self.spec(spec_text(section=table(ruling="limited-phase-0"), phases=SONAR_PHASE))
        code, out = self.run_gates()
        self.assertEqual(code, 1)
        self.assertIn("RED — fix before pushing: sonarqube", out)
        self.assertIn("in the phase being pushed", out)
        self.assertIn("pulled forward", out)
        self.assertIn("don't stop to ask", out)

    def test_an_approved_push_red_ruling_is_exit_4_naming_the_spec(self):
        self.spec(spec_text(section=table(), phases=SONAR_PHASE))
        code, out = self.run_gates()
        self.assertEqual(code, 4, out)
        self.assertIn("GREEN except gate(s) the approved plan lets stay red: sonarqube", out)
        self.assertIn("docs/specs/change.md", out)
        self.assertIn("red allowed by the plan", out)

    def test_the_waiver_does_not_cover_another_red_gate(self):
        self.set_gates(red=("sonarqube", "lint"))
        self.spec(spec_text(section=table(), phases=SONAR_PHASE))
        code, out = self.run_gates()
        self.assertEqual(code, 1)
        self.assertIn("RED — fix before pushing: lint", out)

    def test_pending_draft_and_non_waiving_rulings_waive_nothing(self):
        for status, ruling, approved in (("SIGNED-OFF", "push-red", "PENDING"),
                                         ("DRAFT", "push-red", "yes — someone"),
                                         ("SIGNED-OFF", "limited-phase-0", "yes — someone"),
                                         ("SIGNED-OFF", "reorder", "yes — someone"),
                                         ("SIGNED-OFF", "other: x", "yes — someone"),
                                         ("BUILT", "push-red", "yes — someone")):
            with self.subTest(status=status, ruling=ruling, approved=approved):
                self.spec(spec_text(status, table(ruling=ruling, approved=approved), SONAR_PHASE))
                self.assertEqual(self.run_gates()[0], 1)

    def test_a_partly_built_spec_still_waives(self):
        self.spec(spec_text("PARTIAL(merged: phases 0–1; in review: phase 2)", table(), SONAR_PHASE))
        self.assertEqual(self.run_gates()[0], 4)

    def test_green_stays_exit_0(self):
        self.set_gates(red=())
        self.assertEqual(self.run_gates()[0], 0)

    def test_the_waiver_is_per_gate_name(self):
        self.spec(spec_text(section=table(gate="lint"), phases=SONAR_PHASE))
        self.assertEqual(self.run_gates()[0], 1)


PROGRESS_ASK = """Stage 3 · Implement — Phase 0, step 4 of 4: local gates

Phase 0 is committed, but the SonarQube gate fails. The plan schedules the remediation of those
findings in Phase 2, so phase 0 cannot push.

Stopped at: Stage 6 · Gates
Next: Stage 7 · PR
Why: waiting for your approval to move the SonarQube remediation into phase 0
"""
PLANNING_ASK = """Stage 2 · Spec — step 4 of 4: waiting for sign-off

Gate left for a later phase: SonarQube. Phase 2 remediates its findings. Do you approve moving the
remediation into phase 0, pushing with the gate red, or reordering the phases?

Stopped at: Stage 2 · Spec
Next: Stage 3 · Implement — Phase 0
Why: waiting for your sign-off and your decision on the SonarQube gate
"""
OTHER_STOP = """Stage 4 · Tests — Phase 1

Stopped at: Stage 4
Next: Stage 5
Why: waiting for your decision on which retry policy to use
"""


class StopHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sid = f"gr{os.getpid()}-{id(self)}"
        counter = guard.refusals_file({"sessionId": self.sid})
        counter.unlink(missing_ok=True)
        self.addCleanup(counter.unlink, missing_ok=True)

    def event(self, reply: str) -> dict:
        path = Path(self.tmp.name) / "t.jsonl"
        path.write_text(json.dumps({"type": "assistant.message", "data": {"content": reply}}),
                        encoding="utf-8")
        return {"sessionId": self.sid, "transcriptPath": str(path)}

    def test_a_stop_asking_to_move_the_gate_fix_is_refused_though_it_cites_a_wall(self):
        self.assertTrue(guard.is_real_stop(PROGRESS_ASK), "the Why names an approval, so only this rule can catch it")
        out = json.loads(guard.refuse(self.event(PROGRESS_ASK), PROGRESS_ASK))
        self.assertEqual(out["decision"], "block")
        self.assertIn("fix the failing gate now", out["reason"])
        self.assertIn("pulled forward", out["reason"])

    def test_the_planning_stop_is_untouched(self):
        self.assertFalse(guard.asks_to_defer_gate_fix(PLANNING_ASK))
        self.assertEqual(guard.refuse(self.event(PLANNING_ASK), PLANNING_ASK), "")

    def test_an_unrelated_decision_stop_is_untouched(self):
        self.assertFalse(guard.asks_to_defer_gate_fix(OTHER_STOP))
        self.assertEqual(guard.refuse(self.event(OTHER_STOP), OTHER_STOP), "")

    def test_it_cannot_trap_a_session(self):
        ev = self.event(PROGRESS_ASK)
        got = [bool(guard.refuse(ev, PROGRESS_ASK)) for _ in range(guard.MAX_REFUSALS + 1)]
        self.assertEqual(got, [True] * guard.MAX_REFUSALS + [False])

    def test_a_question_turn_is_not_a_zethus_stage_and_is_ignored(self):
        reply = PROGRESS_ASK.replace("Stage 3 · Implement", "Answering your question")
        self.assertFalse(guard.asks_to_defer_gate_fix(reply))

    def test_prompt_mode_tells_the_next_turn_to_fix_the_gate(self):
        out = json.loads(guard.remind(self.event(PROGRESS_ASK)))
        self.assertIn("fix the failing gate in the phase being pushed", out["additionalContext"])

    def test_the_hook_is_registered_in_both_layouts(self):
        for root in (KIT / "com.github.copilot", KIT):
            text = (root / "hooks" / "hooks.json").read_text(encoding="utf-8")
            self.assertIn("stop_guard.py", text)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class ProseBesideTheCode(unittest.TestCase):
    def test_agent_mirror_and_instructions_carry_the_rule(self):
        for path in (KIT / "com.github.copilot" / "agents" / "zethus.agent.md", KIT / "agents" / "zethus.agent.md"):
            text = flat(path.read_text(encoding="utf-8"))
            for phrase in ("Local gates are green before every push", "Gate left for a later phase",
                           "Limited remediation in phase 0", "Push with the gate red", "A different phase order",
                           "without stopping to ask", "pulled forward", "Gate remediation"):
                self.assertIn(phrase, text, f"{path.name}: {phrase}")
        text = flat((KIT / "copilot-instructions.md").read_text(encoding="utf-8"))
        for phrase in ("Local gates are green before every push", "SonarQube included",
                       "without stopping to ask", "pulled forward", "Gate remediation"):
            self.assertIn(phrase, text)

    def test_skills_carry_their_half(self):
        implement = flat((KIT / "skills" / "implement-phase" / "SKILL.md").read_text(encoding="utf-8"))
        for phrase in ("Every local gate is green before this phase pushes", "without stopping to ask",
                       "as small as turns the gate green", "pulled forward", "push-red"):
            self.assertIn(phrase, implement)
        pre_push = flat((KIT / "skills" / "pre-push-gates" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("GREEN except gate(s) the approved plan lets stay red", pre_push)
        for skill in ("write-spec-full", "write-spec-minimum"):
            text = flat((KIT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8"))
            for phrase in ("Gate left for a later phase", "gate-remediation-check.py", "yes — who, date"):
                self.assertIn(phrase, text, f"{skill}: {phrase}")

    def test_the_decision_note_exists_and_is_linked(self):
        note = KIT / "docs" / "gate-remediation-in-the-plan.md"
        self.assertTrue(note.is_file())
        for doc in ("README.md", "docs/never-stop-silently.md"):
            self.assertIn("gate-remediation-in-the-plan.md", (KIT / doc).read_text(encoding="utf-8"), doc)

    def test_the_pr_template_has_a_place_to_say_a_gate_was_pulled_forward(self):
        self.assertIn("## Gates pulled forward", (KIT / "templates" / "pr.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
