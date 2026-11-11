"""Zethus rebases a stale branch itself, and never hands the rebase to the person.

Ceryce's report, 2026-11-10 (paraphrased; ``zethus/docs/base-freshness-cadence.md``, amendment of
that date): at a freshness checkpoint the agent stopped and asked the person to rebase, when it
could have brought the branch up to date itself. These tests pin that no agent file or prompt asks
the person to rebase, that the procedure (both styles, conflicts, re-running the gates, the two
stops it keeps) is in ``pre-push-gates``, that the script's STALE line says what the agent does
next, that following that line really does reach FRESH, and that the stop guard refuses a stop for
a stale base while letting a failed fetch or an undecidable conflict through.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
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
AGREEMENT = KIT / "copilot-instructions.md"
GATES = KIT / "skills" / "pre-push-gates" / "SKILL.md"
RECORD = KIT / "docs" / "base-freshness-cadence.md"
GUARD = KIT / "com.github.copilot" / "hooks" / "stop_guard.py"
SCRIPT = KIT / "scripts" / "base-freshness.py"
ANCHOR = "pre-push-gates/SKILL.md#bring-a-stale-branch-up-to-date"
AMENDMENT = "## Amendment, 2026-11-10: Zethus rebases a stale branch itself"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                     # a dataclass looks its module up while it is built
    spec.loader.exec_module(mod)
    return mod


guard = load("stop_guard_self_rebase", GUARD)
fresh = load("base_freshness_self_rebase", SCRIPT)

# Wording that hands the rebase to a person. Matched loosely, so a rewording of the old rule
# still trips it.
HANDOVER = (
    re.compile(r"\b(?:ask|tell|have|get|wait for)\s+(?:them|the person|the user|you)\b[^.|\n]{0,60}"
               r"\brebas", re.IGNORECASE),
    re.compile(r"\b(?:the person|the user|they|someone)\s+rebases?\b", re.IGNORECASE),
    re.compile(r"\|\s*A rebase, or a fetch that works\s*\|"),
)


def flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def handovers(text: str) -> list[str]:
    return [m.group(0) for rx in HANDOVER for m in rx.finditer(text)]


def stop_table(text: str) -> str:
    return text.split("You end a turn only at one of these points:", 1)[1].split("\n\n", 2)[1]


class NobodyIsAskedToRebase(unittest.TestCase):
    def test_no_agent_file_asks_the_person_to_rebase(self):
        for path in (CANONICAL, MIRROR):
            self.assertEqual(handovers(path.read_text(encoding="utf-8")), [], path)

    def test_nor_do_the_working_agreement_skills_or_readme(self):
        paths = [AGREEMENT, KIT / "README.md", *sorted((KIT / "skills").glob("*/SKILL.md"))]
        found = {str(p.relative_to(KIT)): handovers(p.read_text(encoding="utf-8")) for p in paths}
        self.assertEqual({k: v for k, v in found.items() if v}, {})

    def test_the_pattern_catches_the_old_wording(self):
        """The old rows, verbatim from before the change, so the check can't rot into a no-op."""
        for old in ("**Stop.** Tell the person how many commits behind the branch is and ask them "
                    "to rebase first.",
                    "If `base-freshness` says it is stale, the person rebases it",
                    "| `base-freshness` reports STALE, or gives no answer | A rebase, or a fetch that works |"):
            self.assertTrue(handovers(old), old)

    def test_the_stale_row_points_at_the_procedure_and_is_no_longer_a_stop(self):
        for path in (CANONICAL, MIRROR):
            text = path.read_text(encoding="utf-8")
            (row,) = [ln for ln in text.splitlines() if ln.startswith("| 1 | STALE |")]
            self.assertIn("Rebase it yourself, then carry on", row)
            self.assertIn(ANCHOR, row)
            self.assertIn("Do no stage work on a stale base", row, "a stale base is still never built on")
            self.assertNotIn("Stop", row)
            table = stop_table(text)
            self.assertNotIn("reports STALE", table)
            self.assertIn("`base-freshness` gives no answer", table, "a failed fetch is still a stop")
            self.assertIn("a rebase conflict needs a decision the spec and diff can't make", table)
            self.assertIn("rebase it yourself (`git rebase origin/<base>`)", text, "rebase style")
            self.assertIn("if it says stale, rebase it yourself first", text, "refusal table")
            self.assertIn("neither is skippable", text)

    def test_the_mirror_link_resolves_one_folder_shallower(self):
        self.assertIn(f"](../../skills/{ANCHOR})", CANONICAL.read_text(encoding="utf-8"))
        self.assertIn(f"](../skills/{ANCHOR})", MIRROR.read_text(encoding="utf-8"))


