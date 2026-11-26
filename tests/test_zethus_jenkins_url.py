"""Tests for the Jenkins base URL: `jenkins-url.py`'s resolution order (config, then the
environment, then nothing), its folder-path handling, and that the example config and the
`jenkins-cli` skill agree with it. No network; the environment is passed in, never read.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.test_zethus import KIT, load, run

jenkins_url = load(KIT / "scripts" / "jenkins-url.py")
UsageError = jenkins_url.UsageError


class ResolutionOrder(unittest.TestCase):
    def test_config_beats_the_environment(self):
        got = jenkins_url.resolve({"jenkins": {"baseUrl": "https://jenkins.example.com/"}},
                                  {"JENKINS_URL": "https://other.example.org"})
        self.assertEqual(got["source"], "config")
        self.assertEqual(got["baseUrl"], "https://jenkins.example.com")   # slash trimmed

    def test_environment_when_config_is_unset(self):
        got = jenkins_url.resolve({}, {"JENKINS_URL": "https://ci.example.org"})
        self.assertEqual((got["source"], got["baseUrl"], got["detail"]),
                         ("env", "https://ci.example.org", "$JENKINS_URL"))

    def test_blank_config_counts_as_unset(self):
        got = jenkins_url.resolve({"jenkins": {"baseUrl": "  "}},
                                  {"JENKINS_URL": "https://ci.example.org"})
        self.assertEqual(got["source"], "env")

    def test_base_url_env_renames_the_variable(self):
        config = {"jenkins": {"baseUrlEnv": "MY_CI"}}
        env = {"JENKINS_URL": "https://wrong.example.org", "MY_CI": "https://ci.example.org"}
        got = jenkins_url.resolve(config, env)
        self.assertEqual((got["baseUrl"], got["detail"]), ("https://ci.example.org", "$MY_CI"))

    def test_nothing_set_is_none_never_a_guess(self):
        got = jenkins_url.resolve({}, {"JENKINS_USER": "alice"})
        self.assertEqual(got["source"], "none")
        self.assertIsNone(got["baseUrl"])
        self.assertIsNone(got["jobUrl"])

    def test_not_a_url_is_an_error_not_a_fallthrough(self):
        with self.assertRaises(UsageError):
            jenkins_url.resolve({"jenkins": {"baseUrl": "jenkins.example.com"}},
                                {"JENKINS_URL": "https://ci.example.org"})
        with self.assertRaises(UsageError):
            jenkins_url.resolve({}, {"JENKINS_URL": "ftp://ci.example.org"})


class JobPath(unittest.TestCase):
    def test_folder_path_becomes_nested_job_segments(self):
        got = jenkins_url.resolve({"jenkins": {"baseUrl": "https://jenkins.example.com",
                                               "jobPath": "team/app"}}, {})
        self.assertEqual(got["jobUrl"], "https://jenkins.example.com/job/team/job/app")
        self.assertEqual(got["jobPath"], "team/app")

    def test_segments_are_encoded_and_slashes_normalised(self):
        got = jenkins_url.resolve({"jenkins": {"baseUrl": "https://jenkins.example.com",
                                               "jobPath": "/my team\\app v2/"}}, {})
        self.assertEqual(got["jobUrl"], "https://jenkins.example.com/job/my%20team/job/app%20v2")

    def test_job_path_applies_to_an_environment_url_too(self):
        got = jenkins_url.resolve({"jenkins": {"jobPath": "app"}},
                                  {"JENKINS_URL": "https://ci.example.org"})
        self.assertEqual(got["jobUrl"], "https://ci.example.org/job/app")

    def test_no_job_path_means_no_job_url(self):
        got = jenkins_url.resolve({"jenkins": {"baseUrl": "https://jenkins.example.com"}}, {})
        self.assertIsNone(got["jobUrl"])

    def test_job_path_must_be_a_string(self):
        with self.assertRaises(UsageError):
            jenkins_url.resolve({"jenkins": {"baseUrl": "https://jenkins.example.com",
                                             "jobPath": ["team", "app"]}}, {})


class Cli(unittest.TestCase):
    def repo_with(self, config: dict | None) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        (tmp / ".git").mkdir()
        if config is not None:
            (tmp / ".github").mkdir()
            (tmp / ".github" / "zethus.config.json").write_text(json.dumps(config), encoding="utf-8")
        return tmp

    def test_config_hit_names_its_source_and_exits_zero(self):
        repo = self.repo_with({"jenkins": {"baseUrl": "https://jenkins.example.com",
                                           "jobPath": "team/app"}})
        code, out = run(jenkins_url, "--repo", str(repo))
        self.assertEqual(code, 0, out)
        self.assertIn("config: https://jenkins.example.com (from jenkins.baseUrl)", out)
        self.assertIn("job: https://jenkins.example.com/job/team/job/app", out)

    def test_json_output(self):
        repo = self.repo_with({"jenkins": {"baseUrl": "https://jenkins.example.com"}})
        code, out = run(jenkins_url, "--repo", str(repo), "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(out)["source"], "config")

    def test_a_bad_value_exits_two(self):
        repo = self.repo_with({"jenkins": {"baseUrl": "not a url"}})
        code, out = run(jenkins_url, "--repo", str(repo))
        self.assertEqual(code, 2, out)


class SkillAndExample(unittest.TestCase):
    def test_example_config_uses_a_placeholder_host_and_the_default_env(self):
        data = json.loads((KIT / "zethus.config.example.json").read_text(encoding="utf-8"))
        section = data["jenkins"]
        self.assertRegex(section["baseUrl"], r"^https://[a-z.]*example\.(com|org|net)$")
        self.assertEqual(section["baseUrlEnv"], "JENKINS_URL")
        self.assertIn("jobPath", section)

    def test_skill_resolves_the_url_from_config_first_and_never_guesses(self):
        text = (KIT / "skills" / "jenkins-cli" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("jenkins-url.py", text)
        self.assertIn("jenkins.baseUrl", text)
        self.assertIn("jenkins.jobPath", text)
        self.assertRegex(text, r"(?i)never infer a URL")
        self.assertRegex(text, r"(?i)say which source")
        self.assertNotIn("$env:JENKINS_URL", text, "REST calls must use the resolved URL")


if __name__ == "__main__":
    unittest.main()
