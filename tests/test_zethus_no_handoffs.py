"""Zethus does the work it has the tools for, and stops for the person only at what only they can give.

Ceryce's request, 2026-11-10 (paraphrased; ``zethus/docs/do-the-work-yourself.md``): after the
self-rebase fix, find every other place the agent asks a person to do a job it should be doing
itself. These tests pin the result:

- no instruction surface (agent files, working agreement, skills, docs, README, templates, scripts,
  hooks) hands the person a job again: a scan for hand-off wording, generalised from
  ``test_zethus_self_rebase.py``'s rebase check, with an allow-list that says why each remaining hit
  is a real human gate;
- each behaviour change: a failed fetch is diagnosed before it is a stop, a MANUAL gate is run and
  judged, red CI on the agent's own PR is fixed, the duplicate-install migration is offered and run,
  a missing HLA is looked for in the repo, the CLI skills read back and follow up themselves;
- the stop guard refuses a stop that waits on the person to do work, a bare failed-fetch stop and a
  done stop over red CI, while letting the real walls through.
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
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "zethus"
SCRIPTS = KIT / "scripts"
CANONICAL = KIT / "com.github.copilot" / "agents" / "zethus.agent.md"
MIRROR = KIT / "agents" / "zethus.agent.md"
AGREEMENT = KIT / "copilot-instructions.md"
GUARD = KIT / "com.github.copilot" / "hooks" / "stop_guard.py"
SESSION_START = KIT / "com.github.copilot" / "hooks" / "session_start.py"
RECORD = KIT / "docs" / "do-the-work-yourself.md"
FETCH_ANCHOR = "pre-push-gates/SKILL.md#when-the-fetch-fails"


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod                     # a dataclass looks its module up while it is built
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(SCRIPTS))
guard = load("stop_guard_no_handoffs", GUARD)
fresh = load("base_freshness_no_handoffs", SCRIPTS / "base-freshness.py")
gates = load("run_local_gates_no_handoffs", SCRIPTS / "run-local-gates.py")
hla = load("hla_input_check_no_handoffs", SCRIPTS / "hla-input-check.py")
webhla = load("webapp_hla_input_check_no_handoffs", SCRIPTS / "webapp-hla-input-check.py")
jsp = load("jsp_servlet_reader_no_handoffs", SCRIPTS / "jsp-servlet-reader.py")
start = load("session_start_no_handoffs", SESSION_START)

# Wording that hands the person a job. Matched loosely, on whitespace-flattened text, so a
# rewording of an old hand-off still trips it.
HANDOFF = (
    re.compile(r"\b(?:ask|tell|have|get|wait for|let)\s+(?:them|the person|the user|the reviewer|a person"
               r"|a human|someone|you)\b[^.|\n]{0,60}?\b(?:to\s+)?(?:rebas\w*|re-?run|run|install\w*"
               r"|regenerat\w*|format|fix|resolv\w*|configur\w*|download\w*|migrat\w*|verify|check|retry"
               r"|paste)\b", re.I),
    re.compile(r"\b(?:so|for)\s+(?:the user|the person|the reviewer|a person|someone)\s+(?:can|to)\s+"
               r"(?:verify|follow|check|run|install|fix|re-?run|rebase)\b", re.I),
    re.compile(r"\bneeds? a person (?:reading|to read|to run|running)\b", re.I),
    re.compile(r"\bhuman-supervised\b", re.I),
    re.compile(r"\b(?:the person|the user|the reviewer|someone)\s+(?:rebases?|re-?runs?|installs|regenerates?"
               r"|fixes)\b", re.I),
    re.compile(r"\bsurface it and let a person decide\b", re.I),
    re.compile(r"\breport (?:that a \w+ is missing|the wait)\b", re.I),
    re.compile(r"\bnot a full run; say so in the PR\b"),
    re.compile(r"\bre-run with --no-fetch\b"),
    re.compile(r"no such file exists\. Stopping to ask"),
    re.compile(r"\bTell the user once\b"),
    re.compile(r"\bget it from the official\b", re.I),
)

# The hits that stay, each a real human gate or a record of the old behaviour. (path, match, why)
ALLOWED = (
    ("docs/base-freshness-cadence.md", "the person rebases", "history: the amendment's context"),
    ("docs/base-freshness-cadence.md", "the person rebase", "history: Ceryce's report, paraphrased"),
    ("docs/do-the-work-yourself.md", "ask the person to rebase", "history: the context"),
    ("docs/do-the-work-yourself.md", "so the user can verify", "history: the audit table"),
    ("docs/do-the-work-yourself.md", "so the user can follow", "history: the audit table"),
    ("docs/do-the-work-yourself.md", "needs a person reading", "history: the audit table"),
    ("docs/do-the-work-yourself.md", "human-supervised", "history: the audit table"),
    ("skills/datadog-cli/SKILL.md", "tell the user, don't retry", "a 401: a key only the person holds"),
    ("skills/datadog-cli/SKILL.md", "tell the user to check", "a possibly leaked key to rotate"),
    ("skills/jenkins-cli/SKILL.md", "tell the user, don't retry", "a 401: a token only the person holds"),
    ("skills/jenkins-cli/SKILL.md", "tell the user to check", "a possibly leaked token to rotate"),
    ("skills/story-enrich/SKILL.md", "ask the person to paste", "no Jira access: only they can reach it"),
)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def handoffs(text: str) -> list[str]:
    return [m.group(0) for rx in HANDOFF for m in rx.finditer(flat(text))]


def surfaces() -> list[Path]:
    return sorted(p for p in KIT.rglob("*") if p.is_file() and p.suffix in (".md", ".py", ".json"))


class NobodyIsHandedTheWork(unittest.TestCase):
    def test_no_instruction_surface_hands_the_person_a_job(self):
        allowed = {(path, match) for path, match, _ in ALLOWED}
        found = []
        for path in surfaces():
            rel = path.relative_to(KIT).as_posix()
            for match in handoffs(path.read_text(encoding="utf-8", errors="replace")):
                if (rel, match) not in allowed:
                    found.append(f"{rel}: {match!r}")
        self.assertEqual(found, [], "hand the job to the agent, or allow-list a real gate with why")

    def test_every_allowed_hit_still_exists(self):
        """An allow-list entry that no longer matches anything is stale: drop it."""
        for path, match, why in ALLOWED:
            self.assertIn(match, handoffs((KIT / path).read_text(encoding="utf-8")), (path, why))

    def test_the_patterns_catch_the_old_wording(self):
        """The old lines, verbatim from before the change, so the scan can't rot into a no-op."""
        for old in (
            "report back what it returned (event ID, downtime ID) so the user can verify or reverse it",
            "report back the queue item ID / build number it returned so the user can follow along.",
            "the scriptlet's exact behaviour needs a person reading the block",
            "Run `jira issue move \"<KEY>\"` interactively once (human-supervised) to see the real list",
            "Neither one merges. Surface it and let a person decide.",
            "report that a JRE is missing rather than installing one unattended.",
            "don't kill and retry immediately — report the wait rather than guessing",
            "NOT checked: ghost — not a full run; say so in the PR",
            "fix the fetch, or re-run with --no-fetch and say the result is as of the last fetch.",
            "modernization.hlaDoc points at 'x.md', but no such file exists. Stopping to ask.",
            "Tell the user once, and that this removes the copy: python install.py",
            "if not, get it from the official SonarQube Server/Cloud scanner docs",
            "Tell the person how many commits behind the branch is and ask them to rebase first.",
        ):
            self.assertTrue(handoffs(old), old)


