"""Tests for the doc-pointer CI check.

Most tests drive ``scan`` against a small synthetic ``Tree``, so they don't depend on this repo's
contents. The last class runs the real check over the real repo, the same way CI does.
"""
import contextlib
import io
import unittest

import check_doc_pointers as cdp

FILES = {
    "README.md",
    "AGENTS.md",
    "amphion/plugin/.claude-plugin/plugin.json",
    "docs/guide.md",
    "mnemosyne/README.md",
    "mnemosyne/src/mnemosyne/stores.py",
    "mnemosyne/memory/.gitignore",
    "scripts/check.py",
    "zethus/README.md",
    "zethus/skills/demo/SKILL.md",
}


def ignored(path):
    # Mirrors mnemosyne/memory/.gitignore listing `local.jsonl`.
    return path.startswith("mnemosyne/memory/") and path.endswith("local.jsonl")


TREE = cdp.Tree(FILES, ignored)


def found(text, md="README.md"):
    """The pointers reported for ``text`` as if it were the file ``md``."""
    return [f.pointer for f in cdp.scan(text, md, TREE)]


class TestLinks(unittest.TestCase):
    def test_existing_file_and_directory_resolve(self):
        self.assertEqual(found("[g](docs/guide.md) and [m](mnemosyne/) and [r](/scripts/check.py)"), [])

    def test_relative_to_the_linking_file(self):
        self.assertEqual(found("[up](../README.md)", "docs/guide.md"), [])
        self.assertEqual(found("[s](src/mnemosyne/stores.py)", "mnemosyne/README.md"), [])

    def test_missing_target_is_reported(self):
        self.assertEqual(found("see [old](morpheus/README.md)"), ["morpheus/README.md"])

    def test_anchor_is_stripped_but_the_file_must_exist(self):
        self.assertEqual(found("[a](docs/guide.md#setup)"), [])
        self.assertEqual(found("[a](docs/gone.md#setup)"), ["docs/gone.md#setup"])

    def test_case_mismatch_is_reported_with_its_own_reason(self):
        findings = cdp.scan("[g](Docs/Guide.md)", "README.md", TREE)
        self.assertEqual(len(findings), 1)
        self.assertIn("case mismatch", findings[0].reason)

    def test_escaping_the_repo_is_reported(self):
        findings = cdp.scan("[x](../outside.md)", "README.md", TREE)
        self.assertEqual([f.reason for f in findings], ["points outside the repository"])

    def test_urls_anchors_and_mail_are_not_repo_links(self):
        text = ("[u](https://example.com/x.md) [a](#section) [m](mailto:someone@example.com) "
                "[p](//cdn.example.com/x.js)")
        self.assertEqual(found(text), [])

    def test_reference_definitions_and_images_are_checked(self):
        self.assertEqual(found("[ref]: docs/nope.md"), ["docs/nope.md"])
        self.assertEqual(found("![logo](img/logo.png)"), ["img/logo.png"])

    def test_angle_bracket_targets_and_titles(self):
        self.assertEqual(found('[g](<docs/guide.md> "Guide")'), [])
        self.assertEqual(found("[g](docs/guide.md 'Guide')"), [])

    def test_links_inside_code_are_not_links(self):
        self.assertEqual(found("`[x](missing.md)`"), [])
        self.assertEqual(found("```\n[x](missing.md)\n```"), [])
        self.assertEqual(found("~~~md\n[x](missing.md)\n~~~"), [])

    def test_line_numbers_are_reported(self):
        findings = cdp.scan("ok\n\n[x](missing.md)", "README.md", TREE)
        self.assertEqual(findings[0].line, 3)
        self.assertEqual(str(findings[0]), "README.md:3: missing.md (no such file or directory)")


