"""Contract tests for the five tool skills (jira-cli, confluence-cli, datadog-cli, jenkins-cli,
sonarqube-cli): frontmatter, the public-kit scrub, the safety rules each one must keep, the
cross-links from the Jira story skills, that the installer picks them up, and that every PowerShell
block parses.

Nothing here talks to Jira, Confluence, Datadog, Jenkins or SonarQube: the commands were carried
over from reviewed notes and never run against a live instance. These tests check the shape.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_zethus import KIT, FakeHome, frontmatter, install_mod, run

TOOL_SKILLS = ("jira-cli", "confluence-cli", "datadog-cli", "jenkins-cli", "sonarqube-cli")

# Phrases that would tie a skill to one person's machine. A list of private names would itself
# publish them, so those stay with the public-commit guard outside this repo.
SCRUBBED = re.compile(r"\b(her|his) (own )?machine\b", re.I)
ALLOWED_HOSTS = {
    "github.com", "raw.githubusercontent.com", "id.atlassian.com",
    "ci.example.internal", "sonarqube.example.internal", "example.atlassian.net", "api.",
}
POWERSHELL_PARSER = r"""
param([string]$Path)
$cases = Get-Content -Raw -Path $Path | ConvertFrom-Json
$bad = @()
foreach ($case in $cases) {
  $errors = $null
  [void][System.Management.Automation.Language.Parser]::ParseInput($case.code, [ref]$null, [ref]$errors)
  if ($errors.Count) { $bad += [pscustomobject]@{ id = $case.id; message = $errors[0].Message } }
}
ConvertTo-Json -InputObject @($bad) -Compress
"""


def text_of(name: str) -> str:
    return (KIT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")


def powershell_blocks(text: str) -> list[str]:
    return re.findall(r"```powershell\n(.*?)```", text, re.S)


def jira_table_commands(text: str) -> list[str]:
    """Each `jira ...` span in a table row: the commands a reader would paste straight in."""
    spans = []
    for line in text.splitlines():
        if line.startswith("| "):
            spans += [s for s in re.findall(r"`([^`]+)`", line) if s.startswith("jira ")]
    return spans


class ToolSkillFrontmatter(unittest.TestCase):
    def test_each_skill_exists_with_valid_frontmatter(self):
        for name in TOOL_SKILLS:
            path = KIT / "skills" / name / "SKILL.md"
            self.assertTrue(path.is_file(), name)
            fm = frontmatter(path)
            self.assertEqual(fm.get("name"), name, f"{name}: name must match its folder")
            self.assertRegex(fm["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
            self.assertLessEqual(len(fm["name"]), 64)
            self.assertTrue(fm.get("description"), f"{name}: description is required")
            # Copilot drops a skill whose description is over 1024 characters, with no warning.
            self.assertLessEqual(len(fm["description"]), 1024, name)
            # An unquoted ": " in the value makes the frontmatter invalid YAML, and the CLI
            # drops the skill with a note only in its log.
            self.assertNotIn(": ", fm["description"], f"{name}: unquoted colon breaks YAML")

    def test_names_do_not_collide_with_a_personal_skill_of_the_plain_tool_name(self):
        """A personal skill silently beats a plugin skill of the same name, and a differing file
        in ~/.copilot/skills stops `install.py --user`."""
        folders = {p.name for p in (KIT / "skills").iterdir() if p.is_dir()}
        for plain in ("jira", "confluence", "datadog", "jenkins", "sonarqube"):
            self.assertNotIn(plain, folders)


class ToolSkillScrub(unittest.TestCase):
    def test_no_scrubbed_word_appears_anywhere_in_a_skill(self):
        for name in TOOL_SKILLS:
            for path in (KIT / "skills" / name).rglob("*"):
                if path.is_file():
                    hit = SCRUBBED.search(path.read_text(encoding="utf-8"))
                    self.assertIsNone(hit, f"{path.name}: {hit and hit.group(0)!r}")

    def test_only_placeholder_and_public_hosts_appear(self):
        for name in TOOL_SKILLS:
            for host in re.findall(r"https?://([A-Za-z0-9_.-]+)", text_of(name)):
                self.assertIn(host, ALLOWED_HOSTS, f"{name}: {host} is not a placeholder")


class ToolSkillSafetyRules(unittest.TestCase):
    def test_every_skill_keeps_its_approval_gate_and_the_second_layer(self):
        for name in TOOL_SKILLS:
            text = text_of(name)
            self.assertRegex(text, r"(?i)confirm|go-ahead|a yes", name)
            self.assertIn("Copilot's own", text, f"{name}: names the second approval layer")

    def test_every_skill_reads_credentials_from_the_environment_and_never_prints_them(self):
        for name in TOOL_SKILLS:
            text = text_of(name)
            self.assertRegex(text, r"(?i)environment", name)
            self.assertRegex(text, r"(?i)never\W+(print|echo)", name)

    def test_every_skill_ends_with_its_checklist(self):
        for name in TOOL_SKILLS:
            heads = [ln for ln in text_of(name).splitlines() if ln.startswith("## ")]
            self.assertTrue(any(h.startswith("## Acceptance") for h in heads), name)
            self.assertIn("- [ ] ", text_of(name), name)

    def test_datadog_never_bypasses_pups_own_prompts(self):
        text = text_of("datadog-cli")
        self.assertIn("**Never** pass `--yes`", text)
        self.assertIn("DD_AUTO_APPROVE", text)

    def test_sonarqube_mutations_are_printed_before_they_run(self):
        text = text_of("sonarqube-cli")
        self.assertIn("Always construct and print the exact command first", text)

    def test_jenkins_keeps_the_cloudbees_section_and_its_confirmations(self):
        text = text_of("jenkins-cli")
        self.assertIn("## CloudBees CI specifics", text)
        self.assertIn("reload-bundle", text)
        self.assertRegex(text, r"(?s)reload-bundle.{0,200}mutation")

    def test_jira_every_mutating_command_names_what_to_confirm(self):
        text = text_of("jira-cli")
        section = text.split("## 3. Mutating commands", 1)[1].split("\n## ", 1)[0]
        rows = [ln for ln in section.splitlines() if ln.startswith("| ") and "`jira " in ln]
        self.assertGreaterEqual(len(rows), 10)
        for row in rows:
            cells = [c for c in row.strip("|").split("|") if c.strip()]
            self.assertGreaterEqual(len(cells), 3, f"no 'confirm before running' cell: {row}")


class JiraStorySkillsUseJiraCli(unittest.TestCase):
    def test_story_skills_point_at_jira_cli_where_they_reach_jira(self):
        for name in ("story-enrich", "spec-to-stories"):
            self.assertIn("../jira-cli/SKILL.md", text_of(name), name)

    def test_the_approval_guardrail_is_not_weakened(self):
        for name in ("story-enrich", "spec-to-stories"):
            text = text_of(name)
            self.assertIn("## Guardrail", text)
            self.assertIn("approval", text.lower())
        self.assertIn("Only an explicit", text_of("story-enrich"))
        self.assertIn("Only an explicit", text_of("spec-to-stories"))

    def test_jira_cli_points_back_at_the_story_skills(self):
        text = text_of("jira-cli")
        self.assertIn("../story-enrich/SKILL.md", text)
        self.assertIn("../spec-to-stories/SKILL.md", text)

    def test_confluence_points_at_jira_cli_for_the_shared_variables(self):
        self.assertIn("../jira-cli/SKILL.md", text_of("confluence-cli"))

    def test_access_script_does_not_claim_the_jira_binary_is_only_go_jira(self):
        doc = (KIT / "scripts" / "jira-access.py").read_text(encoding="utf-8")
        self.assertIn("jira-cli", doc)
        self.assertNotIn("`jira` (go-jira)", doc)
        guide = (KIT / "docs" / "jira-skills.md").read_text(encoding="utf-8")
        self.assertIn("jira-cli", guide)
        self.assertNotIn("`jira` (go-jira)", guide)


class ToolSkillsInTheKit(unittest.TestCase):
    def test_readme_lists_every_tool_skill(self):
        readme = (KIT / "README.md").read_text(encoding="utf-8")
        for name in TOOL_SKILLS:
            self.assertIn(f"skills/{name}", readme, name)

    def test_readme_skill_count_matches_the_skills_folder(self):
        count = len([p for p in (KIT / "skills").iterdir() if (p / "SKILL.md").is_file()])
        readme = (KIT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"all {count} skills", readme)
        self.assertIn(f"listed the {count} skills", readme)

    def test_every_tool_skill_is_a_plugin_skill_and_the_versions_agree(self):
        manifest = json.loads((KIT / "plugin.json").read_text(encoding="utf-8"))
        market = json.loads((KIT.parent / ".github/plugin/marketplace.json").read_text(encoding="utf-8"))
        (entry,) = [p for p in market["plugins"] if p["name"] == "zethus"]
        self.assertEqual(manifest["version"], entry["version"])
        for name in TOOL_SKILLS:
            self.assertTrue((KIT / "skills" / name / "SKILL.md").is_file(), name)


class ToolSkillInstall(unittest.TestCase):
    def test_repo_install_copies_every_tool_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(install_mod, "--target", tmp)
            self.assertEqual(code, 0, out)
            for name in TOOL_SKILLS:
                self.assertTrue((Path(tmp) / ".github/skills" / name / "SKILL.md").is_file(), name)


class ToolSkillUserInstall(FakeHome):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(install_mod, "PLATFORM", "linux")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_user_install_records_every_tool_skill_in_the_manifest(self):
        code, out = run(install_mod, "--user")
        self.assertEqual(code, 0, out)
        manifest = json.loads((self.copilot / "zethus/install-manifest.json").read_text(encoding="utf-8"))
        recorded = {Path(k).as_posix() for k in manifest["files"]}
        for name in TOOL_SKILLS:
            self.assertTrue((self.copilot / "skills" / name / "SKILL.md").is_file(), name)
            self.assertTrue(any(r.endswith(f"skills/{name}/SKILL.md") for r in recorded), name)

    def test_a_personal_skill_of_the_plain_name_is_untouched_and_does_not_block(self):
        mine = self.copilot / "skills" / "jira" / "SKILL.md"
        mine.parent.mkdir(parents=True)
        mine.write_text("mine", encoding="utf-8")
        code, out = run(install_mod, "--user")
        self.assertEqual(code, 0, out)
        self.assertEqual(mine.read_text(encoding="utf-8"), "mine")


@unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 (pwsh) is not installed")
class ToolSkillPowerShell(unittest.TestCase):
    """Round-trips every fenced powershell block, and every `jira ...` command in a table, through
    PowerShell's own parser. A bare `<PLACEHOLDER>` as its own argument is a parse error there,
    because `<` is a reserved operator: those must be quoted."""

    def parse(self, cases: list[dict]) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            script, payload = Path(tmp) / "parse.ps1", Path(tmp) / "cases.json"
            script.write_text(POWERSHELL_PARSER, encoding="utf-8")
            payload.write_text(json.dumps(cases), encoding="utf-8")
            done = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(script), str(payload)],
                capture_output=True, text=True, timeout=120,
            )
        self.assertEqual(done.returncode, 0, done.stderr)
        bad = json.loads(done.stdout)
        return bad if isinstance(bad, list) else [bad]

    def test_every_powershell_block_parses(self):
        cases = []
        for name in TOOL_SKILLS:
            blocks = powershell_blocks(text_of(name))
            self.assertTrue(blocks, f"{name}: has no powershell blocks")
            cases += [{"id": f"{name} block {i + 1}", "code": code} for i, code in enumerate(blocks)]
        self.assertEqual(self.parse(cases), [])

    def test_every_jira_table_command_parses(self):
        spans = jira_table_commands(text_of("jira-cli"))
        self.assertGreaterEqual(len(spans), 15)
        cases = [{"id": span, "code": span} for span in spans]
        self.assertEqual(self.parse(cases), [])


if __name__ == "__main__":
    unittest.main()
