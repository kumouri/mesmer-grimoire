"""CI coverage for lessons capture, Phase 2 (docs/lessons-capture-spec.md §5, §5.2).

Phase 2 does three things, and each is tested here without touching a real host:

* it tightens detection (S4/S5 need an imperative shape and never fire inside a brief; S6 skips
  watchdog kills, navigation, heredoc and quoting retries and unchanged re-runs);
* it turns the rest of the signals into ask outcomes, batched, but only for the signals that have
  earned a question (the others stay in shadow and say so); and
* it prints Copilot's session-start and prompt context in the shape Copilot injects, and takes
  Amphion's and Zethus's watched paths from the config keys those kits already have.

Event payloads use the field names observed on real installs (spec §4.7.1). Copilot behaviour on a
real VS Code or cloud-agent host cannot be driven from here and is not claimed.
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

from tests.test_mnemosyne_capture import MNEMOSYNE_SRC, _Project, cd, cli, core  # noqa: F401

from mnemosyne import detect  # noqa: E402


def signals_of(prompt, find):
    return [phrase.casefold() for phrase, _s, _e in find(prompt)]


class S4Detection(unittest.TestCase):
    def test_bare_always_and_never_in_prose_no_longer_fire(self):
        for prose in ("The build never finished, so I re-ran it.",
                      "It always rounds up here, which is why the totals look off.",
                      "We were never told which branch to use.",
                      "Scope records calls and targets, never accuracy.",
                      "I remember when this test was flaky.",
                      "Never again, I said to myself."):
            self.assertEqual(detect.s4_matches(prose), [], prose)

    def test_an_imperative_directive_fires(self):
        self.assertEqual(signals_of("Always run the linter before you push.", detect.s4_matches), ["always"])
        self.assertEqual(signals_of("Never squash merge a PR in this repo.", detect.s4_matches), ["never"])
        self.assertEqual(signals_of("Please remember to page at 50.", detect.s4_matches), ["remember to"])
        self.assertEqual(signals_of("From now on, use tabs.", detect.s4_matches), ["from now on"])
        self.assertEqual(signals_of("Ok, and you should always write the test first.", detect.s4_matches),
                         ["always"])

    def test_a_directive_buried_in_another_sentence_does_not(self):
        self.assertEqual(detect.s4_matches("The agent file says the reviewer should never approve a draft."), [])


class S5Detection(unittest.TestCase):
    def test_mid_sentence_dont_and_bare_instead_no_longer_fire(self):
        for prose in ("The two modes don't have to match.",
                      "Why would you say that? I don't think it was needed.",
                      "A note is sent, instead of counting as an answer.",
                      "Don't you think we should wait?",
                      "Don't worry about the formatting."):
            self.assertEqual(detect.s5_matches(prose), [], prose)

    def test_corrections_fire(self):
        self.assertEqual(signals_of("No, use merge commits.", detect.s5_matches), ["no,"])
        self.assertEqual(signals_of("Don't squash that PR.", detect.s5_matches), ["don't squash"])
        self.assertEqual(signals_of("Ok, do not rebase it.", detect.s5_matches), ["do not rebase"])
        self.assertEqual(signals_of("That's wrong, the base is develop.", detect.s5_matches), ["that's wrong"])
        self.assertEqual(signals_of("Use the staging key instead.", detect.s5_matches), ["instead"])

    def test_curly_apostrophes_count(self):
        self.assertEqual(signals_of("Don’t squash that PR.", detect.s5_matches), ["don’t squash"])


class BriefGate(_Project):
    def test_brief_shapes(self):
        self.assertFalse(detect.looks_like_brief("Always run the linter before you push."))
        self.assertTrue(detect.looks_like_brief("Never merge. " + "x" * detect.BRIEF_CHARS))
        self.assertTrue(detect.looks_like_brief("Never merge.\n```\ncode\n```"))
        self.assertTrue(detect.looks_like_brief("<note>Do not merge.</note>"))
        listed = "Rules\n" + "\n".join(f"- item {n}" for n in range(detect.BRIEF_LINES))
        self.assertTrue(detect.looks_like_brief(listed))
        self.assertFalse(detect.looks_like_brief("- one\n- two\nNever merge."))

    def test_a_brief_records_nothing_and_says_so(self):
        brief = "Never merge a PR. Do not message anyone. " + "context " * 200
        rec = self.capture("prompt", self.ev(prompt=brief))
        self.assertEqual((rec["decision"], rec["candidates"]), ("brief", []))
        self.assertEqual(cd.candidates(self.root), [])

    def test_a_brief_does_not_stop_recall_and_a_secret_is_still_dropped_first(self):
        shape = "gh" + "p_" + "A1b2C3d4" * 5
        rec = self.capture("prompt", self.ev(prompt="Never share this: " + shape + " " + "x " * 700))
        self.assertEqual(rec["decision"], "dropped")

    def test_the_same_directive_in_a_short_message_is_a_candidate(self):
        self.capture("prompt", self.ev(prompt="Never merge a PR without CI."))
        self.assertEqual(self.signals(), ["S4"])
        self.assertEqual(cd.candidates(self.root)[0]["det"], cd.DETECTOR)


class S6Exclusions(_Project):
    def fail_then_pass(self, first, second, error="Exit code 1", session="s1"):
        self.capture("post-tool", self.ev(session_id=session, hook_event_name="PostToolUseFailure",
                                          tool_name="Bash", tool_input={"command": first}, error=error))
        self.capture("post-tool", self.ev(session_id=session, hook_event_name="PostToolUse", tool_name="Bash",
                                          tool_input={"command": second}, tool_response={"stdout": ""}))
        return [r["decision"] for r in cd.decisions(self.root) if r["mode"] == "post-tool"]

    def test_a_real_fix_still_records(self):
        self.fail_then_pass("git switch feat", "git switch -c feat")
        self.assertEqual(self.signals(), ["S6"])

    def test_watchdog_kills_never_pair_up(self):
        for code in (124, 130, 137, 143):
            self.fail_then_pass("npm test", "npm test --ci", error=f"Exit code {code}", session=f"w{code}")
        self.assertEqual(self.signals(), [])
        self.assertIn("excluded-failure", [r["decision"] for r in cd.decisions(self.root)])

    def test_navigation_and_plain_reads_are_not_lessons(self):
        for n, (first, second) in enumerate((("cd build", "cd build/out"), ("ls dist", "ls docs"),
                                             ("cat notes.txt", "cat docs/notes.txt"), ("sleep 5", "sleep 6"))):
            self.fail_then_pass(first, second, session=f"n{n}")
        self.assertEqual(self.signals(), [])

    def test_heredoc_and_quoting_retries_are_not_lessons(self):
        self.fail_then_pass("python - <<'EOF'\nprint(1\nEOF", "python - <<'EOF'\nprint(1)\nEOF", session="h")
        self.fail_then_pass("git commit -m \"it's\"", "git commit -m 'it is'",
                            error="Exit code 2\nunexpected EOF while looking for matching `\"'", session="q")
        self.assertEqual(self.signals(), [])

    def test_an_unchanged_rerun_is_a_flake_not_a_lesson(self):
        decisions = self.fail_then_pass("gh pr checks", "gh pr checks")
        self.assertEqual(self.signals(), [])
        self.assertEqual(decisions[-1], "excluded-retry")

    def test_the_failure_text_is_never_stored(self):
        self.fail_then_pass("git switch feat", "git switch -c feat", error="Exit code 128\nsecret-looking detail")
        self.assertNotIn("secret-looking", json.dumps(cd.candidates(self.root)))
        self.assertNotIn("secret-looking", (cd.capture_dir(self.root) / cd.STATE).read_text(encoding="utf-8"))


class SignalStatus(_Project):
    def test_defaults(self):
        st = cd.signal_status(self.root, {})
        self.assertEqual({s: v["status"] for s, v in st.items() if s in ("S1", "S2", "S4", "S5", "S6", "S8",
                                                                         "S9-S11", "S12")},
                         {"S1": "auto", "S2": "auto", "S4": "shadow", "S5": "shadow", "S6": "shadow",
                          "S8": "ask", "S9-S11": "ask", "S12": "shadow"})
        self.assertIn("none labelled", st["S5"]["why"])

    def test_a_project_can_opt_a_signal_in_by_name_or_id(self):
        st = cd.signal_status(self.root, {"ask": {"signals": ["correction", "S6"]}})
        self.assertEqual((st["S5"]["status"], st["S6"]["status"], st["S4"]["status"]), ("ask", "ask", "shadow"))

    def label(self, sig, verdicts, det=None):
        for v in verdicts:
            c = cd.add_candidate(self.root, sig, context={"repo": self.root.name}, evidence={"match": "x"})
            cd.label(self.root, c["id"], v)

    def test_a_signal_earns_its_questions_by_measured_precision(self):
        self.label("S5", ["lesson"] * 5 + ["noise"] * 4)               # 9 labelled: not enough yet
        self.assertEqual(cd.signal_status(self.root, {})["S5"]["status"], "shadow")
        self.label("S5", ["lesson"])                                    # 10 labelled, 6 of 10
        self.assertEqual(cd.signal_status(self.root, {})["S5"]["status"], "ask")
        self.label("S6", ["lesson"] * 3 + ["noise"] * 7)                # 10 labelled but 0.3
        self.assertEqual(cd.signal_status(self.root, {})["S6"]["status"], "shadow")

    def test_labels_on_older_detectors_do_not_count(self):
        self.label("S4", ["lesson"] * 12)
        rows = []
        for line in (cd.capture_dir(self.root) / cd.CANDIDATES).read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            row.pop("det", None)                                         # a Phase 0 candidate
            rows.append(json.dumps(row))
        (cd.capture_dir(self.root) / cd.CANDIDATES).write_text("\n".join(rows) + "\n", encoding="utf-8")
        self.assertEqual(cd.signal_status(self.root, {})["S4"]["status"], "shadow")

    def test_shadow_candidates_are_recorded_but_never_triaged(self):
        self.capture("prompt", self.ev(prompt="Never merge a PR without CI."))
        self.assertEqual(self.signals(), ["S4"])
        plan = cd.triage(self.root, {}, project=self.root.name, branch="feat/demo")
        self.assertEqual((plan["untriaged"], plan["suppressed"]), (0, {"shadow": 1}))
        self.assertEqual(cd.untriaged(self.root, raw=True)[0]["signal"], "S4")

    def test_old_detector_candidates_are_never_asked_even_when_opted_in(self):
        c = cd.add_candidate(self.root, "S5", context={"repo": self.root.name, "branch": "feat/demo"},
                             evidence={"match": "Do not"})
        text = (cd.capture_dir(self.root) / cd.CANDIDATES).read_text(encoding="utf-8")
        (cd.capture_dir(self.root) / cd.CANDIDATES).write_text(text.replace(',"det":2', ''), encoding="utf-8")
        plan = cd.triage(self.root, {"ask": {"signals": ["S5"]}}, project=self.root.name)
        self.assertEqual((plan["untriaged"], plan["suppressed"]), (0, {"stale": 1}))
        self.assertTrue(c["id"])


class AskTriage(_Project):
    def fresh_eyes(self, session="s1"):
        self.capture("post-tool", self.ev(session_id=session, tool_name="Skill",
                                          tool_input={"skill": "fresh-eyes-investigation"}, tool_response={}))

    def plan(self, cfg=None):
        return cd.triage(self.root, cfg or {}, project=self.root.name, branch="feat/demo")

    def test_ask_items_become_one_batched_question_set_with_the_four_options(self):
        self.fresh_eyes()
        self.capture("post-tool", self.ev(tool_name="Write", tool_input={"file_path": "docs/friction-log.md"},
                                          tool_response={}))
        plan = self.plan()
        self.assertEqual([q["signal"] for q in plan["questions"]], ["S8", "S9-S11"])
        for q in plan["questions"]:
            self.assertEqual([o["key"] for o in q["options"]], ["save", "edit", "skip", "never"])
        self.assertEqual(plan["questions"][1]["category"], "process")      # a friction entry is a process lesson
        self.assertEqual(plan["questions"][1]["kind"], "S9-S11:friction")

    def test_numbered_rendering_for_a_host_with_no_question_tool(self):
        self.fresh_eyes()
        text = cd.render_questions(self.plan())
        self.assertIn("1. [S8]", text)
        self.assertIn("   1.4  Never ask about this kind", text)
        self.assertEqual(cd.render_questions({"questions": []}), "")

    def test_questions_carry_pointers_never_tool_output(self):
        self.capture("post-tool", self.ev(hook_event_name="PostToolUseFailure", tool_name="Bash",
                                          tool_input={"command": "git switch feat"},
                                          error="Exit code 128\nfatal: leaked-output"))
        self.capture("post-tool", self.ev(hook_event_name="PostToolUse", tool_name="Bash",
                                          tool_input={"command": "git switch -c feat"}, tool_response={}))
        plan = self.plan({"ask": {"signals": ["S6"]}})
        text = json.dumps(plan)
        self.assertIn("git switch", text)
        self.assertNotIn("leaked-output", text)

    def test_skip_is_a_negative_fingerprint(self):
        path = "docs/specs/a.md"
        for session in ("one", "two"):
            self.capture("post-tool", self.ev(session_id=session, tool_name="Write",
                                              tool_input={"file_path": path}, tool_response={}))
            if session == "one":
                (q,) = self.plan()["questions"]
                cd.resolve(self.root, q["id"], "skipped")
        self.assertEqual(len(cd.candidates(self.root)), 2)           # both were recorded
        plan = self.plan()
        self.assertEqual((plan["untriaged"], plan["suppressed"]), (0, {"seen": 1}))

    def test_a_stored_answer_is_not_asked_again_for_the_same_path(self):
        for session in ("one", "two"):
            self.capture("post-tool", self.ev(session_id=session, tool_name="Edit",
                                              tool_input={"file_path": "docs/specs/b.md"}, tool_response={}))
            if session == "one":
                cd.resolve(self.root, self.plan()["questions"][0]["id"], "stored", lesson="L-0001")
        self.assertEqual(self.plan()["untriaged"], 0)

    def test_never_mutes_the_kind_for_good(self):
        self.capture("post-tool", self.ev(tool_name="Write", tool_input={"file_path": "docs/friction-log.md"},
                                          tool_response={}))
        cd.resolve(self.root, self.plan()["questions"][0]["id"], "never")
        self.assertIn("S9-S11:friction", cd.muted_kinds(self.root))
        self.capture("post-tool", self.ev(session_id="later", tool_name="Write",
                                          tool_input={"file_path": "docs/friction-log.md"}, tool_response={}))
        self.capture("post-tool", self.ev(session_id="later", tool_name="Write",
                                          tool_input={"file_path": "docs/specs/c.md"}, tool_response={}))
        plan = self.plan()
        self.assertEqual([q["kind"] for q in plan["questions"]], ["S9-S11:spec"])   # other kinds still ask
        self.assertEqual(plan["suppressed"], {"muted": 1})

    def test_the_cli_resolves_never_and_prints_numbered_questions(self):
        self.fresh_eyes()
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = cli.main(["--repo", str(self.root), "candidate", "triage", "--project", self.root.name,
                           "--numbered"])
        self.assertEqual(rc, 0)
        self.assertIn("Lessons triage: 1 question(s)", out.getvalue())
        cid = cd.candidates(self.root)[0]["id"]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--repo", str(self.root), "candidate", "resolve", cid, "never"]), 0)
        self.assertEqual(self.plan()["untriaged"], 0)
        self.assertIn("S8", cd.muted_kinds(self.root))

    def test_an_adr_the_script_already_raised_is_not_asked_twice(self):
        cd.record_adr(self.root, "2026-11-24-x", "docs/adr/2026-11-24-x.md", env=self.env)
        self.capture("post-tool", self.ev(tool_name="Edit", tool_input={"file_path": "docs/adr/2026-11-24-x.md"},
                                          tool_response={}))
        plan = self.plan()
        self.assertEqual([it["signal"] for it in plan["items"]], ["S1"])
        self.assertEqual(plan["suppressed"], {"covered": 1})

    def test_the_engine_still_refuses_a_security_hook_capture(self):
        # The Q2 exclusions hold for every ask: a `security` lesson is asked, never captured by a hook.
        self.fresh_eyes()
        cid = cd.candidates(self.root)[0]["id"]
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = cli.main(["--repo", str(self.root), "capture", "--category", "security", "--title", "t",
                           "--lesson", "l", "--captured-by", "hook:S8", "--candidate", cid])
        self.assertEqual(rc, 2)
        self.assertIn("never auto-stored", err.getvalue())
        self.assertEqual(self.plan()["untriaged"], 1)           # still pending: nothing was resolved


class WatchedPaths(_Project):
    def write(self, path, session="s1", tool="Write", n=0):
        self.capture("post-tool", self.ev(session_id=session, tool_name=tool,
                                          tool_input={"file_path": path, "n": n}, tool_response={}))

    def test_a_bare_repo_watches_the_conventional_places(self):
        entries = dict((k, p) for p, k in cd.watch_entries(self.root, {}))
        self.assertEqual(entries, {"adr": "docs/adr/", "spec": "docs/specs/", "friction": "docs/friction-log.md"})

    def test_amphion_keys_become_watched_paths(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "amphion.config.json").write_text(json.dumps({
            "ledger": {"path": "docs/PHASE-PROGRESS.md"},
            "frictionLog": {"sink": "markdown", "markdown": {"path": "notes/friction.md"}}}), encoding="utf-8")
        entries = dict((k, p) for p, k in cd.watch_entries(self.root, {}))
        self.assertEqual((entries["friction"], entries["ledger"]), ("notes/friction.md", "docs/PHASE-PROGRESS.md"))
        self.assertEqual(entries["spec"], "docs/specs/")                    # untouched kinds keep their default
        self.write("notes/friction.md")
        self.write("docs/PHASE-PROGRESS.md")
        self.write("docs/friction-log.md")                                  # no longer the friction log
        self.assertEqual([(c["evidence"]["kind"], c["evidence"]["sub"]) for c in cd.candidates(self.root)],
                         [("friction", "S10"), ("ledger", "S11")])

    def test_a_notion_friction_sink_is_not_a_file_to_watch(self):
        (self.root / ".claude").mkdir()
        (self.root / ".claude" / "amphion.config.json").write_text(json.dumps({
            "frictionLog": {"sink": "notion", "markdown": {"path": "notes/friction.md"}}}), encoding="utf-8")
        self.assertNotIn("notes/friction.md", [p for p, _k in cd.watch_entries(self.root, {})])

    def test_zethus_spec_and_adr_dirs_are_watched(self):
        (self.root / ".github").mkdir()
        (self.root / ".github" / "zethus.config.json").write_text(json.dumps({
            "spec": {"dir": "design/specs"}, "adr": {"dir": "design/decisions"}}), encoding="utf-8")
        entries = dict((k, p) for p, k in cd.watch_entries(self.root, {}))
        self.assertEqual((entries["spec"], entries["adr"]), ("design/specs/", "design/decisions/"))

    def test_an_explicit_watch_list_is_the_whole_list_and_may_name_kinds(self):
        entries = cd.watch_entries(self.root, {"watch": ["notes/decisions.md", {"path": "wiki", "kind": "spec"}]})
        self.assertEqual(entries, [("notes/decisions.md", "path"), ("wiki/", "spec")])

    def test_a_path_is_one_candidate_a_session(self):
        for n in range(3):                                   # three real edits (the guard keys on content)
            self.write("docs/specs/a.md", n=n)
        self.write("docs/specs/a.md", session="other")
        self.assertEqual(self.signals(), ["S9-S11", "S9-S11"])
        self.assertEqual([r["decision"] for r in cd.decisions(self.root)],
                         ["candidate", "watched-repeat", "watched-repeat", "candidate"])


class RecalledLessons(_Project):
    def test_digest_ids_are_read_from_the_digest_lines(self):
        digest = ("RECALL: 2 reflexion lesson(s) applied.\n- L-0001 [mistake/plan/local] A title\n    APPLY: x\n"
                  "- T-0003 [convention/team] Another\n  (+1 more)\n")
        self.assertEqual(cd.digest_ids(digest), ["L-0001", "T-0003"])

    def test_a_correction_after_a_recall_raises_s12_with_the_ids(self):
        cd.note_recall(self.root, "s1", ["L-0001", "L-0002"])
        self.capture("prompt", self.ev(prompt="No, use merge commits."))
        self.assertEqual(self.signals(), ["S5", "S12"])
        s12 = cd.candidates(self.root)[1]
        self.assertEqual(s12["evidence"]["lessons"], ["L-0001", "L-0002"])
        self.assertEqual(s12["evidence"]["correction"], cd.candidates(self.root)[0]["id"])
        self.assertIn("L-0001", cd.ask_question(s12))

    def test_no_recall_in_the_session_no_s12(self):
        cd.note_recall(self.root, "someone-else", ["L-0001"])
        self.capture("prompt", self.ev(prompt="No, use merge commits."))
        self.assertEqual(self.signals(), ["S5"])

    def test_s12_asks_only_when_it_has_earned_it_and_its_capture_is_not_a_hook_capture(self):
        cd.note_recall(self.root, "s1", ["L-0001"])
        self.capture("prompt", self.ev(prompt="No, use merge commits."))
        plan = cd.triage(self.root, {"ask": {"signals": ["S5", "S12"]}}, project=self.root.name, branch="feat/demo")
        s12 = [q for q in plan["questions"] if q["signal"] == "S12"]
        self.assertEqual(len(s12), 1)
        self.assertTrue(s12[0]["supersede"])                                # offer --supersede
        self.assertEqual(cd.triage(self.root, {}, project=self.root.name)["untriaged"], 0)


class CopilotBridge(_Project):
    """The Copilot-format registrations: session-start and prompt context as JSON additionalContext
    (observed on the CLI; unverified on VS Code and the cloud agent), the agentStop block, and one run
    per event with both the repo's and the user's file present."""

    def setUp(self):
        super().setUp()
        self.env = {k: v for k, v in self.env.items() if k != "CLAUDECODE"}
        self.env["COPILOT_CLI"] = "1"
        (self.root / ".github").mkdir()
        self.cfg = self.root / ".github" / "zethus.config.json"

    def active(self):
        self.cfg.write_text(json.dumps({"memory": {"mode": "active"}}), encoding="utf-8")

    def cev(self, **kw):
        return dict({"sessionId": "c1", "cwd": str(self.root)}, **kw)

    def pending(self):
        cd.record_adr(self.root, "2026-11-24-outbox", env=self.env)

    def test_session_start_prints_json_additional_context_in_active_mode(self):
        self.active()
        self.pending()
        out = self.hook("session-start", self.cev(source="new"))
        doc = json.loads(out)
        self.assertEqual(list(doc), ["additionalContext"])
        self.assertIn("await triage", doc["additionalContext"])

    def test_claude_code_still_gets_plain_stdout(self):
        self.active()
        self.pending()
        env = dict(self.env, CLAUDECODE="1")
        env.pop("COPILOT_CLI")
        out = self.hook("session-start", self.ev(hook_event_name="SessionStart", source="startup"), env=env)
        self.assertTrue(out.startswith("[Mnemosyne]"), out)

    def test_shadow_mode_prints_nothing_on_any_host(self):
        self.pending()
        self.capture("post-tool", self.cev(toolName="skill", toolArgs={"skill": "fresh-eyes-investigation"}))
        for mode, ev in (("session-start", self.cev(source="new")), ("stop", self.cev(stop_hook_active=False)),
                         ("pre-compact", self.cev()), ("post-tool", self.cev(toolName="create", toolArgs={}))):
            self.assertEqual(self.hook(mode, ev), "", mode)
        self.assertEqual(self.hook("stop", self.cev(stop_hook_active=False)), "")

    def test_an_unrecognised_host_gets_plain_stdout_not_json(self):
        self.active()
        self.pending()
        env = {k: v for k, v in self.env.items() if k != "COPILOT_CLI"}
        out = self.hook("session-start", {"cwd": str(self.root), "session_id": "x"}, env=env)
        self.assertTrue(out.startswith("[Mnemosyne]"), out)

    def test_agent_stop_blocks_once_with_the_json_decision(self):
        self.active()
        self.pending()
        out = json.loads(self.hook("stop", self.cev(stop_hook_active=False)))
        self.assertEqual(out["decision"], "block")
        self.assertIn("one batched question set", out["reason"])
        self.assertEqual(self.hook("stop", self.cev(stop_hook_active=True)), "")

    def test_prompt_recall_keeps_plain_stdout_until_active_then_goes_json(self):
        core.init_repo(self.root)
        core.capture(cli.load_config(None, self.root), self.root, {
            "category": "convention", "title": "Page lists at fifty", "lesson": "Page list endpoints at 50.",
            "tags": "pagination", "reflection_of": "list endpoints returned everything", "stage": "plan"})
        prompt = self.cev(prompt="how should I page the list endpoint with pagination?")
        out = self.hook("prompt", prompt)
        self.assertIn("[Mnemosyne reflexion memory]", out)
        self.assertFalse(out.lstrip().startswith("{"))                        # shadow: as it always was
        self.active()
        later = self.cev(prompt="how should I page the list endpoint with pagination?", sessionId="c2")
        doc = json.loads(self.hook("prompt", later))
        self.assertIn("Page lists at fifty", doc["additionalContext"])

    def test_both_hook_files_print_one_digest(self):
        self.active()
        self.pending()
        import shutil
        from tests.test_mnemosyne_capture import HOOK
        copies = []
        for folder in (self.root / ".github" / "hooks", self.root / "home" / ".copilot" / "hooks"):
            folder.mkdir(parents=True)
            copies.append(shutil.copy(HOOK, folder))
        import subprocess
        outs = []
        for script in copies:
            proc = subprocess.run([sys.executable, script, "session-start"], input=json.dumps(self.cev(source="new")),
                                  capture_output=True, text=True, env=self.env, cwd=str(self.root))
            self.assertEqual((proc.returncode, proc.stderr), (0, ""))
            outs.append(proc.stdout)
        self.assertEqual([bool(o) for o in outs], [True, False])               # the second run prints nothing
        self.assertIn("duplicate", [r["decision"] for r in cd.decisions(self.root)])

    def test_postTool_events_from_copilot_raise_the_same_signals(self):
        self.capture("post-tool", self.cev(toolName="create", toolArgs={"path": "docs/specs/x.md"}))
        self.assertEqual(self.signals(), ["S9-S11"])


class UpgradeChangesNothing(_Project):
    """An upgrade must not change a session by itself: with no memory.mode set every mode is silent,
    whatever is in the spool, and the stop hook never blocks."""

    def test_default_mode_is_silent_and_never_blocks(self):
        cd.record_adr(self.root, "2026-11-24-outbox", env=self.env)
        self.capture("post-tool", self.ev(tool_name="Skill", tool_input={"skill": "fresh-eyes-investigation"},
                                          tool_response={}))
        for mode in ("session-start", "stop", "pre-compact", "post-tool", "prompt"):
            self.assertEqual(self.hook(mode, self.ev(prompt="Never merge a PR without CI.", stop_hook_active=False)),
                             "", mode)
        self.assertNotIn("block", [r["decision"] for r in cd.decisions(self.root)])

    def test_nothing_is_ever_stored_by_a_hook(self):
        before = self.lesson_files()
        for mode in ("session-start", "stop", "pre-compact", "prompt"):
            self.hook(mode, self.ev(prompt="Never merge a PR without CI.", stop_hook_active=False))
        self.assertEqual(self.lesson_files(), before)


class Doctor(_Project):
    def test_doctor_reports_each_signal_status_and_the_checkpoint_count(self):
        cd.record_adr(self.root, "2026-11-24-x", env=self.env)
        self.capture("prompt", self.ev(prompt="Never merge a PR without CI."))
        d = cd.doctor(self.root, 5, {})
        self.assertEqual((d["untriaged"], d["unresolved"]), (1, 2))          # the S4 is in shadow
        self.assertEqual(d["signals"]["S4"]["status"], "shadow")

    def test_stats_can_count_only_the_current_detectors(self):
        self.capture("prompt", self.ev(prompt="Never merge a PR without CI."))
        text = (cd.capture_dir(self.root) / cd.CANDIDATES).read_text(encoding="utf-8")
        (cd.capture_dir(self.root) / cd.CANDIDATES).write_text(text.replace(',"det":2', ''), encoding="utf-8")
        self.assertEqual(cd.stats(self.root)["total"], 1)
        self.assertEqual(cd.stats(self.root, current=True)["total"], 0)


if __name__ == "__main__":
    unittest.main()