class TestCodeSpans(unittest.TestCase):
    def test_existing_paths_resolve_from_the_repo_root(self):
        self.assertEqual(found("run `scripts/check.py` over `docs/guide.md`"), [])

    def test_line_suffixes_are_allowed(self):
        self.assertEqual(found("`scripts/check.py:12` and `scripts/check.py:12-20`"), [])
        self.assertEqual(found("`scripts/gone.py:12`"), ["`scripts/gone.py:12`"])

    def test_directory_spans(self):
        self.assertEqual(found("`mnemosyne/` and `docs/`"), [])
        self.assertEqual(found("`morpheus/`"), ["`morpheus/`"])
        # A trailing slash claims a directory: a file of that name doesn't satisfy it.
        self.assertEqual(found("`scripts/check.py/`"), ["`scripts/check.py/`"])

    def test_deleted_file_is_reported(self):
        self.assertEqual(found("the fixture `tests/_util.py`"), ["`tests/_util.py`"])

    def test_tail_of_a_tracked_path_resolves(self):
        self.assertEqual(found("federation lives in `src/mnemosyne/stores.py`"), [])
        self.assertEqual(found("`.claude-plugin/plugin.json`"), [])
        self.assertEqual(found("`.claude-plugin/marketplace.json`"),
                         ["`.claude-plugin/marketplace.json`"])

    def test_explicitly_relative_paths_are_not_matched_by_tail(self):
        self.assertEqual(found("`./stores.py`"), ["`./stores.py`"])

    def test_ancestor_directories_are_tried(self):
        self.assertEqual(found("`src/mnemosyne/stores.py`", "mnemosyne/README.md"), [])

    def test_gitignored_runtime_path_resolves(self):
        self.assertEqual(found("`memory/local.jsonl`", "mnemosyne/README.md"), [])
        self.assertEqual(found("`memory/lessons.jsonl`", "mnemosyne/README.md"),
                         ["`memory/lessons.jsonl`"])

    def test_non_paths_are_skipped(self):
        for span in ("origin/develop", "feature/*", "docs/<slug>.md", "~/.claude/skills/x/SKILL.md",
                     "$HOME/x.md", "github.com/kumouri/x.md", "a b/c.md", "dispatch.py",
                     "--target path/x", "mcp>=1.2", "grimoire_hook.py:21-25", "docs/adr"):
            self.assertEqual(found(f"`{span}`"), [], span)

    def test_host_directories_are_install_destinations(self):
        for span in (".claude/amphion.config.json", ".copilot/zethus.config.json",
                     ".agents/skills/x/SKILL.md", ".codex/agents/z.toml", ".cursor/rules/z.mdc"):
            self.assertEqual(found(f"`{span}`"), [], span)

    def test_example_docs_skip_spans_but_still_check_links(self):
        text = "`src/webhooks/retry.py:48` and [sibling](../missing/SKILL.md)"
        self.assertEqual(found(text, "zethus/skills/demo/SKILL.md"), ["../missing/SKILL.md"])

    def test_consumer_paths_are_scoped_to_their_kit(self):
        self.assertEqual(found("`.github/zethus/scripts/x.py`", "zethus/README.md"), [])
        self.assertEqual(found("`.github/zethus/scripts/x.py`", "README.md"),
                         ["`.github/zethus/scripts/x.py`"])

    def test_point_in_time_marker_skips_spans_but_not_links(self):
        text = f"{cdp.POINT_IN_TIME_MARKER}\n`tests/_util.py` and [x](gone.md)"
        self.assertEqual(found(text, "docs/guide.md"), ["gone.md"])

    def test_spans_in_fences_are_ignored(self):
        self.assertEqual(found("```bash\npython `tests/_util.py`\n```"), [])


class TestTree(unittest.TestCase):
    def test_parent_directories_are_known(self):
        self.assertTrue(TREE.has("mnemosyne/src", want_dir=True))
        self.assertTrue(TREE.has("mnemosyne/src/mnemosyne/stores.py"))
        self.assertFalse(TREE.has("mnemosyne/src/mnemosyne/stores.py", want_dir=True))

    def test_normalize(self):
        self.assertEqual(cdp.normalize("docs", "../README.md"), "README.md")
        self.assertIsNone(cdp.normalize("", "../x.md"))
        self.assertEqual(cdp.normalize("a/b", "./c.md"), "a/b/c.md")


class TestThisRepo(unittest.TestCase):
    """The check CI runs: every pointer in this repo's Markdown resolves."""

    def test_repo_is_clean(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = cdp.main([])
        self.assertEqual(code, 0, buf.getvalue())

    def test_unknown_path_argument_is_a_usage_error(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cdp.main(["no/such/dir"]), 2)


if __name__ == "__main__":
    unittest.main()
