"""CI coverage for lessons capture, Phase 3 (docs/lessons-capture-spec.md section 4.4, section 5).

Phase 3 adds context fingerprints (a context is a spec or ticket, Q5), the S7 "promote to standard?"
question (Q4), promotion as a standard to the shared tier or any store in `config.stores` (Q3), and
config-default proposals. Its exit test is `TestExitCriterion`: three ADRs with the same answer across
two specs produce exactly one question, and three in one spec produce none.

The exit test drives the real pieces end to end: Zethus's `new-adr.py` (a subprocess) records the S1
candidate with its question class, option and spec; the CLI captures it; triage asks. Everything is
offline. The only subprocesses are `new-adr.py` and local git. No lesson text here is real: every
title, spec id and option is invented for the test.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.test_mnemosyne_review_flow import GitWorld, git

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "zethus" / "scripts"

from mnemosyne import candidates as cd  # noqa: E402
from mnemosyne import cli, core, standards  # noqa: E402
from mnemosyne.config import Config  # noqa: E402

CLASS = "merge strategy"
OPTION = "merge commits"
# Three answers worded nothing alike: only the question class and chosen option tie them together.
WORDINGS = (
    ("Land every PR with a merge commit", "Use a merge commit when landing a PR so history stays whole."),
    ("History must keep each branch's commits", "Never squash on landing; the branch's own commits are the record."),
    ("Reviewers read the merge graph", "Integrate through merge commits, as the graph is what reviewers read."),
)
FAKE_SECRET = "pass" + "word=hunter2hunter2"   # built at run time: no credential-shaped literal in the file


class _Work(GitWorld):
    """A project that is also its own memory repo (a clone of a bare remote), with capture active."""

    mode = "active"
    with_remote = False     # a bare remote and a clone (promotion needs a git repo with an origin)
    pass_spec = False       # also hand the spec and an anchor to `capture`, so the lesson carries provenance

    def setUp(self):
        super().setUp()
        if self.with_remote:
            self.remote = self.memory_remote("primary")
            self.dev = self.clone(self.remote, "dev")
        else:
            self.dev = self.root / "dev"
            self.dev.mkdir()
            git(self.dev, "init", "-q")
            core.init_repo(self.dev)
        env = {"MNEMOSYNE_REPO": str(self.dev), "PYTHONPATH": str(REPO / "mnemosyne" / "src")}
        if self.mode:
            env["MNEMOSYNE_CAPTURE_MODE"] = self.mode
        patcher = patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for var in ("MNEMOSYNE_CAPTURE", "MNEMOSYNE_CONTEXT_SALT", "ZETHUS_CONFIG"):
            os.environ.pop(var, None)
        if not self.mode:
            os.environ.pop("MNEMOSYNE_CAPTURE_MODE", None)
        previous = os.getcwd()
        os.chdir(self.dev)
        self.addCleanup(os.chdir, previous)

    # -- driving the real pieces ---------------------------------------------------------------

    def cli(self, *argv, expect=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = cli.main(["--repo", str(self.dev), *argv])
        self.assertEqual(rc, expect, out.getvalue() + err.getvalue())
        return out.getvalue()

    def adr(self, title, *flags):
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / "new-adr.py"), title, "--deciders", "Alice", *flags],
            cwd=str(self.dev), capture_output=True, text=True, env=dict(os.environ),
            stdin=subprocess.DEVNULL)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return [c for c in cd.candidates(self.dev) if c["signal"] == "S1"][-1]

    def store_adr(self, n, spec, *extra):
        """Record ADR number `n` (answering CLASS with OPTION) in `spec`, then store its candidate
        as the lesson the agent would write. Returns (the capture's output, the candidate)."""
        title, lesson = WORDINGS[n % len(WORDINGS)]
        cand = self.adr(f"{title} ({spec})", "--question-class", CLASS, "--option", OPTION,
                        "--spec", spec, *extra)
        more = ["--tags", "merge"] + (["--spec", spec, "--anchors", "docs/adr/x.md:3"] if self.pass_spec else [])
        out = self.cli("capture", "--category", "decision", "--captured-by", "hook:S1",
                       "--candidate", cand["id"], "--title", title, "--lesson", lesson, *more)
        return out, cand

    def questions(self):
        plan = json.loads(self.cli("--format", "json", "candidate", "triage"))
        return [q for q in plan["questions"] if q["signal"] == "S7"], plan

    def local(self):
        return core.read_jsonl(core.local_path(self.dev))


class TestExitCriterion(_Work):
    """Spec section 5, Phase 3 exit: the same answer in three ADRs, across two specs or in one."""

    def test_three_adrs_across_two_specs_make_exactly_one_question(self):
        self.store_adr(0, "SPEC-A")
        self.store_adr(1, "SPEC-A")
        self.assertEqual(self.questions()[0], [])                  # two occurrences, one context
        out, _ = self.store_adr(2, "SPEC-B")
        self.assertIn("REINFORCED", out)
        self.assertIn("STANDARD?", out)
        qs, plan = self.questions()
        self.assertEqual(len(qs), 1)
        (lesson,) = self.local()
        self.assertEqual((lesson["id"], lesson["reinforced"]), ("L-0001", 2))
        self.assertEqual(len(lesson["contexts"]), 3)
        self.assertEqual(len({e["ctx"] for e in lesson["contexts"]}), 2)
        self.assertEqual([o["key"] for o in qs[0]["options"]], ["promote:shared", "skip", "never"])
        self.assertIn("L-0001", qs[0]["question"])
        self.assertEqual(plan["signals"].get("S7", {}).get("status", "ask"), "ask")
        # Asking again, scanning, or another occurrence never makes a second question.
        self.assertEqual(self.cli("--format", "json", "standard", "scan").strip(), "[]")
        self.store_adr(0, "SPEC-C")
        self.assertEqual(len(self.questions()[0]), 1)

    def test_three_adrs_in_one_spec_make_no_question(self):
        for n in range(3):
            self.store_adr(n, "SPEC-A")
        (lesson,) = self.local()
        self.assertEqual((lesson["reinforced"], len(lesson["contexts"])), (2, 3))
        self.assertEqual(len({e["ctx"] for e in lesson["contexts"]}), 1)
        self.assertEqual(self.questions()[0], [])
        self.assertEqual(self.cli("--format", "json", "standard", "scan").strip(), "[]")
        (row,) = json.loads(self.cli("--format", "json", "standard", "list"))["lessons"]
        self.assertEqual((row["occurrences"], row["contexts"], row["qualifies"]), (3, 1, False))
        self.assertFalse([c for c in cd.candidates(self.dev) if c["signal"] == "S7"])

    def test_a_skip_is_final(self):
        for n, spec in enumerate(("SPEC-A", "SPEC-A", "SPEC-B")):
            self.store_adr(n, spec)
        (q,) = self.questions()[0]
        self.cli("candidate", "resolve", q["id"], "skipped", "--note", "not a standard here")
        self.assertEqual(self.questions()[0], [])
        self.store_adr(1, "SPEC-D")
        self.store_adr(2, "SPEC-E")
        self.assertEqual(self.questions()[0], [])
        self.assertEqual(len([c for c in cd.candidates(self.dev) if c["signal"] == "S7"]), 1)

    def test_the_question_is_asked_from_any_branch(self):
        for n, spec in enumerate(("SPEC-A", "SPEC-A", "SPEC-B")):
            self.store_adr(n, spec)
        git(self.dev, "checkout", "-q", "-b", "feature/elsewhere")
        self.assertEqual(len(self.questions()[0]), 1)

    def test_the_window_and_the_thresholds_come_from_memory_standard(self):
        cfg_dir = self.dev / ".github"
        cfg_dir.mkdir()
        (cfg_dir / "zethus.config.json").write_text(json.dumps(
            {"memory": {"standard": {"minOccurrences": 2, "minContexts": 2}}}), encoding="utf-8")
        self.store_adr(0, "SPEC-A")
        self.assertEqual(self.questions()[0], [])
        self.store_adr(1, "SPEC-B")
        self.assertEqual(len(self.questions()[0]), 1)


class TestShadowByDefault(_Work):
    """An upgrade changes nothing by itself: without active mode capture is what it was."""

    mode = None

    def test_capture_records_no_fingerprint_and_nothing_is_asked(self):
        for n, spec in enumerate(("SPEC-A", "SPEC-B", "SPEC-C")):
            out, _ = self.store_adr(n, spec)
            self.assertNotIn("STANDARD?", out)
        for lesson in self.local():
            self.assertNotIn("contexts", lesson)
            self.assertNotIn("decision", lesson)
        self.assertEqual(self.cli("--format", "json", "standard", "scan").strip(), "[]")
        self.assertFalse([c for c in cd.candidates(self.dev) if c["signal"] == "S7"])
        self.assertEqual(cd.capture_mode({}), "shadow")

    def test_a_decision_given_on_the_command_line_is_still_honoured(self):
        self.cli("capture", "--category", "decision", "--title", "Page lists at fifty rows",
                 "--lesson", "List endpoints return fifty rows a page unless asked.",
                 "--decision-class", "page size", "--decision-option", "fifty")
        (lesson,) = self.local()
        self.assertEqual(lesson["decision"], {"class": "page size", "option": "fifty"})
        self.assertNotIn("contexts", lesson)


class TestContexts(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo = Path(self._td.name)
        (self.repo / "memory").mkdir()
        env = patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("MNEMOSYNE_CONTEXT_SALT", None)

    def test_a_spec_beats_a_ticket_beats_a_branch(self):
        self.assertEqual(standards.context_ref("SPEC-9", "feature/ABC-12-x"), ("spec", "SPEC-9"))
        self.assertEqual(standards.context_ref(None, "feature/abc-12-add-thing"), ("ticket", "ABC-12"))
        self.assertEqual(standards.context_ref(None, "feature/add-thing"), ("branch", "feature/add-thing"))
        self.assertIsNone(standards.context_ref(None, None))
        self.assertIsNone(standards.context_ref("", "(detached)"))

    def test_the_hash_is_salted_stable_and_hides_the_reference(self):
        a = standards.context_hash(self.repo, "host/org/repo", "ABC-12")
        self.assertEqual(a, standards.context_hash(self.repo, "host/org/repo", "abc-12"))
        self.assertNotEqual(a, standards.context_hash(self.repo, "host/org/repo", "ABC-13"))
        self.assertNotEqual(a, standards.context_hash(self.repo, "host/org/other", "ABC-12"))
        self.assertRegex(a, r"^[0-9a-f]{16}$")
        self.assertTrue((cd.capture_dir(self.repo) / standards.SALT_FILE).is_file())
        self.assertTrue(cd.is_self_ignored(self.repo))            # the salt can never be committed
        os.environ[standards.SALT_ENV] = "team-salt"
        b = standards.context_hash(self.repo, "host/org/repo", "ABC-12")
        self.assertNotEqual(a, b)
        with tempfile.TemporaryDirectory() as other:             # one salt, one count, any machine
            (Path(other) / "memory").mkdir()
            self.assertEqual(b, standards.context_hash(Path(other), "host/org/repo", "ABC-12"))

    def test_repo_identity_survives_a_reclone_and_a_login(self):
        for n, url in enumerate(("https://user:pw@github.com/Org/Repo.git", "git@github.com:Org/Repo.git",
                                 "https://github.com/org/repo")):
            work = self.repo / f"w{n}"
            (work / ".git").mkdir(parents=True)
            (work / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8")
            self.assertEqual(standards.repo_identity(work), "github.com/org/repo")
        bare = self.repo / "Plain"
        (bare / ".git").mkdir(parents=True)
        self.assertEqual(standards.repo_identity(bare), "plain")

    def test_the_rule_counts_only_what_is_inside_the_window(self):
        cfg = Config({})
        st = standards.settings(cfg, {})
        self.assertEqual(st, {"minOccurrences": 3, "minContexts": 2, "windowDays": 180})
        old, new = "2020-01-01", core.today()
        lesson = {"id": "L-0001", "status": "active", "contexts": [
            {"ctx": "a", "date": new}, {"ctx": "b", "date": old}, {"ctx": "c", "date": old}]}
        self.assertEqual(standards.counts(lesson, st), {"occurrences": 1, "contexts": 1})
        self.assertFalse(standards.qualifies(lesson, st))
        lesson["contexts"] = [{"ctx": "a", "date": new}, {"ctx": "a", "date": new}, {"ctx": "b", "date": new}]
        self.assertTrue(standards.qualifies(lesson, st))
        for blocker in ({"status": "retired"}, {"standard": {"since": new}},
                        {"source": {"exported_to": {"tier": "shared", "remote_id": "L-0002"}}}):
            self.assertFalse(standards.qualifies(dict(lesson, **blocker), st), blocker)

    def test_settings_read_the_memory_standard_block(self):
        st = standards.settings(Config({}), {"standard": {"minOccurrences": 5, "minContexts": 3, "windowDays": 30}})
        self.assertEqual(st, {"minOccurrences": 5, "minContexts": 3, "windowDays": 30})
        self.assertEqual(standards.settings(Config({}), {"standard": {"minOccurrences": "x"}})["minOccurrences"], 3)


class TestWhatALessonCarries(_Work):
    def test_no_spec_ticket_or_branch_name_lands_on_the_lesson(self):
        git(self.dev, "checkout", "-q", "-b", "feature/ZED-77-internal-codename")
        for n, spec in enumerate(("SPEC-A", "SPEC-A", "SPEC-B")):
            self.store_adr(n, spec)
        text = core.local_path(self.dev).read_text(encoding="utf-8")
        for name in ("SPEC-A", "SPEC-B", "ZED-77", "internal-codename"):
            self.assertNotIn(name, text)
        for entry in self.local()[0]["contexts"]:
            self.assertEqual(set(entry), {"ctx", "date", "k", "signal"})
            self.assertRegex(entry["ctx"], r"^[0-9a-f]{16}$")
            self.assertEqual(entry["signal"], "S1")

    def test_a_branch_stands_in_when_no_spec_or_ticket_is_named(self):
        git(self.dev, "checkout", "-q", "-b", "feature/plain-branch")
        cand = self.adr("Plain decision one", "--question-class", CLASS, "--option", OPTION)
        self.assertEqual(cand["context"]["ref"], "feature/plain-branch")
        git(self.dev, "checkout", "-q", "-b", "feature/ABC-5-thing")
        cand = self.adr("Plain decision two", "--question-class", CLASS, "--option", OPTION)
        self.assertEqual(cand["context"]["ref"], "ABC-5")

    def test_the_same_candidate_captured_twice_counts_once(self):
        _, cand = self.store_adr(0, "SPEC-A")
        self.cli("capture", "--category", "decision", "--captured-by", "hook:S1", "--candidate", cand["id"],
                 "--title", WORDINGS[0][0], "--lesson", WORDINGS[0][1])
        (lesson,) = self.local()
        self.assertEqual(len(lesson["contexts"]), 1)

    def test_a_decision_needs_both_halves_and_no_secret(self):
        self.cli("capture", "--category", "decision", "--title", "Half a decision", "--lesson",
                 "A question class alone is not a decision.", "--decision-class", CLASS, expect=2)
        self.cli("capture", "--category", "decision", "--title", "Secret decision", "--lesson",
                 "A credential shape must never be stored.", "--decision-class", CLASS,
                 "--decision-option", FAKE_SECRET, expect=2)
        self.assertEqual(self.local(), [])

    def test_the_new_lesson_fields_validate(self):
        for n, spec in enumerate(("SPEC-A", "SPEC-B")):
            self.store_adr(n, spec)
        self.assertIn("VALIDATE: OK", self.cli("validate"))
        bad = self.local()
        bad[0]["contexts"] = [{"nope": 1}]
        core.write_jsonl(core.local_path(self.dev), bad)
        self.assertIn("bad contexts", self.cli("validate", expect=1))


class TestZethusAdr(_Work):
    def test_the_adr_records_the_answer_and_the_candidate_points_at_it(self):
        cand = self.adr("Pin the answer", "--question-class", CLASS, "--option", OPTION, "--spec", "SPEC-A",
                        "--config-key", "branchModel.maxBehind", "--config-value", "0")
        ev = cand["evidence"]
        self.assertEqual((ev["qclass"], ev["option"], ev["config_key"], ev["config_value"]),
                         (CLASS, OPTION, "branchModel.maxBehind", "0"))
        self.assertEqual(cand["context"]["ref"], "SPEC-A")
        self.assertRegex(cand["context"]["ctx"], r"^[0-9a-f]{16}$")
        text = next((self.dev / "docs" / "adr").glob("*pin-the-answer.md")).read_text(encoding="utf-8")
        self.assertIn(f"| Question class | {CLASS} |", text)
        self.assertIn(f"| Chosen option | {OPTION} |", text)

    def test_an_adr_without_the_new_flags_is_as_it_was(self):
        cand = self.adr("An ADR with no answer recorded")
        self.assertEqual(sorted(cand["evidence"]), ["adr", "path"])
        text = next((self.dev / "docs" / "adr").glob("*no-answer-recorded.md")).read_text(encoding="utf-8")
        self.assertIn("| Question class | — |", text)

    def test_a_secret_in_the_option_is_dropped_not_recorded(self):
        cand = self.adr("A careless ADR", "--question-class", CLASS, "--option", FAKE_SECRET)
        self.assertNotIn("option", cand["evidence"])
        self.assertNotIn("qclass", cand["evidence"])

    def test_half_an_answer_is_not_recorded(self):
        cand = self.adr("A half answer", "--option", OPTION)
        self.assertEqual(sorted(cand["evidence"]), ["adr", "path"])


class _Recurring(_Work):
    """A decision lesson that has met the rule: three occurrences across two specs."""

    with_remote = True

    def setUp(self):
        super().setUp()
        for n, spec in enumerate(("SPEC-A", "SPEC-A", "SPEC-B")):
            self.store_adr(n, spec, *self.adr_flags)
        (self.q,) = self.questions()[0]

    adr_flags = ()


class TestPromoteToShared(_Recurring):
    def test_a_yes_opens_a_review_branch_with_a_standard(self):
        out = self.cli("standard", "promote", "L-0001", "--to", "shared", "--candidate", self.q["id"])
        self.assertIn("PROMOTED: L-0001", out)
        self.assertIn("STANDARD: L-0001", out)
        copy = json.loads(git(self.dev, "show", "reflexion/L-0001:memory/lessons.jsonl").splitlines()[-1])
        self.assertEqual((copy["category"], copy["memory_type"], copy["confidence"]),
                         ("convention", "procedural", "high"))
        self.assertEqual(copy["standard"]["occurrences"], 3)
        self.assertEqual(copy["standard"]["contexts"], 2)
        self.assertEqual(len(copy["contexts"]), 3)
        self.assertEqual(copy["review"]["state"], "approved")      # merging the PR is the approval
        (original,) = self.local()
        self.assertEqual((original["category"], original["confidence"]), ("decision", "medium"))
        self.assertNotIn("standard", original)
        self.assertEqual(original["source"]["exported_to"], {"tier": "shared", "remote_id": "L-0001"})
        self.assertEqual(self.questions()[0], [])                  # the candidate is resolved
        (cand,) = [c for c in cd.candidates(self.dev) if c["signal"] == "S7"]
        self.assertEqual((cand["resolution"], cand["resolved_lesson"]), ("stored", "L-0001"))

    def test_the_standard_never_lands_in_the_working_tree_of_any_tier(self):
        self.cli("standard", "promote", "L-0001")
        self.assertFalse(core.shared_path(self.dev).read_text(encoding="utf-8").strip())

    def test_a_lesson_below_the_rule_is_refused_unless_forced(self):
        self.cli("capture", "--category", "convention", "--title", "A lesson seen once", "--lesson",
                 "This lesson has one occurrence and so is no standard yet.", "--spec", "SPEC-Z")
        self.cli("standard", "promote", "L-0002", expect=2)
        self.assertIn("PROMOTED", self.cli("standard", "promote", "L-0002", "--force"))

    def test_the_second_promotion_is_refused(self):
        self.cli("standard", "promote", "L-0001")
        self.cli("standard", "promote", "L-0001", expect=2)


class TestPromoteToAStore(_Recurring):
    pass_spec = True

    def setUp(self):
        super().setUp()
        self.team_remote = self.memory_remote("team")
        self.team = self.clone(self.team_remote, "team")
        self.cfg_team = self.store_cfg("internal")

    def store_cfg(self, scope):
        return Config({**self.cfg.as_dict(), "stores": [
            {"tier": "team", "prefix": "T", "path": str(self.team), "scope": scope}]})

    def promote(self, cfg, lid="L-0001"):
        res = standards.promote(cfg, self.dev, lid, "team", {})
        return res, [json.loads(l) for l in git(self.team, "show",
                                                f"{res['branch']}:memory/lessons.jsonl").splitlines()]

    def test_a_store_in_config_stores_is_a_target(self):
        res, rows = self.promote(self.cfg_team)
        (copy,) = rows
        self.assertEqual((res["tier"], copy["id"]), ("team", "T-0001"))
        self.assertEqual((copy["category"], copy["memory_type"], copy["confidence"]),
                         ("convention", "procedural", "high"))
        self.assertTrue(copy["standard"])
        self.assertEqual(self.local()[0]["source"]["exported_to"], {"tier": "team", "remote_id": "T-0001"})

    def test_an_internal_store_keeps_provenance(self):
        _, rows = self.promote(self.store_cfg("internal"))
        self.assertEqual(rows[0]["source"]["spec_id"], "SPEC-A")
        self.assertEqual(rows[0]["source"]["anchors"], ["docs/adr/x.md:3"])

    def test_an_external_store_gets_the_context_hashes_and_no_names(self):
        _, rows = self.promote(self.store_cfg("external"))
        (copy,) = rows
        for key in ("spec_id", "anchors", "reflection_of", "exported_from"):
            self.assertNotIn(key, copy["source"])
        self.assertNotIn("SPEC-A", json.dumps(copy))
        self.assertEqual(len({e["ctx"] for e in copy["contexts"]}), 2)   # it can still count contexts
        self.assertTrue(copy["standard"])

    def test_a_scope_that_is_not_internal_or_external_is_a_config_error(self):
        from mnemosyne.config import ConfigError
        with self.assertRaises(ConfigError):
            Config({**self.cfg.as_dict(), "stores": [{"tier": "t", "prefix": "T", "path": ".", "scope": "x"}]})

    def test_offer_tiers_follow_the_federation_and_offertier(self):
        cfg = Config({**self.cfg.as_dict(), "stores": [
            {"tier": "team", "prefix": "T", "path": str(self.team)},
            {"tier": "ro", "prefix": "R", "path": str(self.team), "readonly": True},
            {"tier": "org", "prefix": "O", "path": str(self.team)}]})
        self.assertEqual(standards.offer_tiers(cfg, {}), ["shared", "team", "org"])
        self.assertEqual(standards.offer_tiers(cfg, {"offerTier": "org"}), ["org", "shared", "team"])
        self.assertEqual(standards.offer_tiers(cfg, {"offerTier": "ro"}), ["shared", "team", "org"])
        self.assertEqual(standards.offer_tiers(cfg, {"offerTier": "nowhere"}), ["shared", "team", "org"])
        labels = [o["key"] for o in standards.options({"evidence": {}}, ["org", "shared"])]
        self.assertEqual(labels, ["promote:org", "promote:shared", "skip", "never"])


class TestConfigDefaultProposal(_Recurring):
    adr_flags = ("--config-key", "branchModel.maxBehind", "--config-value", "0")

    def test_the_question_names_the_key_and_a_proposal_is_printed_never_written(self):
        self.assertIn("branchModel.maxBehind", self.q["question"])
        out = self.cli("standard", "config", "L-0001")
        self.assertIn('{"branchModel": {"maxBehind": 0}}', out)
        self.assertIn("nothing was written", out)
        promoted = self.cli("standard", "promote", "L-0001", "--candidate", self.q["id"])
        self.assertIn("CONFIG DEFAULT (proposal, nothing was written): branchModel.maxBehind = 0", promoted)
        self.assertFalse(list(self.dev.rglob("*.config.json")))
        copy = json.loads(git(self.dev, "show", "reflexion/L-0001:memory/lessons.jsonl").splitlines()[-1])
        self.assertEqual(copy["config_default"], {"key": "branchModel.maxBehind", "value": 0})

    def test_a_lesson_without_a_key_proposes_nothing(self):
        self.cli("capture", "--category", "convention", "--title", "No config attached", "--lesson",
                 "This lesson maps to no config key at all.")
        self.assertIn("proposes no config default", self.cli("standard", "config", "L-0002"))

    def test_a_key_that_is_not_a_dotted_name_is_refused(self):
        self.cli("capture", "--category", "convention", "--title", "Bad key here", "--lesson",
                 "A config key must be a dotted name.", "--config-key", "a b; rm", expect=2)


class TestQuestionRendering(_Recurring):
    def test_the_numbered_form_lists_one_option_per_tier(self):
        text = self.cli("candidate", "triage", "--numbered")
        self.assertIn("1. [S7]", text)
        self.assertIn("1.1  Promote to the project's shared tier as a standard", text)
        self.assertIn("1.3  Never ask about this kind", text)

    def test_never_mutes_every_standard_question(self):
        self.cli("candidate", "resolve", self.q["id"], "never")
        for n, spec in enumerate(("SPEC-D", "SPEC-E")):
            self.store_adr(n, spec)
        self.assertEqual(self.questions()[0], [])

    def test_doctor_lists_s7_as_asking(self):
        self.assertEqual(cd.doctor(self.dev, 0, {})["signals"]["S7"]["status"], "ask")


if __name__ == "__main__":
    unittest.main()