class TheAgentFileChangesOneRow(unittest.TestCase):
    def test_the_exit_3_row_points_at_the_fetch_procedure_in_both_copies(self):
        for path, depth in ((CANONICAL, "../../skills/"), (MIRROR, "../skills/")):
            (row,) = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                      if ln.startswith("| 3 | No answer: the fetch failed |")]
            self.assertIn(f"]({depth}{FETCH_ANCHOR})", row, path)
            self.assertIn("Retry and diagnose it yourself", row)
            self.assertIn("Don't proceed as if the base were fresh.", row, "still never assumed fresh")


class TheWorkingAgreement(unittest.TestCase):
    def test_says_who_does_the_work(self):
        text = flat(AGREEMENT.read_text(encoding="utf-8"))
        for phrase in ("Work you can do with your own tools is yours, never a task handed to the person",
                       "installing a missing toolchain", "fixing a red gate or red CI on your PR",
                       "Stop for the person only at what only they can give",
                       "after doing everything up to it, and name that one thing",
                       "](docs/do-the-work-yourself.md)",
                       "Stop only when the fetch still fails after you have retried and diagnosed it"):
            self.assertIn(phrase, text, phrase)


class TheFailedFetch(unittest.TestCase):
    def test_pre_push_gates_holds_the_procedure(self):
        text = flat((KIT / "skills" / "pre-push-gates" / "SKILL.md").read_text(encoding="utf-8"))
        section = text.split("## When the fetch fails", 1)[1].split(" ## ", 1)[0]
        for phrase in ("Retry once", "git remote -v", "git ls-remote --heads <remote>",
                       "Re-run `base-freshness` after the fix", "Stop only for what this machine can't give you",
                       "name exactly that one thing", "Say what you tried",
                       "don't use `--no-fetch` as a way round"):
            self.assertIn(phrase, section, phrase)
        step0 = text.split("0. **Check the base is fresh:**", 1)[1].split(" 1. **", 1)[0]
        self.assertIn("retry and diagnose it yourself", step0)
        self.assertNotIn("That one is a stop, because no rebase can fix it", step0)

    def test_the_no_answer_line_says_what_the_agent_does_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = lambda *a, cwd=root: subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
            run("init", "-q", "-b", "develop", "work")
            work = root / "work"
            run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--allow-empty",
                "-m", "init", cwd=work)
            run("remote", "add", "origin", str(root / "gone.git"), cwd=work)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = fresh.main(["--repo", str(work)])
        out = buf.getvalue()
        self.assertEqual(code, 3, out)
        for phrase in ("NO ANSWER", "Retrying and diagnosing it now", "git remote -v",
                       "git ls-remote --heads origin", "Stop only for what this machine can't supply",
                       "name that one thing", "--no-fetch is not a way round"):
            self.assertIn(phrase, out, phrase)
        self.assertEqual(handoffs(out), [])


