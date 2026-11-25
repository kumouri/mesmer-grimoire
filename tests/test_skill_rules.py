"""The agentskills.io rules for a skill's ``name`` and ``description`` (stage 1 section 3.4's skill
frontmatter lint), over every skill in the repo: Zethus's, Amphion's, Mnemosyne's and the shared
core's source. ``tests/test_frontmatter.py`` already proves each file's frontmatter *parses*; this
proves it says something a host will accept. CI runs it as its own step so a failure names the rule.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests.test_frontmatter import REPO, frontmatter, kit_files

NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def field(head: str, key: str) -> str:
    """One top-level frontmatter field as a string: plain, quoted, or a folded or literal block."""
    lines = head.splitlines()
    for i, line in enumerate(lines):
        m = re.match(rf"{key}:\s*(.*)$", line)
        if not m:
            continue
        value = m.group(1).strip()
        if value[:1] in ("|", ">"):
            block = []
            for nxt in lines[i + 1:]:
                if nxt and not nxt[0].isspace():
                    break
                block.append(nxt.strip())
            return " ".join(b for b in block if b)
        if value[:1] == '"':
            return json.loads(value)
        if value[:1] == "'":
            return value[1:-1].replace("''", "'")
        for nxt in lines[i + 1:]:              # a plain scalar can continue on indented lines
            if not nxt.startswith((" ", "\t")):
                break
            value += " " + nxt.strip()
        return value
    return ""


def skills() -> list[Path]:
    return [p for p in kit_files() if p.name == "SKILL.md"]


class SkillRules(unittest.TestCase):
    def test_the_lint_sees_every_kit_and_the_core(self):
        top = {p.relative_to(REPO).as_posix().split("/")[0] for p in skills()}
        self.assertTrue({"zethus", "amphion", "mnemosyne", "core"} <= top, top)

    def test_the_name_is_the_folder_and_is_a_valid_name(self):
        for path in skills():
            with self.subTest(path.relative_to(REPO).as_posix()):
                name = field(frontmatter(path.read_text(encoding="utf-8")), "name")
                self.assertEqual(name, path.parent.name, "the name must equal its folder")
                self.assertLessEqual(len(name), 64)
                self.assertRegex(name, NAME, "lowercase letters, digits and single hyphens")

    def test_the_description_is_present_and_within_the_limit(self):
        for path in skills():
            with self.subTest(path.relative_to(REPO).as_posix()):
                desc = field(frontmatter(path.read_text(encoding="utf-8")), "description")
                self.assertGreater(len(desc.strip()), 0)
                self.assertLessEqual(len(desc), 1024)

    def test_two_skills_in_one_install_set_never_share_a_name(self):
        """Personal and project skills of one name silently beat each other, so each install set
        (a plugin folder, or the kit's own) must hold every name once."""
        for root in ("zethus/skills", "amphion/plugin/skills", "mnemosyne/plugin/skills", "core/skills"):
            names = [p.name for p in (REPO / root).iterdir() if p.is_dir()]
            self.assertEqual(len(names), len(set(names)), root)

    def test_the_lint_itself_rejects_what_it_should(self):
        self.assertIsNone(NAME.fullmatch("Bad_Name"))
        self.assertIsNone(NAME.fullmatch("double--hyphen"))
        self.assertIsNone(NAME.fullmatch("-leading"))
        self.assertIsNotNone(NAME.fullmatch("a-b-2"))
        self.assertEqual(field("name: a\ndescription: >\n  one\n  two\nother: 1", "description"), "one two")
        self.assertEqual(field('name: a\ndescription: "q: x"', "description"), "q: x")


if __name__ == "__main__":
    unittest.main()