class TheProcedure(unittest.TestCase):
    def test_pre_push_gates_holds_it(self):
        text = GATES.read_text(encoding="utf-8")
        self.assertIn("## Bring a stale branch up to date", text)
        section = flat(GATES).split("## Bring a stale branch up to date", 1)[1].split(" ## ", 1)[0]
        for phrase in ("Both freshness checkpoints use this", "not the person's",
                       "git stash push --include-untracked",
                       "git rebase origin/<base>", "cut a fresh branch",
                       "git rebase --update-refs origin/<base>",
                       "Resolve conflicts yourself, keeping both sides' intent",
                       "Stop only for a conflict you can't decide", "never half-applied",
                       "git rebase --abort", "the question tool", "the hunk",
                       "re-run `python <kit root>/scripts/base-freshness.py`", "must report FRESH",
                       "not a third one", "run `run-local-gates` again",
                       "git push --force-with-lease", "never a plain `--force`",
                       "says it was rebased", "exit 3"):
            self.assertIn(phrase, section, phrase)

    def test_step_0_rebases_instead_of_stopping(self):
        step0 = flat(GATES).split("0. **Check the base is fresh:**", 1)[1].split(" 1. **", 1)[0]
        self.assertIn("bring the branch up to date **yourself**", step0)
        self.assertIn("Don't stop for it, and don't hand the rebase to the person", step0)
        self.assertIn("Exit 3", step0)
        self.assertNotIn("means stop", step0)

    def test_the_working_agreement_carries_the_short_form(self):
        text = flat(AGREEMENT)
        for phrase in ("bring the branch up to date **yourself**", "Never hand the rebase to the person",
                       "Stop only when the fetch fails", "never half-applied",
                       "A stale base is not one of those: you rebase it yourself"):
            self.assertIn(phrase, text, phrase)
        self.assertNotIn("an answer, a rebase)", text)

    def test_the_other_skills_point_at_it(self):
        for name in ("implement-phase", "zethus-pr-description"):
            text = (KIT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn(f"](../{ANCHOR})", text, name)

    def test_the_record_is_amended_and_paraphrases(self):
        text = RECORD.read_text(encoding="utf-8")
        self.assertIn(AMENDMENT, text)
        self.assertIn("2026-11-10: the agent rebases a stale branch itself", text)
        amendment = text.split(AMENDMENT, 1)[1]
        self.assertIn("Ceryce's report, paraphrased", amendment)
        self.assertNotIn("\n> ", amendment, "a public record paraphrases; no block quote")
        for phrase in ("No answer (exit 3)", "never half-applied", "neither is skippable"):
            self.assertIn(phrase, amendment)


class StaleMessage(unittest.TestCase):
    def freshness(self, style: str) -> object:
        return fresh.Freshness(style, "develop", "origin/develop", behind=2, ahead=1, max_behind=0,
                               merge_base="0" * 40, upstream=None, rewritten=None)

    def test_says_what_the_agent_does_next_in_both_styles(self):
        for style, plan in (("branch-per-change", "re-run base-freshness to confirm"),
                            ("rebase", "git push --force-with-lease and say in the PR body")):
            out = "\n".join(fresh.report(self.freshness(style), fetched=True))
            self.assertIn("STALE — 2 commit(s) behind origin/develop. Bringing the branch up to date "
                          "now, before any other work", out)
            self.assertIn(plan, out)
            self.assertIn("--update-refs", out)
            self.assertIn("then carry on", out)
            self.assertIn("never half-applied", out)
            self.assertEqual(handovers(out), [], style)
            self.assertNotIn("Rebase before doing anything else", out, "the old instruction to a human")


class FollowingTheMessageReachesFresh(unittest.TestCase):
    """A real origin: go stale, do what the STALE line says, and the check comes back FRESH."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.origin, self.seed, self.work = root / "origin.git", root / "seed", root / "work"
        self.git(root, "init", "-q", "--bare", "-b", "develop", str(self.origin))
        self.git(root, "clone", "-q", str(self.origin), str(self.seed))
        self.commit(self.seed, "a.txt", "one\ntwo\nthree\n", "init")
        self.git(self.seed, "push", "-q", "origin", "HEAD:develop")
        self.git(root, "clone", "-q", str(self.origin), str(self.work))
        self.git(self.work, "checkout", "-q", "-b", "feature/x", "origin/develop")

    def git(self, where: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(where), "-c", "user.name=t", "-c",
                               "user.email=t@example.com", "-c", "core.autocrlf=false", *args],
                              capture_output=True, text=True)

    def commit(self, where: Path, name: str, text: str, msg: str) -> None:
        (where / name).write_text(text, encoding="utf-8", newline="\n")
        self.git(where, "add", name)
        self.assertEqual(self.git(where, "commit", "-q", "-m", msg).returncode, 0)

    def check(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = fresh.main(["--repo", str(self.work)])
        return code, buf.getvalue()

    def test_stale_then_rebased_then_fresh_with_a_resolvable_conflict(self):
        self.commit(self.work, "a.txt", "one\ntwo\nthree\nmine\n", "mine: append a line")
        self.git(self.seed, "pull", "-q", "origin", "develop")
        self.commit(self.seed, "a.txt", "ONE\ntwo\nthree\ntheirs\n", "theirs: upper-case one, append")
        self.assertEqual(self.git(self.seed, "push", "-q", "origin", "HEAD:develop").returncode, 0)

        code, out = self.check()
        self.assertEqual(code, 1, out)
        self.assertIn("Bringing the branch up to date now", out)

        rebase = self.git(self.work, "rebase", "origin/develop")
        self.assertNotEqual(rebase.returncode, 0, "both sides appended: a conflict to resolve")
        # Keep both sides' intent: their upper-cased line and their line, then mine.
        (self.work / "a.txt").write_text("ONE\ntwo\nthree\ntheirs\nmine\n", encoding="utf-8",
                                         newline="\n")
        self.git(self.work, "add", "a.txt")
        env = dict(os.environ, GIT_EDITOR="true")
        cont = subprocess.run(["git", "-C", str(self.work), "-c", "user.name=t", "-c",
                               "user.email=t@example.com", "rebase", "--continue"],
                              capture_output=True, text=True, env=env)
        self.assertEqual(cont.returncode, 0, cont.stderr)

        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn("FRESH", out)


STALE_STOP = ("Stage 6 · Gates — step 0 of 4: base freshness\n\n"
              "The branch is behind.\n\n"
              "Stopped at: Stage 6 · Gates — step 0\n"
              "Next: Stage 6 · Gates — step 1, run the local gates\n"
              "Why: the branch is 3 commits behind origin/develop; please rebase it first")
FETCH_STOP = ("Stage 0 · Orient — step 1 of 3: base freshness\n\n"
              "Stopped at: Stage 0 · Orient — step 1\n"
              "Next: Stage 0 · Orient — step 2, read the config\n"
              "Why: base-freshness gave no answer: the fetch failed, so the base is unknown")
CONFLICT_STOP = ("Stage 6 · Gates — step 0 of 4: base freshness\n\n"
                 "Stopped at: Stage 6 · Gates — step 0, rebase paused at commit abc123\n"
                 "Next: Stage 6 · Gates — step 0, git rebase --continue once you rule\n"
                 "Why: a rebase conflict in src/retry.py lines 40-52 needs your decision")
DONE_STOP = ("Stage 7 · PR — step 3 of 3: PR opened\n\n"
             "Stopped at: Stage 7 · PR — step 3\n"
             "Next: nothing; a person merges\n"
             "Why: the goal is complete; the PR is open, rebased onto develop")


class StopGuard(unittest.TestCase):
    def setUp(self):
        self.sid = f"rebase{os.getpid()}-{id(self)}"
        counter = guard.refusals_file({"sessionId": self.sid})
        counter.unlink(missing_ok=True)
        self.addCleanup(counter.unlink, missing_ok=True)

    def refuse(self, reply: str) -> str:
        return guard.refuse({"sessionId": self.sid}, reply)

    def test_refuses_a_stop_for_a_stale_base_and_says_to_rebase(self):
        for why in ("the branch is 3 commits behind origin/develop; please rebase it first",
                    "waiting for you to rebase onto develop",
                    "the base is stale"):
            reply = STALE_STOP.rsplit("Why:", 1)[0] + "Why: " + why
            out = self.refuse(reply)
            self.assertTrue(out, why)
            reason = json.loads(out)["reason"]
            self.assertIn("the rebase is not the person's to do", reason)
            self.assertIn("--force-with-lease", reason)
            self.assertIn("Bring a stale branch up to date", reason)
            guard.refusals_file({"sessionId": self.sid}).unlink(missing_ok=True)

    def test_lets_the_two_remaining_stops_through(self):
        for reply in (FETCH_STOP, CONFLICT_STOP):
            self.assertEqual(self.refuse(reply), "", reply.splitlines()[-1])

    def test_a_done_stop_that_mentions_a_rebase_is_left_alone(self):
        self.assertEqual(self.refuse(DONE_STOP), "")

    def test_stale_and_rebase_alone_are_no_longer_walls(self):
        self.assertNotIn("stale", guard.WALLS)
        self.assertNotIn("rebase", guard.WALLS)
        self.assertIn("conflict", guard.WALLS)
        self.assertIn("fetch", guard.WALLS)

    def test_prompt_mode_reminds_to_rebase(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text(json.dumps({"type": "assistant.message", "data": {"content": STALE_STOP}}),
                            encoding="utf-8")
            out = json.loads(guard.remind({"transcriptPath": str(path)}))
        self.assertIn("rebase the branch yourself first", out["additionalContext"])


if __name__ == "__main__":
    unittest.main()
