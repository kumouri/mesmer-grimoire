"""``pr-later`` style: the next phase starts with no PR open, and Zethus opens none until asked.

Ceryce's ruling, 2026-11-19 (paraphrased; ``zethus/docs/phase-advance-without-pr.md``): on a busy,
closely watched repo the team may not want a PR open yet, but still needs several phases done on
the branch. Zethus blocked the next phase unless the previous one was in an open PR or merged, and
the workaround was a draft PR. These tests pin the third ``branchModel.style``: the script accepts
it and says what to do when it is stale, the default stays ``branch-per-change``, every doc that
says how a phase advances names the committed-and-green gate, nothing opens a PR (or a draft) in
this style until the person says so, the status words never claim a review that isn't happening,
the agent mirror carries all of it, and the stop guard lets the style's done stop through.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "zethus"
CANONICAL = KIT / "com.github.copilot" / "agents" / "zethus.agent.md"
MIRROR = KIT / "agents" / "zethus.agent.md"
AGREEMENT = KIT / "copilot-instructions.md"
IMPLEMENT = KIT / "skills" / "implement-phase" / "SKILL.md"
PR_SKILL = KIT / "skills" / "zethus-pr-description" / "SKILL.md"
GATES = KIT / "skills" / "pre-push-gates" / "SKILL.md"
DOCS_RULE = KIT / "com.github.copilot" / "rules" / "zethus-docs.instructions.md"
RECORD = KIT / "docs" / "phase-advance-without-pr.md"
EARLIER = KIT / "docs" / "phase-advance-on-push.md"
README = KIT / "README.md"
GUARD = KIT / "com.github.copilot" / "hooks" / "stop_guard.py"
SCRIPT = KIT / "scripts" / "base-freshness.py"
EXAMPLE = KIT / "zethus.config.example.json"
PR_ANCHOR = "zethus-pr-description/SKILL.md#in-pr-later-style-no-pr-until-the-person-asks"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                     # a dataclass looks its module up while it is built
    spec.loader.exec_module(mod)
    return mod


fresh = load("base_freshness_pr_later", SCRIPT)
guard = load("stop_guard_pr_later", GUARD)


def flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


class Selectable(unittest.TestCase):
    """Chosen the way the other styles are, and off unless chosen."""

    def test_the_script_accepts_the_style(self):
        self.assertIn("pr-later", fresh.STYLES)
        self.assertEqual(fresh.branch_model({"branchModel": {"style": "pr-later"}}), ("pr-later", 0))

    def test_the_default_is_unchanged(self):
        self.assertEqual(fresh.DEFAULT_STYLE, "branch-per-change")
        self.assertEqual(fresh.branch_model({}), ("branch-per-change", 0))
        example = json.loads(EXAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(example["branchModel"]["style"], "branch-per-change",
                         "the shipped example keeps today's behaviour")

    def test_an_unknown_style_is_still_a_usage_error(self):
        with self.assertRaises(fresh.UsageError) as ctx:
            fresh.branch_model({"branchModel": {"style": "pr-never"}})
        self.assertIn("pr-later", str(ctx.exception), "the error lists the new style")


class StaleMessage(unittest.TestCase):
    def freshness(self, rewritten: bool) -> object:
        return fresh.Freshness("pr-later", "develop", "origin/develop", behind=2, ahead=1,
                               max_behind=0, merge_base="0" * 40,
                               upstream="origin/feature/x" if rewritten else None,
                               rewritten=rewritten or None)

    def test_says_to_rebase_the_working_branch_and_open_no_pr(self):
        out = "\n".join(fresh.report(self.freshness(False), fetched=True))
        self.assertIn("style pr-later", out)
        self.assertIn("STALE — 2 commit(s) behind origin/develop. Bringing the branch up to date now",
                      out)
        self.assertIn("git rebase origin/develop on the working branch", out)
        self.assertIn("note the rebase in the spec's As built list, and open no PR for it", out)
        self.assertNotIn("say in the PR", out, "there is no PR to say it in")

    def test_a_rewritten_upstream_is_noted_in_the_spec_not_a_pr(self):
        out = "\n".join(fresh.report(self.freshness(True), fetched=True))
        self.assertIn("say in the spec's As built list (no PR is open) that it was rebased", out)

    def test_the_other_styles_still_name_the_pr(self):
        f = fresh.Freshness("rebase", "develop", "origin/develop", behind=0, ahead=1, max_behind=0,
                            merge_base="0" * 40, upstream="origin/x", rewritten=True)
        self.assertIn("say in the PR that it was rebased",
                      "\n".join(fresh.report(f, fetched=True)))


class AdvanceGate(unittest.TestCase):
    """Committed with green gates is enough; no PR, no merge."""

    def test_implement_phase_preconditions(self):
        text = IMPLEMENT.read_text(encoding="utf-8")
        pre = re.sub(r"\s+", " ", text.split("## Preconditions", 1)[1].split("\n## ", 1)[0])
        self.assertIn("If `branchModel.style` is `pr-later`, no PR is needed either", pre)
        self.assertIn("**committed on the working branch with every local gate green**", pre)
        self.assertIn("docs/phase-advance-without-pr.md", pre)
        self.assertIn("pushed to its PR**. Its PR does not have to be merged", pre,
                      "the push-gate wording for the other styles stays")

    def test_the_agent_and_its_mirror_carry_the_style(self):
        for path in (CANONICAL, MIRROR):
            text = flat(path)
            model = text.split("## Branch model", 1)[1].split("**Stuck branch.**", 1)[0]
            with self.subTest(path=path.name, where=path.parent.name):
                self.assertIn("**`pr-later`**", model)
                self.assertIn("**committed with every local gate green**", model)
                self.assertIn("open no PR, not even a draft, until the person says to", model)
                self.assertIn("phase-advance-without-pr.md", model)
                self.assertIn("in-pr-later-style-no-pr-until-the-person-asks", model)
                self.assertIn("**no PR opened** until the person says to", text, "stage 7")

    def test_the_working_agreement(self):
        text = flat(AGREEMENT)
        self.assertIn("If `branchModel.style` is `pr-later`, the next phase starts once the last is "
                      "committed with every local gate green, with no PR", text)
        self.assertIn("In `pr-later` style, open no PR, not even a draft, until the person says to",
                      text)
        self.assertIn("pushed to its PR, not\n  once it merges",
                      AGREEMENT.read_text(encoding="utf-8"), "the default rule stays")


class NoPrUntilAsked(unittest.TestCase):
    """Pushing is a backup; a PR, or a draft as a workaround, waits for the person."""

    def test_the_pr_skill_opens_none(self):
        text = flat(PR_SKILL)
        section = text.split("## In `pr-later` style: no PR until the person asks", 1)[1]
        section = section.split("## Step 4", 1)[0]
        for phrase in ("opens **no PR**, and no draft PR as a stand-in",
                       "**Push the working branch** as a backup",
                       "**Write the body anyway, into the spec, not GitHub.**",
                       "Opening it is the person's call",
                       "**When the person says to open it**",
                       "**one** PR against `<base>` that covers every phase committed so far",
                       "Mark those phases `in review (PR #n)`"):
            self.assertIn(phrase, section)

    def test_the_pre_push_gates_point_there(self):
        text = flat(GATES)
        self.assertIn("In `pr-later` style: commit and push the branch, open no PR", text)
        self.assertIn("| `pr-later` | `git rebase origin/<base>` on the working branch.", text)
        self.assertIn("in-pr-later-style-no-pr-until-the-person-asks", text)

    def test_the_agent_links_the_procedure(self):
        self.assertIn(PR_ANCHOR, CANONICAL.read_text(encoding="utf-8"))

    def test_the_goal_complete_stop_waits_on_the_person(self):
        text = flat(CANONICAL)
        self.assertIn("| `pr-later`: the goal is complete, the last phase committed and green, and "
                      "no PR | The person's word to open the PR |", text)


class StatusWords(unittest.TestCase):
    """A phase is never in review or merged without a PR."""

    def test_every_status_doc_names_the_no_pr_words(self):
        for path in (IMPLEMENT, DOCS_RULE, KIT / "templates" / "spec-full.md",
                     KIT / "skills" / "write-spec-full" / "SKILL.md", RECORD):
            text = flat(path)
            with self.subTest(doc=path.name):
                self.assertIn("PARTIAL(on branch: ", text)
                self.assertIn("in review (PR #n)" if path in (IMPLEMENT, RECORD) else "in review",
                              text)
        for path in (IMPLEMENT, DOCS_RULE, KIT / "templates" / "spec-full.md", RECORD):
            text = flat(path)
            with self.subTest(doc=path.name, words="phase"):
                self.assertTrue("on branch (<short sha>)" in text or "on branch (<sha>)" in text)
                self.assertTrue("committed (<short sha>)" in text or "committed (<sha>)" in text)
                self.assertIn("never `in review`", text)

    def test_the_gate_check_reads_the_status_as_partial(self):
        rulings = load("gate_rulings_pr_later", KIT / "scripts" / "_gate_rulings.py")
        self.assertEqual(
            rulings.status_of("**Status:** PARTIAL(on branch: phases 0–1; committed: phase 2)"),
            "PARTIAL")


class Record(unittest.TestCase):
    """The decision record exists, extends the earlier one, and paraphrases."""

    def test_the_record(self):
        text = RECORD.read_text(encoding="utf-8")
        self.assertIn("| Date | 2026-11-19 |", text)
        self.assertIn("| Extends | [The next phase starts on push, not on merge](phase-advance-on-push.md)",
                      text)
        self.assertIn("Ceryce's ruling, paraphrased", text)
        self.assertNotIn("\n> ", text, "a public record paraphrases; no block quote")
        for heading in ("### When to use it", "### Status words in this style",
                        "### When the PR is eventually opened", "## Options considered"):
            self.assertIn(heading, text)
        self.assertIn('{ "branchModel": { "style": "pr-later" } }', text)

    def test_the_readme_routes_to_it(self):
        text = README.read_text(encoding="utf-8")
        self.assertIn("docs/phase-advance-without-pr.md", text)
        self.assertIn("| | `branch-per-change` (default) | `rebase` | `pr-later` |", text)
        self.assertIn("No style waits for a merge to start the next phase.", text)
        self.assertTrue(EARLIER.exists())


class StopGuardLetsTheDoneStopThrough(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sid = f"prl{os.getpid()}-{id(self)}"
        counter = guard.refusals_file({"sessionId": self.sid})
        counter.unlink(missing_ok=True)
        self.addCleanup(counter.unlink, missing_ok=True)

    def event(self, reply: str) -> dict:
        path = Path(self.tmp.name) / "transcript.jsonl"
        rows = [{"type": "user.message", "data": {"content": "go"}},
                {"type": "assistant.message", "data": {"content": reply}}]
        path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        return {"sessionId": self.sid, "transcriptPath": str(path)}

    def test_the_pr_later_done_stop_is_a_real_stop(self):
        reply = ("Stage 7 · PR — Phase 2: branch pushed, no PR (pr-later)\n\n"
                 "Stopped at: Stage 7 · PR — Phase 2 is on branch at abc1234; no PR opened\n"
                 "Next: open one PR for phases 0–2 when you say so\n"
                 "Why: the goal is complete; opening the PR is your decision (pr-later style)")
        self.assertEqual(guard.refuse(self.event(reply), reply), "")

    def test_a_committed_phase_is_still_not_a_stop(self):
        reply = ("Stage 3 · Implement — Phase 1\n\nStopped at: Phase 1\nNext: Phase 2\n"
                 "Why: phase 1 is committed and green on the branch")
        self.assertTrue(guard.refuse(self.event(reply), reply),
                        "pr-later removes the PR gate, not the rule that progress isn't a stop")


if __name__ == "__main__":
    unittest.main()
