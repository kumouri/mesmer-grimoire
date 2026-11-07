"""Tests for the machine-identifier CI guard.

The bad shapes below are synthetic. `jdoe` / `mmiller` are invented account
names and `acme-holdings` is an invented workspace segment -- nothing in this
file is a real identifier, which is why `check_identifiers.py` skips this path
via SKIP_PATHS rather than flagging its own fixtures.
"""
import contextlib
import io
import pathlib
import tempfile
import unittest

import check_identifiers as ci

B = "\\"  # keeps Windows path fixtures readable without escape soup


def run_main(argv):
    """Call main() with its report captured, so tests stay quiet."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        return ci.main(argv)


def matches(line):
    """All matched texts the guard reports for a single line."""
    return [m for m, _ in ci.scan_line(line)]


class TestWindowsUserPath(unittest.TestCase):
    def test_fires_on_real_looking_account_name(self):
        for line in (
            f"C:{B}Users{B}jdoe{B}workspace{B}thing",
            f'doc = "C:{B}{B}Users{B}{B}jdoe{B}{B}repo"',   # doubled, as in a string literal
            "C:/Users/jdoe/repo",                            # forward slashes
            f"D:{B}users{B}mmiller{B}x",                     # any drive, any case
        ):
            self.assertTrue(matches(line), f"should have fired: {line}")

    def test_placeholders_do_not_fire(self):
        for name in ("<user>", "<username>", "alice", "bob", "USERNAME", "%USERNAME%"):
            line = f"C:{B}Users{B}{name}{B}repo"
            self.assertEqual(matches(line), [], f"should not have fired: {line}")

    def test_placeholder_survives_trailing_sentence_punctuation(self):
        # Prose ending a sentence with a path must still see the placeholder.
        self.assertEqual(matches("runners live at /home/runner."), [])

    def test_http_scheme_is_not_a_drive_letter(self):
        # "p://" inside "http://" must not read as a drive-absolute path.
        for line in ("see http://example.com/a/b", "see https://x.io/a/b"):
            self.assertEqual(matches(line), [], line)

    def test_backslash_escape_is_not_a_drive_path(self):
        self.assertEqual(matches(r"print('done:\n' + x)"), [])


class TestOtherAbsolutePaths(unittest.TestCase):
    def test_drive_absolute_path_fires(self):
        hits = matches(f"note = D:{B}workspace{B}acme-holdings{B}notes.md")
        self.assertTrue(hits)

    def test_drive_absolute_report_omits_the_private_segment(self):
        # The guard's output lands in public CI logs, so it reports the shape
        # prefix rather than echoing the whole path.
        hits = matches(f"note = D:{B}workspace{B}acme-holdings{B}notes.md")
        self.assertNotIn("acme-holdings", " ".join(hits))

    def test_posix_home_fires(self):
        self.assertTrue(matches("cfg = /home/jdoe/projects/x"))
        self.assertTrue(matches("mac = /Users/jdoe/projects/x"))

    def test_posix_home_placeholders_do_not_fire(self):
        for line in ("/home/<user>/x", "/home/runner/work/repo", "/Users/alice/x"):
            self.assertEqual(matches(line), [], line)

    def test_lowercase_users_rest_route_does_not_fire(self):
        # /users/{id} is an API route, not a macOS home directory.
        self.assertEqual(matches("GET /users/{id} from the API"), [])

    def test_wsl_mount_fires_only_for_a_drive_letter(self):
        self.assertTrue(matches("wsl = /mnt/c/"))
        self.assertEqual(matches("vol = /mnt/data/volume"), [])


class TestRepoOrg(unittest.TestCase):
    def test_wrong_org_fires(self):
        for line in (
            "https://github.com/someoneelse/mesmer-grimoire",
            "git@github.com:someoneelse/mesmer-grimoire.git",
        ):
            self.assertTrue(matches(line), line)

    def test_retired_slug_fires_even_under_the_canonical_org(self):
        for slug in ci.RETIRED_SLUGS:
            for line in (
                f"https://github.com/{ci.CANONICAL_ORG}/{slug}/tree/main/grimoire",
                f"git clone https://github.com/{ci.CANONICAL_ORG}/{slug}.git",
            ):
                self.assertTrue(matches(line), line)

    def test_slug_prefix_of_another_repo_does_not_fire(self):
        line = f"https://github.com/psf/{ci.REPO_SLUG}-extras"
        self.assertEqual(matches(line), [])

    def test_canonical_org_does_not_fire(self):
        self.assertEqual(matches(f"https://github.com/{ci.CANONICAL_ORG}/{ci.REPO_SLUG}"), [])

    def test_other_repos_under_other_orgs_are_not_our_business(self):
        self.assertEqual(matches("https://github.com/psf/requests"), [])


class TestEmail(unittest.TestCase):
    def test_unknown_address_fires(self):
        self.assertTrue(matches("who = someone.else@contoso.co"))

    def test_allowlist_suppresses_the_attribution_line(self):
        # The real author line from the packages' pyproject.toml: the allowlist
        # must exonerate it, because "scrub the machine, keep the author".
        allowed = sorted(ci.ALLOWED_EMAILS)[0]
        line = f'authors = [{{ name = "Ceryce Armstrong", email = "{allowed}" }}]'
        self.assertEqual(matches(line), [])

    def test_allowlist_is_address_specific_not_a_blanket_pass(self):
        # Same shape, same file, different address -> still caught.
        line = 'authors = [{ name = "Someone Else", email = "someone@contoso.co" }]'
        self.assertTrue(matches(line))

    def test_scp_style_git_remote_is_not_an_email(self):
        self.assertEqual(matches("url = git@github.com:org/team-memory.git"), [])

    def test_reserved_example_domains_do_not_fire(self):
        self.assertEqual(matches("contact someone@example.com"), [])


class TestFileScanning(unittest.TestCase):
    def test_clean_file_yields_no_hits(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "clean.md"
            p.write_text("A repo-relative path: scripts/check_identifiers.py\n", "utf-8")
            self.assertEqual(ci.scan_file(p, "clean.md"), [])

    def test_dirty_file_reports_path_and_line_number(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "dirty.md"
            p.write_text(f"first line\nsecond\nC:{B}Users{B}jdoe{B}x\n", "utf-8")
            hits = ci.scan_file(p, "dirty.md")
            self.assertEqual(len(hits), 1)
            self.assertIn("dirty.md:3:", hits[0])

    def test_undecodable_file_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "blob.bin"
            p.write_bytes(b"\xff\xfe\x00binary\xff")
            self.assertEqual(ci.scan_file(p, "blob.bin"), [])

    def test_main_exits_zero_on_a_clean_tree(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "clean.md"
            p.write_text("nothing to see here\n", "utf-8")
            self.assertEqual(run_main([str(p)]), 0)

    def test_main_exits_one_when_something_matched(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "dirty.md"
            p.write_text(f"C:{B}Users{B}jdoe{B}x\n", "utf-8")
            self.assertEqual(run_main([str(p)]), 1)


class TestGuardScansItself(unittest.TestCase):
    def test_the_guard_source_is_clean(self):
        # The guard's own docs must obey the guard's own rules.
        src = pathlib.Path(ci.__file__).resolve()
        self.assertEqual(ci.scan_file(src, "check_identifiers.py"), [])


if __name__ == "__main__":
    unittest.main()