class GatesThatDidNotRun(unittest.TestCase):
    def run_gates(self, config: dict) -> tuple[int, str, Path]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        (repo / ".git").mkdir()
        (repo / ".github").mkdir()
        (repo / ".github" / "zethus.config.json").write_text(json.dumps(config), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = gates.main(["--repo", str(repo)])
        return code, buf.getvalue(), repo

    def test_a_manual_gate_is_run_and_its_output_shown_for_the_agent_to_judge(self):
        marker = "Path('ran.txt').write_text('x'); print('3 TODOs found')"
        code, out, repo = self.run_gates({"gates": {"test": [sys.executable, "-c", "pass"],
                                                    "mandatedChecks": [
            {"name": "no-todo", "command": [sys.executable, "-c", f"from pathlib import Path; {marker}"],
             "expect": "0 hits"}]}})
        self.assertEqual(code, 3, out)
        self.assertTrue((repo / "ran.txt").is_file(), "the MANUAL gate's command really ran")
        self.assertIn("| no-todo | MANUAL |", out)
        self.assertIn("ran, exit 0; judge it against expect: 0 hits", out)
        self.assertIn("--- no-todo", out)
        self.assertIn("3 TODOs found", out, "its output is printed for the agent to judge")
        self.assertIn("judge its output below against its expect", out)
        self.assertIn("in the PR's Evidence", out)
        self.assertNotIn("say so in the PR", out)

    def test_a_skipped_gate_says_to_install_the_toolchain(self):
        code, out, _ = self.run_gates({"gates": {"steps": [
            {"name": "ghost", "command": "zethus-no-such-tool-xyz --check"}]}})
        self.assertEqual(code, 3, out)
        self.assertIn("For each SKIP, install the missing toolchain", out)
        self.assertIn("Only a gate this machine really can't run goes under What was not checked", out)
        self.assertEqual(handoffs(out), [])

    def test_the_skill_says_the_same(self):
        text = flat((KIT / "skills" / "pre-push-gates" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("A `SKIP` gate: install the missing toolchain yourself", text)
        self.assertIn("judge that output against the gate's `expect` yourself", text)
        self.assertIn("Configure `gates.steps` yourself, starting from the CI workflow's steps", text)


class RedCiIsTheAgentsToFix(unittest.TestCase):
    def test_the_pr_skill_reads_ci_and_fixes_a_red_check(self):
        text = flat((KIT / "skills" / "zethus-pr-description" / "SKILL.md").read_text(encoding="utf-8"))
        section = text.split("## Step 4: read CI, and fix a red check", 1)[1].split(" ## ", 1)[0]
        for phrase in ("fixing it is your job, not the reviewer's", "gh pr checks <number>",
                       "gh run view <run-id> --log-failed", "reproduce it locally", "re-run `run-local-gates`",
                       "add the missing gate to `gates.steps`", "fresh-eyes-investigation",
                       "Only the person decides", "say in the final stop that CI wasn't read"):
            self.assertIn(phrase, section, phrase)
        self.assertIn("If it has none, read CI ([step 4](#step-4-read-ci-and-fix-a-red-check))", text)

    def test_pre_push_gates_no_longer_hands_red_ci_over(self):
        text = flat((KIT / "skills" / "pre-push-gates" / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("Red CI on your own PR is yours to fix", text)
        self.assertIn("What a person decides is only whether to merge, wait or waive", text)


class TheDuplicateInstall(unittest.TestCase):
    def test_the_hook_has_the_agent_offer_and_run_the_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".copilot" / "instructions").mkdir(parents=True)
            (home / ".copilot" / "instructions" / "zethus.instructions.md").write_text("x", encoding="utf-8")
            with mock.patch.object(Path, "home", return_value=home):
                text = start.context({"cwd": str(home)})
        for phrase in ("offer to remove the copy yourself", "with the question tool",
                       "'Remove the copy (Recommended)' runs", "--user --migrate-to-plugin",
                       "'Keep both' changes nothing", "only a picked yes runs it", "on yes, run it"):
            self.assertIn(phrase, text, phrase)
        self.assertEqual(handoffs(text), [])


class TheHlaIsLookedForFirst(unittest.TestCase):
    def repo(self, files: dict[str, str]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        repo = Path(tmp.name)
        subprocess.run(["git", "init", "-q", str(repo)], capture_output=True)
        for name, text in files.items():
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(text, encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", name], capture_output=True)
        return repo

    def test_unconfigured_lists_the_candidate_docs_in_the_repo(self):
        repo = self.repo({"docs/target-architecture.md": "# High-Level Architecture\n",
                          "README.md": "# Unrelated\n"})
        for check in (hla.check, lambda r, c, e: (lambda code, lines: (code, " ".join(lines)))(*webhla.check(r, c, e))):
            code, message = check(repo, {}, None)
            self.assertEqual(code, 1)
            self.assertIn("no HLA document configured", message)
            self.assertIn("The repo has HLA-looking docs: docs/target-architecture.md", message)
            self.assertIn("set modernization.hlaDoc to it (or pass --hla) and re-run", message)
            self.assertNotIn("README.md", message)

    def test_a_moved_hla_is_looked_for_and_none_found_means_ask(self):
        repo = self.repo({"README.md": "# Unrelated\n"})
        code, message = hla.check(repo, {"modernization": {"hlaDoc": "docs/hla.md"}}, None)
        self.assertEqual(code, 1)
        self.assertIn("no such file exists; it may have moved", message)
        self.assertIn("No tracked doc looks like an HLA", message)
        self.assertIn("ask the person where it is, with the question tool", message)
        self.assertEqual(handoffs(message), [])

    def test_a_missing_answer_is_asked_then_written_in_by_the_agent(self):
        repo = self.repo({"hla.md": "# HLA\nprose only\n"})
        _, message = hla.check(repo, {"modernization": {"hlaDoc": "hla.md"}}, None)
        self.assertIn("The disposition is the person's decision", message)
        self.assertIn("write the line into the HLA yourself and re-run", message)
        _, lines = webhla.check(repo, {"modernization": {"hlaDoc": "hla.md"}}, None)
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertIn("write the line into the HLA yourself and re-run", line)

    def test_the_skills_say_the_lookup_is_the_agents(self):
        for name in ("dialect-oracle-plsql", "webapp-strangler-planner"):
            text = flat((KIT / "skills" / name / "SKILL.md").read_text(encoding="utf-8"))
            self.assertIn("from the candidates the message lists", text, name)
            self.assertNotIn("Exit 1 means **stop and ask", text, name)


class TheToolSkillsFollowUpThemselves(unittest.TestCase):
    PINS = {
        "jira-cli": ("rest/api/2/issue/<KEY>/transitions", "offer it once with the question tool",
                     "on a picked yes run the install yourself",
                     "Rule out the wrong `JIRA_AUTH_TYPE` yourself first",
                     "Check the project key (`jira project list`)"),
        "sonarqube-cli": ("look for it yourself, Maven's `sonar:sonar` goal",
                          "Verify it yourself, then state what changed",
                          "poll `api/ce/component?component=<key>`",
                          "offer to run `sonar-scanner` yourself"),
        "datadog-cli": ("read it back yourself (`pup downtime list`",),
        "jenkins-cli": ("follow it yourself, read-only, until it finishes",
                        "use the REST equivalent below for the task",
                        "Work out the exact build number yourself",
                        "<JENKINS_URL>/jnlpJars/jenkins-cli.jar"),
        "batch-type-cron-scheduler-wrappers": ("Test the first yourself before asking",
                                               "your recommended order"),
        "story-enrich": ("look in the repo first: a draft under `stories.dir`",),
        "webapp-target-plain-jsp-servlets": ("read the block yourself",),
    }

    def test_each_skill_does_its_own_follow_up(self):
        for name, phrases in self.PINS.items():
            text = flat((KIT / "skills" / name / "SKILL.md").read_text(encoding="utf-8"))
            for phrase in phrases:
                self.assertIn(phrase, text, f"{name}: {phrase}")

    def test_the_jsp_reader_points_at_reading_the_block(self):
        rules = jsp.read_jsp("<% if (x) { out.print(1); } %>\n", "a.jsp")
        text = " ".join(r.why for r in rules)
        self.assertIn("read the block itself (recover-business-rules)", text)
        self.assertEqual(handoffs(text), [])


STOP = "Stage {stage} · {name} — step 1 of 2: {step}\n\nStopped at: Stage {stage} · {name} — step 1\nNext: {next}\nWhy: {why}"


def reply(why: str, stage: int = 6, extra: str = "") -> str:
    body = STOP.format(stage=stage, name="Gates", step="local gates", next="Stage 7 · PR", why=why)
    return body.replace("\n\nStopped at:", f"\n\n{extra}\n\nStopped at:") if extra else body


class StopGuard(unittest.TestCase):
    def setUp(self):
        self.sid = f"handoffs{os.getpid()}-{id(self)}"
        counter = guard.refusals_file({"sessionId": self.sid})
        counter.unlink(missing_ok=True)
        self.addCleanup(counter.unlink, missing_ok=True)

    def refuse(self, text: str) -> str:
        guard.refusals_file({"sessionId": self.sid}).unlink(missing_ok=True)
        return guard.refuse({"sessionId": self.sid}, text)

    def test_refuses_a_stop_that_waits_on_the_person_to_do_work(self):
        for why in ("waiting on you to run npm install, then I'll re-run the gates",
                    "waiting for you to install the JDK",
                    "please re-run the build on your machine",
                    "the person needs to regenerate the lockfile",
                    "over to you to fix the lint findings"):
            out = self.refuse(reply(why))
            self.assertTrue(out, why)
            reason = json.loads(out)["reason"]
            self.assertIn("hands the person a job you can do with your own tools", reason)
            self.assertIn("name that one thing", reason)

    def test_lets_a_hand_off_through_when_only_the_person_can_give_it(self):
        for why in ("waiting on you to sign in to the VPN; the build host is unreachable from here",
                    "waiting for you to run the deploy approval in the change board",
                    "waiting for your sign-off on the spec",
                    "a decision for you: keep or replace the shim",
                    "waiting on you to add the token to JIRA_API_TOKEN; it's yours to create"):
            self.assertEqual(self.refuse(reply(why)), "", why)

    def test_refuses_a_bare_failed_fetch_and_lets_one_with_its_cause_through(self):
        out = self.refuse(reply("base-freshness gave no answer: the fetch failed", stage=0))
        self.assertIn("a failed fetch is yours to diagnose", json.loads(out)["reason"])
        for why in ("the fetch failed twice with 403: the remote rejects the token",
                    "could not fetch: the host is unreachable without the VPN"):
            self.assertEqual(self.refuse(reply(why, stage=0)), "", why)

    def test_refuses_a_done_stop_over_red_ci(self):
        text = reply("the goal is complete; no further phase", stage=7,
                     extra="PR #12 is open. CI is red on the lint job.")
        out = self.refuse(text)
        self.assertIn("the change isn't done while CI is red", json.loads(out)["reason"])
        for extra in ("PR #12 is open. CI is green.", "CI was red on lint; fixed and pushed, now green."):
            self.assertEqual(self.refuse(reply("the goal is complete; no further phase", stage=7,
                                               extra=extra)), "", extra)

    def test_waiting_on_you_is_no_longer_a_wall_by_itself(self):
        self.assertFalse(guard.hands_off_work(reply("waiting on your answer to the open question")))
        self.assertTrue(guard.hands_off_work(reply("waiting on you to run the formatter")))

    def test_prompt_mode_reminds_to_do_the_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text(json.dumps({"type": "assistant.message",
                                        "data": {"content": reply("waiting on you to run npm install")}}),
                            encoding="utf-8")
            out = json.loads(guard.remind({"transcriptPath": str(path)}))
        self.assertIn("your last turn stopped for a job that was yours", out["additionalContext"])


class TheRecord(unittest.TestCase):
    def test_it_paraphrases_and_names_the_one_agent_file_row(self):
        text = RECORD.read_text(encoding="utf-8")
        self.assertIn("Ceryce's follow-up, paraphrased", text)
        self.assertNotIn("\n> ", text, "a public record paraphrases; no block quote")
        self.assertIn("the agent file changes one row, the exit-3 row", text)
        for heading in ("## Decision", "## Context", "## Options considered", "## Consequences"):
            self.assertIn(heading, text)

    def test_the_guard_docstring_and_never_stop_silently_point_at_it(self):
        self.assertIn("docs/do-the-work-yourself.md", GUARD.read_text(encoding="utf-8"))
        self.assertIn("](do-the-work-yourself.md)",
                      (KIT / "docs" / "never-stop-silently.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
