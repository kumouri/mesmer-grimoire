"""Zethus names the person it works for, never a placeholder (``zethus/docs/identity-of-the-person.md``).

Ceryce's report, 2026-11-19 (paraphrased): Zethus couldn't tell who it was working for, so its ADRs
and other docs wrote "Requester" or a similar stand-in wherever they recorded who asked for,
approved or decided something. ``new-adr.py`` and ``new-spec.py`` defaulted those fields to ``TBD``.

These tests pin the resolution order (config, most personal first; git; the forge account; then
nothing), that the first source wins whole, the run log (every step and the winner, never the
values), the refusal of placeholders, ``identity.py`` and its ``--save``, the scripts that fill
the fields, the ``sessionStart`` hook, and the wording in the templates, skills, agent and
working agreement.

Every test runs in a throwaway home with no git identity and the forge step stubbed, so neither
the developer's own name nor the network can reach it.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
KIT = REPO / "zethus"
SCRIPTS = KIT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import _identity  # noqa: E402

AGENTS = (KIT / "com.github.copilot" / "agents" / "zethus.agent.md", KIT / "agents" / "zethus.agent.md")
AGREEMENT = KIT / "copilot-instructions.md"
RECORD = KIT / "docs" / "identity-of-the-person.md"
HOOK = KIT / "com.github.copilot" / "hooks" / "session_start.py"
NAME = "Alex Example"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


identity_cli = load(SCRIPTS / "identity.py", "zethus_identity_cli")
adr_mod = load(SCRIPTS / "new-adr.py", "zethus_identity_new_adr")
spec_mod = load(SCRIPTS / "new-spec.py", "zethus_identity_new_spec")
hook_mod = load(HOOK, "zethus_identity_session_start")


def run(module, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = module.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def flat(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


class Hermetic(unittest.TestCase):
    """A git repo in a throwaway home: no global or system git identity, no ``$ZETHUS_CONFIG``,
    the run log in the home, and ``gh`` replaced by :meth:`gh` (unset: not installed)."""

    gh_reply: subprocess.CompletedProcess | Exception | None = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.log = self.home / "identity.log"
        env = {"HOME": str(self.home), "USERPROFILE": str(self.home),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": str(self.home / ".gitconfig"),
               "ZETHUS_IDENTITY_LOG": str(self.log), "ZETHUS_IDENTITY_FORGE": "on"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        for var in ("ZETHUS_CONFIG", "GH_HOST"):
            os.environ.pop(var, None)
        self.git("init", "-q")
        self.gh_calls: list[list[str]] = []
        real_run = subprocess.run

        def fake_run(argv, *args, **kwargs):
            if argv and argv[0] == "gh":
                self.gh_calls.append(list(argv))
                reply = self.gh_reply
                if reply is None:
                    raise FileNotFoundError("gh")
                if isinstance(reply, Exception):
                    raise reply
                return reply
            return real_run(argv, *args, **kwargs)

        sub = mock.patch.object(_identity.subprocess, "run", side_effect=fake_run)
        sub.start()
        self.addCleanup(sub.stop)

    def git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), *args], check=True, capture_output=True)

    def git_name(self, name: str) -> None:
        self.git("config", "user.name", name)

    def config(self, rel: str, data: dict, base: Path | None = None) -> Path:
        path = (base or self.repo) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def user_config(self, data: dict) -> Path:
        return self.config(".copilot/zethus/config.json", data, base=self.home)

    def gh_user(self, name: str | None, login: str | None, code: int = 0) -> None:
        self.gh_reply = subprocess.CompletedProcess(
            ["gh"], code, stdout=json.dumps({"name": name, "login": login}),
            stderr="" if code == 0 else "HTTP 401: Bad credentials")

    def resolve(self, **kwargs):
        log = _identity.RunLog(self.log)
        try:
            return _identity.resolve(self.repo, log=log, **kwargs)
        finally:
            log.close()

    def log_text(self) -> str:
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""


class ResolutionOrder(Hermetic):
    def test_config_beats_git_and_the_forge(self):
        self.user_config({"identity": {"name": NAME, "handle": "alexex"}})
        self.git_name("Someone Else")
        self.gh_user("Forge Name", "forgelogin")
        found = self.resolve()
        self.assertEqual((found.name, found.handle, found.step), (NAME, "alexex", 1))
        self.assertEqual(found.source, "config ~/.copilot/zethus/config.json")
        self.assertEqual(self.gh_calls, [], "a later step is not tried once one wins")

    def test_personal_config_beats_the_committed_one(self):
        self.config(".github/zethus.config.json", {"identity": {"name": "Team Default"}})
        self.config(".copilot/zethus.config.json", {"identity": {"name": NAME}})
        self.assertEqual(self.resolve().display, NAME)

    def test_user_config_beats_the_committed_one_even_though_other_keys_come_from_the_repo(self):
        self.config(".github/zethus.config.json", {"gates": {"steps": []}})
        self.user_config({"identity": {"name": NAME}})
        self.assertEqual(self.resolve().display, NAME)

    def test_zethus_config_and_explicit_config_come_first(self):
        self.user_config({"identity": {"name": "User Default"}})
        env_cfg = self.config("elsewhere.json", {"identity": {"name": "From Env"}})
        os.environ["ZETHUS_CONFIG"] = str(env_cfg)
        self.assertEqual(self.resolve().display, "From Env")
        explicit = self.config("explicit.json", {"identity": {"name": NAME}})
        self.assertEqual(self.resolve(config=str(explicit)).display, NAME)

    def test_committed_or_amphion_config_still_counts_when_nothing_personal_exists(self):
        self.config(".claude/amphion.config.json", {"identity": {"name": NAME}})
        self.git_name("Someone Else")
        self.assertEqual(self.resolve().display, NAME)

    def test_git_user_name_when_config_has_none(self):
        self.user_config({"commits": {"aiTrailer": "x"}})
        self.git_name(NAME)
        found = self.resolve()
        self.assertEqual((found.display, found.step, found.source), (NAME, 2, "git config user.name"))

    def test_git_email_is_never_used(self):
        self.git("config", "user.email", "alex@example.com")
        found = self.resolve(forge=False)
        self.assertFalse(found.resolved)
        self.assertNotIn("example.com", json.dumps(found.as_dict()))

    def test_forge_name_then_login_when_config_and_git_give_nothing(self):
        self.gh_user(NAME, "alexex")
        found = self.resolve()
        self.assertEqual((found.name, found.handle, found.step), (NAME, "alexex", 3))
        self.assertEqual(self.gh_calls[0][:3], ["gh", "api", "user"])
        self.gh_user(None, "alexex")
        self.assertEqual(self.resolve().display, "alexex", "the login when the account has no name")

    def test_forge_host_follows_origin(self):
        self.git("remote", "add", "origin", "git@github.example.org:team/repo.git")
        self.gh_user(NAME, "alexex")
        self.resolve()
        self.assertEqual(self.gh_calls[0][-2:], ["--hostname", "github.example.org"])

    def test_forge_skipped_for_a_non_github_origin(self):
        self.git("remote", "add", "origin", "https://gitlab.example.org/team/repo.git")
        found = self.resolve()
        self.assertFalse(found.resolved)
        self.assertEqual(self.gh_calls, [])
        self.assertTrue(any("not a GitHub host" in line for line in found.trace))

    def test_forge_off_by_flag_or_env(self):
        self.gh_user(NAME, "alexex")
        self.assertFalse(self.resolve(forge=False).resolved)
        os.environ["ZETHUS_IDENTITY_FORGE"] = "off"
        self.assertFalse(self.resolve().resolved)
        self.assertEqual(self.gh_calls, [])

    def test_forge_failures_are_traced_not_raised(self):
        self.gh_user(None, None, code=1)
        self.assertIn("exit 1", self.resolve().trace[-1])
        self.gh_reply = subprocess.TimeoutExpired(["gh"], 8)
        self.assertIn("TimeoutExpired", self.resolve().trace[-1])
        self.gh_reply = None
        self.assertIn("gh is not installed", self.resolve().trace[-1])

    def test_unresolved_traces_every_step(self):
        found = self.resolve()
        self.assertFalse(found.resolved)
        self.assertEqual(found.display, "")
        self.assertEqual([line[0] for line in found.trace], ["1", "2", "3"])

    def test_the_first_source_wins_whole(self):
        """A handle in config and a name in git are not stitched together."""
        self.user_config({"identity": {"handle": "alexex"}})
        self.git_name(NAME)
        found = self.resolve()
        self.assertEqual((found.name, found.handle, found.display), ("", "alexex", "alexex"))

    def test_names_are_kept_as_written(self):
        written = "  dr. ana-maría o'neill-NGUYEN  "
        self.user_config({"identity": {"name": written}})
        self.assertEqual(self.resolve().display, written.strip())

    def test_placeholders_in_any_source_are_skipped(self):
        self.user_config({"identity": {"name": "TBD"}})
        self.git_name("Requester")
        self.gh_user(NAME, None)
        found = self.resolve()
        self.assertEqual((found.display, found.step), (NAME, 3))

    def test_unreadable_config_is_skipped_not_fatal(self):
        bad = self.repo / ".copilot" / "zethus.config.json"
        bad.parent.mkdir()
        bad.write_text("{not json", encoding="utf-8")
        self.git_name(NAME)
        found = self.resolve()
        self.assertEqual(found.display, NAME)
        self.assertTrue(any("unreadable" in line for line in found.trace))


class Placeholders(unittest.TestCase):
    def test_stand_ins_are_placeholders(self):
        for value in ("TBD", "tbd", " Requester ", "the user", "User", "Unknown", "N/A", "—", "",
                      "<who>", "{{owner}}", "[name]", "…", "the person", "Approver", "owner"):
            self.assertTrue(_identity.is_placeholder(value), repr(value))

    def test_real_names_teams_and_roles_someone_wrote_are_not(self):
        for value in (NAME, "alexex", "Payments team", "Team A", "Platform guild", "Ana María"):
            self.assertFalse(_identity.is_placeholder(value), value)


class RunLog(Hermetic):
    def test_every_step_and_the_winner_are_logged_without_values(self):
        self.git_name(NAME)
        self.resolve()
        log = self.log_text()
        self.assertIn("identity: start", log)
        self.assertIn("1 config: no config holds identity.name or identity.handle", log)
        self.assertIn("2 git user.name: present", log)
        self.assertIn("3: not tried (an earlier source won)", log)
        self.assertIn("identity: resolved from git config user.name (step 2)", log)
        self.assertNotIn(NAME, log, "the log records that a value was present, never the value")

    def test_unresolved_is_logged(self):
        self.resolve()
        self.assertIn("identity: unresolved after config, git and forge", self.log_text())

    def test_each_line_carries_the_run_id_and_survives_without_close(self):
        log = _identity.RunLog(self.log)
        log("first line")
        self.assertIn(f"[{log.run_id}] first line", self.log_text(), "flushed as written")
        log.close()

    def test_log_off_and_an_unwritable_log_never_cost_the_run(self):
        self.git_name(NAME)
        os.environ["ZETHUS_IDENTITY_LOG"] = "off"
        self.assertIsNone(_identity.log_path())
        blocked = self.root / "a-file"
        blocked.write_text("", encoding="utf-8")
        log = _identity.RunLog(blocked / "sub" / "identity.log")
        self.assertTrue(log.error)
        self.assertEqual(_identity.resolve(self.repo, log=log).display, NAME)

    def test_default_log_lives_in_the_user_home(self):
        os.environ.pop("ZETHUS_IDENTITY_LOG")
        self.assertEqual(_identity.log_path(),
                         self.home / ".copilot" / "zethus" / "logs" / "identity.log")


class IdentityCli(Hermetic):
    def cli(self, *argv: str):
        return run(identity_cli, "--repo", str(self.repo), *argv)

    def test_resolved_report_names_the_source_and_the_agent_rule(self):
        self.git_name(NAME)
        code, out, _ = self.cli()
        self.assertEqual(code, 0)
        self.assertIn(f"Working for: {NAME}. Source: git config user.name (step 2 of 3, git).", out)
        self.assertIn("never the approver or the decider", out)
        self.assertIn("Run log:", out)

    def test_unresolved_exits_1_and_says_to_ask_once(self):
        code, out, _ = self.cli()
        self.assertEqual(code, 1)
        self.assertIn("Working for: not resolved", out)
        self.assertIn("Ask the person once, with the question tool", out)
        self.assertIn("Never write a placeholder", out)

    def test_field_and_json(self):
        self.user_config({"identity": {"name": NAME, "handle": "alexex"}})
        self.assertEqual(self.cli("--field", "display")[1].strip(), NAME)
        self.assertEqual(self.cli("--field", "handle")[1].strip(), "alexex")
        data = json.loads(self.cli("--json")[1])
        self.assertEqual((data["resolved"], data["step"], data["agent"]), (True, 1, "Zethus (AI agent)"))

    def test_field_prints_nothing_when_unresolved(self):
        code, out, _ = self.cli("--field", "display")
        self.assertEqual((code, out), (1, ""))

    def test_no_forge_flag(self):
        self.gh_user(NAME, None)
        self.assertEqual(self.cli("--no-forge")[0], 1)
        self.assertEqual(self.gh_calls, [])

    def test_save_to_user_config_merges_and_is_then_resolved(self):
        path = self.user_config({"commits": {"aiTrailer": "keep me"}})
        code, out, _ = self.cli("--save", "--name", NAME, "--handle", "alexex")
        self.assertEqual(code, 0, out)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["commits"], {"aiTrailer": "keep me"}, "other keys untouched")
        self.assertEqual(data["identity"], {"name": NAME, "handle": "alexex"})
        self.assertEqual(self.cli("--field", "display")[1].strip(), NAME)
        self.assertIn("saved identity.name, identity.handle", self.log_text())
        self.assertNotIn(NAME, self.log_text())

    def test_save_to_repo_writes_the_untracked_file_never_the_committed_one(self):
        code, out, _ = self.cli("--save", "--to", "repo", "--name", NAME)
        self.assertEqual(code, 0, out)
        self.assertTrue((self.repo / ".copilot" / "zethus.config.json").is_file())
        self.assertFalse((self.repo / ".github").exists())
        self.assertIn("info/exclude", out)

    def test_save_refuses_placeholders_and_bad_json_and_touches_nothing(self):
        code, _, err = self.cli("--save", "--name", "Requester")
        self.assertEqual(code, 2)
        self.assertIn("placeholder", err)
        self.assertFalse((self.home / ".copilot" / "zethus" / "config.json").exists())
        bad = self.home / ".copilot" / "zethus" / "config.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("{oops", encoding="utf-8")
        self.assertEqual(self.cli("--save", "--name", NAME)[0], 2)
        self.assertEqual(bad.read_text(encoding="utf-8"), "{oops")
        self.assertEqual(self.cli("--save")[0], 2, "nothing to save")
        self.assertEqual(self.cli("--name", NAME)[0], 2, "--name only goes with --save")


class ScriptsFillTheFields(Hermetic):
    def adr(self, *argv: str):
        return run(adr_mod, "--repo", str(self.repo), "--date", "2026-01-15", *argv)

    def spec(self, *argv: str):
        return run(spec_mod, "--repo", str(self.repo), "--date", "2026-01-15", *argv)

    def test_no_tbd_default_survives(self):
        for script in ("new-adr.py", "new-spec.py"):
            text = (SCRIPTS / script).read_text(encoding="utf-8")
            self.assertNotIn('default="TBD"', text, script)

    def test_adr_deciders_resolved_and_agent_recorded_apart(self):
        self.git_name(NAME)
        code, out, err = self.adr("Use the outbox")
        self.assertEqual(code, 0, err)
        self.assertIn(f"deciders: {NAME} (git config user.name)", out)
        text = (self.repo / "docs/adr/2026-01-15-use-the-outbox.md").read_text(encoding="utf-8")
        self.assertIn(f"| Deciders | {NAME} |", text)
        self.assertIn("| Recorded by | Zethus (AI agent) |", text)
        self.assertNotIn("{{", text)
        self.assertNotIn("| Deciders | TBD |", text)

    def test_adr_refuses_with_no_one_to_name_and_writes_nothing(self):
        code, _, err = self.adr("Use the outbox")
        self.assertEqual(code, 2)
        self.assertIn("who decided: not known", err)
        self.assertIn("Not writing a placeholder", err)
        self.assertFalse((self.repo / "docs").exists(), "no record and no index row")

    def test_adr_refuses_a_placeholder_flag(self):
        self.git_name(NAME)
        for value in ("TBD", "Requester", "<who>"):
            code, _, err = self.adr("Use the outbox", "--deciders", value)
            self.assertEqual(code, 2, value)
            self.assertIn("placeholder", err)
        self.assertFalse((self.repo / "docs").exists())

    def test_adr_names_someone_else_when_told(self):
        self.git_name(NAME)
        self.assertEqual(self.adr("Use the outbox", "--deciders", "Payments team")[0], 0)
        text = (self.repo / "docs/adr/2026-01-15-use-the-outbox.md").read_text(encoding="utf-8")
        self.assertIn("| Deciders | Payments team |", text)

    def test_spec_owner_and_requester_resolved(self):
        self.user_config({"identity": {"name": NAME}})
        for kind in ("full", "minimum"):
            code, out, err = self.spec(kind, f"Retry {kind}")
            self.assertEqual(code, 0, err)
            text = (self.repo / f"docs/specs/retry-{kind}.md").read_text(encoding="utf-8")
            self.assertIn(f"**Owner:** {NAME}", text)
            self.assertIn(f"**Requested by:** {NAME}", text)
            self.assertIn("**Signed off:** not yet", text)
            self.assertIn("**Written by:** Zethus (AI agent)", text)
            self.assertNotIn("{{", text)
            self.assertNotIn("requester's exact words", text)

    def test_spec_team_owner_still_resolves_the_requester(self):
        self.git_name(NAME)
        code, out, _ = self.spec("minimum", "Trim", "--owner", "Payments team")
        self.assertEqual(code, 0)
        self.assertIn(f"owner: Payments team (given explicitly); requested by: {NAME} (git config "
                      "user.name)", out)

    def test_spec_refuses_with_no_one_and_on_placeholders(self):
        self.assertEqual(self.spec("minimum", "Trim")[0], 2)
        self.git_name(NAME)
        self.assertEqual(self.spec("minimum", "Trim", "--owner", "TBD")[0], 2)
        self.assertEqual(self.spec("minimum", "Trim", "--requester", "the user")[0], 2)
        self.assertFalse((self.repo / "docs").exists())

    def test_scripts_log_which_source_won(self):
        self.git_name(NAME)
        self.adr("Use the outbox")
        log = self.log_text()
        self.assertIn("new-adr: 2026-01-15-use-the-outbox", log)
        self.assertIn("identity: resolved from git config user.name (step 2)", log)
        self.assertIn("new-adr: wrote docs/adr/2026-01-15-use-the-outbox.md", log)
        self.assertNotIn(NAME, log)


class SessionStartHook(Hermetic):
    def test_announces_who_from_config_or_git_without_the_forge(self):
        self.git_name(NAME)
        self.gh_user("Forge Name", "forgelogin")
        text = hook_mod.working_for(str(self.repo))
        self.assertIn(f"Working for: **{NAME}** (source: git config user.name)", text)
        self.assertIn("never the approver or decider", text)
        self.assertEqual(self.gh_calls, [], "the hook never waits on the network")

    def test_says_so_when_unresolved_and_points_at_the_script(self):
        self.gh_user(NAME, None)
        text = hook_mod.working_for(str(self.repo))
        self.assertIn("Working for: not resolved from config or git", text)
        self.assertIn("scripts/identity.py", text)
        self.assertIn("ask the person once", text)
        self.assertEqual(self.gh_calls, [])

    def test_the_announcement_goes_out_with_the_agreement(self):
        self.git_name(NAME)
        with mock.patch.object(hook_mod, "user_copy", return_value=False):
            text = hook_mod.context({"cwd": str(self.repo)})
        self.assertIn("## Who you are working for", text)
        self.assertIn(NAME, text)

    def test_fail_open(self):
        with mock.patch.object(_identity, "resolve", side_effect=RuntimeError("boom")):
            self.assertIn("not resolved", hook_mod.working_for(str(self.repo)))


class WordingEverywhere(unittest.TestCase):
    def test_templates(self):
        adr = (KIT / "templates" / "adr.md").read_text(encoding="utf-8")
        self.assertIn("| Deciders | {{deciders}} |\n| Recorded by | {{recordedBy}} |", adr)
        for name in ("spec-full.md", "spec-minimum.md"):
            text = flat(KIT / "templates" / name)
            with self.subTest(template=name):
                self.assertIn("**Requested by:** {{requester}} · **Signed off:** {{signedOff}} · "
                              "**Written by:** {{writtenBy}}", text)
                self.assertIn("never a placeholder", text)
                self.assertIn("The agent is only ever *Written by*", text)
                self.assertNotIn("requester's exact words", text)
        self.assertIn("**Requested by:**", flat(KIT / "templates" / "pr.md"))
        self.assertIn("never the agent", flat(KIT / "templates" / "constitution.md"))

    def test_skills_resolve_instead_of_asking_for_a_literal(self):
        for skill in ("write-adr", "write-spec-full", "write-spec-minimum", "zethus-pr-description"):
            text = flat(KIT / "skills" / skill / "SKILL.md")
            with self.subTest(skill=skill):
                self.assertIn("scripts/identity.py", text)
                self.assertRegex(text, r"[Nn]ever (?:a placeholder|write a placeholder|pass a stand-in)")
        self.assertNotIn('--deciders "<who>"', flat(KIT / "skills" / "write-adr" / "SKILL.md"))
        self.assertNotIn('--owner "<who signs off>"', flat(KIT / "skills" / "write-spec-full" / "SKILL.md"))

    def test_agent_and_mirror(self):
        for path in AGENTS:
            text = flat(path)
            with self.subTest(where=path.parent.parent.name):
                self.assertIn("config read; `identity.py` names who you work for |", text)
                self.assertIn("**Name the person, never a placeholder.**", text)
                self.assertIn("docs/identity-of-the-person.md", text)
                self.assertIn("`plan.checklist`, `identity.*`", text)

    def test_working_agreement(self):
        text = flat(AGREEMENT)
        self.assertIn("## Who you work for", AGREEMENT.read_text(encoding="utf-8"))
        for phrase in ("scripts/identity.py", "`git config user.name`", "`gh api user`",
                       "ask the person once, at the start", "Never write a placeholder",
                       "you never approve or decide", "docs/identity-of-the-person.md"):
            self.assertIn(phrase, text)

    def test_decision_record_and_readme(self):
        record = RECORD.read_text(encoding="utf-8")
        self.assertIn("| Deciders |", record)
        self.assertIn("paraphrased", record)
        self.assertIn("2026-11-19", record)
        readme = (KIT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/identity-of-the-person.md", readme)
        self.assertIn("| `identity.name`, `identity.handle` |", readme)
        self.assertIn("[`scripts/identity.py`](scripts/identity.py)", readme)

    def test_example_config_names_no_one(self):
        data = json.loads((KIT / "zethus.config.example.json").read_text(encoding="utf-8"))
        self.assertEqual(data["identity"], {"name": "", "handle": ""})


if __name__ == "__main__":
    unittest.main()
