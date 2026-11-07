"""Every agent and skill file's frontmatter must be valid YAML, because the Copilot CLI drops the
whole file when it isn't, and says so only in its log ("frontmatter is malformed ... mapping values
are not allowed"; ``--agent zethus`` then fails with "No such agent"). IntelliJ's language server
is lenient, so a broken file looks fine there.

This repo's CI is stdlib-only, so ``check`` below is a strict reader for the subset of YAML the kit
writes: top-level ``key: value`` lines, plain / quoted / flow / block scalars. It rejects what a real
parser rejects in that subset. When PyYAML happens to be installed, every file is also parsed with
it, as a cross-check that this reader and a real parser agree.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "node_modules", ".venv", "venv"}


def kit_files() -> list[Path]:
    """Every agent file (source and generated mirror) and every skill, wherever the kit keeps them."""
    found = [*REPO.rglob("*.agent.md"), *REPO.rglob("SKILL.md")]
    return sorted(p for p in found if not SKIP_DIRS & set(p.relative_to(REPO).parts))


def frontmatter(text: str) -> str:
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].rstrip() != "---":
        raise ValueError("no frontmatter: the file must open with ---")
    for i, line in enumerate(lines[1:], 1):
        if line.rstrip() == "---":
            return "\n".join(lines[1:i])
    raise ValueError("frontmatter is never closed with ---")


def plain_problem(value: str) -> str | None:
    if re.search(r":(\s|$)", value):
        return "a colon followed by a space (or at the end) makes it a nested mapping"
    if re.search(r"\s#", value):
        return "' #' starts a comment and silently cuts the value short"
    if value[0] in "&*!|>%@`," or (value[0] in "-?" and len(value) > 1 and value[1] == " "):
        return f"a plain value cannot start with {value[0]!r}"
    return None


def scalar_problem(value: str) -> str | None:
    """Why ``value`` (text after ``key:``, already stripped) is not one valid YAML scalar, or None."""
    if not value or value[0] in "|>":
        return None
    if value[0] == '"':
        try:
            json.loads(value)
        except ValueError:
            return "a double-quoted value must end at its closing quote, with inner quotes escaped"
        return None
    if value[0] == "'":
        if not re.fullmatch(r"'(?:[^']|'')*'", value):
            return "a single-quoted value must end at its closing quote, with inner quotes doubled"
        return None
    if value[0] in "[{":
        try:
            json.loads(value)
        except ValueError:
            return "a flow collection here must be valid JSON"
        return None
    return plain_problem(value)


def check(text: str) -> list[str]:
    """Every reason the frontmatter would not parse; empty when it is fine."""
    try:
        head = frontmatter(text)
    except ValueError as exc:
        return [str(exc)]
    problems: list[str] = []
    seen: set[str] = set()
    owner = None  # (key, value-so-far) of the last top-level key, to judge continuation lines
    for n, line in enumerate(head.splitlines(), 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            if owner == "plain":
                why = plain_problem(line.strip())
                if why:
                    problems.append(f"line {n}: {why}")
            continue
        m = re.match(r"([A-Za-z0-9_.-]+):(?:\s+(.*?))?\s*$", line)
        if not m:
            problems.append(f"line {n}: not a 'key: value' line")
            owner = None
            continue
        key, value = m[1], m[2] or ""
        if key in seen:
            problems.append(f"line {n}: duplicate key {key!r}")
        seen.add(key)
        why = scalar_problem(value)
        if why:
            problems.append(f"line {n}: {key}: {why}")
        owner = "plain" if value and value[0] not in "\"'[{|>" else None
    return problems


class FrontmatterChecker(unittest.TestCase):
    """The checker has to catch the real failure, or the sweep below proves nothing."""

    def test_the_unquoted_colon_that_broke_the_zethus_agent_is_caught(self):
        text = "---\nname: z\ndescription: Keeps going until the gate: it stops.\n---\nbody\n"
        self.assertTrue(any("colon" in p for p in check(text)), check(text))

    def test_quoting_fixes_it(self):
        text = '---\nname: z\ndescription: "Keeps going until the gate: it stops."\n---\nbody\n'
        self.assertEqual(check(text), [])

    def test_other_ways_a_value_breaks(self):
        for bad in ("a # b", "- x: y", "*alias", '"open', '"closed" trailing', "'it's'", "[1, 2", "{a: 1"):
            with self.subTest(bad):
                self.assertTrue(check(f"---\nname: z\ndescription: {bad}\n---\n"), bad)

    def test_the_shapes_the_kit_uses_pass(self):
        for good in ('["read", "search"]', "plain words, with commas", "it's fine", '"say \\"hi\\": ok"',
                     "'it''s: fine'", ">", "|", "see a:b and http://x.y/z", "a#b"):
            with self.subTest(good):
                self.assertEqual(check(f"---\nname: z\ndescription: {good}\n---\n"), [], good)

    def test_folded_block_and_plain_continuation(self):
        folded = "---\nname: z\ndescription: >\n  Anything: goes here # too\n  at all.\n---\n"
        self.assertEqual(check(folded), [])
        plain = "---\nname: z\ndescription: first line\n  second: line\n---\n"
        self.assertTrue(check(plain))

    def test_missing_or_unclosed_frontmatter(self):
        self.assertTrue(check("no frontmatter\n"))
        self.assertTrue(check("---\nname: z\n"))


class KitFrontmatter(unittest.TestCase):
    def test_the_sweep_finds_the_agent_source_mirror_and_skills(self):
        rel = {p.relative_to(REPO).as_posix() for p in kit_files()}
        self.assertIn("zethus/com.github.copilot/agents/zethus.agent.md", rel)
        self.assertIn("zethus/agents/zethus.agent.md", rel)
        self.assertTrue(any(r.endswith("SKILL.md") for r in rel))

    def test_every_agent_and_skill_frontmatter_parses(self):
        for path in kit_files():
            with self.subTest(path.relative_to(REPO).as_posix()):
                self.assertEqual(check(path.read_text(encoding="utf-8")), [])

    def test_every_agent_and_skill_declares_name_and_description(self):
        for path in kit_files():
            with self.subTest(path.relative_to(REPO).as_posix()):
                head = frontmatter(path.read_text(encoding="utf-8"))
                for key in ("name", "description"):
                    self.assertRegex(head, rf"(?m)^{key}:", path.as_posix())

    def test_a_real_yaml_parser_agrees_when_one_is_installed(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed; the strict reader above is what CI runs")
        for path in kit_files():
            with self.subTest(path.relative_to(REPO).as_posix()):
                data = yaml.safe_load(frontmatter(path.read_text(encoding="utf-8")))
                self.assertIsInstance(data, dict)
                self.assertIsInstance(data.get("description"), str)


if __name__ == "__main__":
    unittest.main()
