"""CI coverage for the hook's spool index (docs/lessons-capture-spec.md §4.7, "Spool read cost").

`stop` and `session-start` read the candidate spool through an index kept beside it
(`memory/.capture/index.bin`), so a hook parses only what was appended since the last one. The index
is a cache and must never change an answer, so every test here compares the hook's read with the
full read (`_fold` and `untriaged`) on the same spool, across the cases that could break it:
appends, labels and resolutions, deletions, a truncated last line, a damaged or missing index, a
write that fails, and hooks racing each other and a writer.

Offline and temp-dir only. No timing assertion is made on a shared CI runner; what makes the read
cheap (no JSON parsed for the lines already indexed) is asserted by counting parses instead.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
MNEMOSYNE_SRC = REPO / "mnemosyne" / "src"
if str(MNEMOSYNE_SRC) not in sys.path:
    sys.path.insert(0, str(MNEMOSYNE_SRC))

from mnemosyne import candidates as cd  # noqa: E402

PROJECTS = ("alpha", "beta", "gamma")
BRANCHES = ("main", "feat/x")
SIGNALS = ("S1", "S2", "S4", "S5", "S6", "S8", "S9-S11", "S12")
CONFIGS = ({}, {"ask": {"signals": ["correction", "explicit-remember"]}}, {"ask": {"signals": ["S6"]}})


def make_rows(rnd: random.Random, n: int, start: int = 0) -> list:
    """Spool rows of every type a spool holds, including the awkward ones: duplicate ids, labels
    and resolutions that point at nothing, repeated fingerprints, ADR paths, and text that a naive
    line splitter would cut in two."""
    rows, ids = [], []
    for i in range(start, start + n):
        r = rnd.random()
        if r < 0.62 or not ids:
            cid = rnd.choice(ids) if ids and rnd.random() < 0.03 else f"C-{i:06d}"
            ids.append(cid)
            sig = rnd.choice(SIGNALS)
            # a raw U+2028 (json.dumps keeps it) is a line break to `str.splitlines`: such a row is torn
            ev = {"head": "git status", "excerpt": "line one\u2028line two" if rnd.random() < 0.03 else "caf\u00e9"}
            if sig in ("S1", "S9-S11"):
                ev.update(kind=rnd.choice(["adr", "spec", "friction", "ledger"]), path=f"docs/adr/{rnd.randrange(6)}.md")
            row = {"type": "candidate", "id": cid, "ts": "2026-11-01T10:00:00", "signal": sig,
                   "session": f"s{rnd.randrange(5)}",
                   "context": {"repo": rnd.choice(PROJECTS), "branch": rnd.choice(BRANCHES)},
                   "evidence": ev, "fp": f"fp{rnd.randrange(40)}" if rnd.random() < 0.7 else None}
            if rnd.random() < 0.85:
                row["det"] = rnd.choice([1, 2, 2, 2])
            rows.append(row)
        elif r < 0.78:
            rows.append({"type": "label", "id": rnd.choice(ids + ["C-nothing"]),
                         "verdict": rnd.choice(["lesson", "lesson", "noise", None]), "note": "n"})
        elif r < 0.95:
            rows.append({"type": "resolution", "id": rnd.choice(ids + ["C-nothing"]),
                         "as": rnd.choice(["stored", "skipped", "asked", "dropped"]), "lesson": "L-1"})
        elif r < 0.97:
            rows.append({"type": "mute", "kind": rnd.choice(["S5", "S6", "S9-S11:spec", "S9-S11:adr"])})
        else:
            rows.append({"type": "something-else", "id": rnd.choice(ids)})
    return rows


def dump(rows: list) -> bytes:
    return b"".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
                    for r in rows)


class SpoolCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        (self.root / "memory").mkdir()
        self.dir = cd.ensure_capture_dir(self.root)
        self.spool = self.dir / cd.CANDIDATES
        self.index = self.dir / cd.INDEX
        self.rnd = random.Random(20261124)

    def tearDown(self):
        self._td.cleanup()

    def write(self, rows):
        self.spool.write_bytes(dump(rows))

    def append_bytes(self, data: bytes):
        with open(self.spool, "ab") as fh:
            fh.write(data)

    def assertSameAsFullRead(self):
        """The hook's read equals the full read, in every number the hooks and `triage` take from it."""
        full, full_muted = cd._fold(self.root)
        rows, muted = cd._slim_fold(self.root)
        self.assertEqual(rows, [cd._row(c) for c in full])
        self.assertEqual(muted, full_muted)
        self.assertEqual(sum(1 for c in full if not c.get("verdict")), sum(1 for r in rows if not r[cd._VERDICT]))
        for project in (None, *PROJECTS, "nobody"):
            for branch in (None, *BRANCHES):
                for cfg in CONFIGS:
                    want = cd.untriaged(self.root, project=project, branch=branch, mem_cfg=cfg)
                    self.assertEqual(cd.untriaged_count(self.root, project, branch, cfg), len(want),
                                     (project, branch, cfg))
                    idx, counts, status = cd._pool_rows(rows, muted, cfg, project, branch)
                    _items, wcounts, wstatus = cd._triage_pool((full, full_muted), cfg, project, branch, self.root)
                    self.assertEqual((counts, status), (wcounts, wstatus))
                    self.assertEqual([full[i]["id"] for i in idx], [c["id"] for c in want])

    def parses(self, fn):
        """How many lines `fn` parsed as JSON."""
        real, calls = json.loads, []

        def counting(*a, **k):
            calls.append(1)
            return real(*a, **k)

        with mock.patch.object(cd.json, "loads", counting):
            fn()
        return len(calls)


class IndexMatchesFullRead(SpoolCase):
    def test_a_missing_spool_is_empty(self):
        self.assertEqual(cd._slim_fold(self.root), ([], set()))
        self.assertFalse(self.index.exists())
        self.assertEqual(cd.untriaged_count(self.root), 0)

    def test_first_read_builds_the_index_and_matches(self):
        self.write(make_rows(self.rnd, 600))
        self.assertSameAsFullRead()
        self.assertTrue(self.index.is_file())

    def test_appended_rows_labels_and_resolutions_fold_in(self):
        rows = make_rows(self.rnd, 400)
        self.write(rows)
        self.assertSameAsFullRead()
        for step in range(6):
            self.append_bytes(dump(make_rows(self.rnd, 40, start=1000 * (step + 1))))
            self.assertSameAsFullRead()

    def test_the_public_api_writes_are_seen(self):
        for sig in ("S4", "S8", "S9-S11"):
            cd.add_candidate(self.root, sig, session="s", context={"repo": "alpha", "branch": "main"},
                             evidence={"kind": "spec", "path": "docs/specs/a.md"}, fp_key=sig)
        self.assertSameAsFullRead()
        first = cd.candidates(self.root)[0]["id"]
        cd.label(self.root, first, "lesson")
        self.assertSameAsFullRead()
        cd.resolve(self.root, cd.candidates(self.root)[1]["id"], "skipped")
        self.assertSameAsFullRead()
        cd.resolve(self.root, cd.candidates(self.root)[2]["id"], "never")
        self.assertSameAsFullRead()

    def test_enough_labels_move_a_signal_out_of_shadow(self):
        rows = []
        for i in range(14):
            rows.append({"type": "candidate", "id": f"C-{i}", "signal": "S6", "det": 2, "session": "s",
                         "context": {"repo": "alpha", "branch": "main"}, "evidence": {}})
        self.write(rows)
        self.assertEqual(cd.untriaged_count(self.root, "alpha", "main"), 0)
        self.append_bytes(dump([{"type": "label", "id": f"C-{i}", "verdict": "lesson"} for i in range(12)]))
        self.assertEqual(cd.untriaged_count(self.root, "alpha", "main"), 14)
        self.assertSameAsFullRead()

    def test_a_warm_read_parses_nothing_and_a_tail_read_parses_only_the_tail(self):
        self.write(make_rows(self.rnd, 500))
        cd._slim_fold(self.root)
        self.assertEqual(self.parses(lambda: cd._slim_fold(self.root)), 0)
        tail = dump(make_rows(self.rnd, 7, start=9000))
        self.append_bytes(tail)
        self.assertEqual(self.parses(lambda: cd._slim_fold(self.root)), len(tail.decode("utf-8").splitlines()))
        self.assertEqual(self.parses(lambda: cd._slim_fold(self.root)), 0)

    def test_the_hook_decision_is_the_same_with_and_without_the_index(self):
        self.write(make_rows(self.rnd, 500))
        env = {"MNEMOSYNE_REPO": str(self.root)}
        ev = {"session_id": "s1", "cwd": str(self.root), "stop_hook_active": False}
        with_index = cd.capture_event("stop", ev, env=env, root=self.root)
        self.assertTrue(self.index.is_file())
        self.index.unlink()
        ev2 = dict(ev, session_id="s2")
        without = cd.capture_event("stop", ev2, env=env, root=self.root)
        for key in ("pending", "untriaged", "decision"):
            self.assertEqual(with_index[key], without[key], key)


class IndexNeverTrustedBlindly(SpoolCase):
    def test_a_shorter_spool_is_read_whole(self):
        rows = make_rows(self.rnd, 300)
        self.write(rows)
        self.assertSameAsFullRead()
        self.write(rows[:120])                       # archived or truncated
        self.assertSameAsFullRead()

    def test_a_deleted_early_line_is_noticed_even_after_the_spool_grows_back(self):
        rows = make_rows(self.rnd, 300)
        self.write(rows)
        self.assertSameAsFullRead()
        kept = rows[:5] + rows[6:]                   # one line deleted near the start
        self.write(kept + make_rows(self.rnd, 60, start=5000))   # and more appended: larger than before
        self.assertSameAsFullRead()

    def test_a_deleted_line_just_before_the_end_is_noticed(self):
        rows = make_rows(self.rnd, 300)
        self.write(rows)
        self.assertSameAsFullRead()
        self.write(rows[:-3] + make_rows(self.rnd, 40, start=7000))
        self.assertSameAsFullRead()

    def test_an_emptied_spool_is_empty(self):
        self.write(make_rows(self.rnd, 100))
        self.assertSameAsFullRead()
        self.spool.write_bytes(b"")
        self.assertEqual(cd._slim_fold(self.root), ([], set()))
        self.assertSameAsFullRead()

    def test_an_edit_that_keeps_the_size_is_noticed_by_the_modified_time(self):
        rows = make_rows(self.rnd, 200)
        self.write(rows)
        self.assertSameAsFullRead()
        data = bytearray(self.spool.read_bytes())
        at = data.index(b"fp", len(data) // 2)       # change one byte well inside the indexed bytes
        data[at + 2] = ord("9") if data[at + 2] != ord("9") else ord("8")
        self.spool.write_bytes(bytes(data))
        st = self.spool.stat()
        os.utime(self.spool, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        self.assertSameAsFullRead()

    def test_a_truncated_last_line_is_never_indexed_and_is_counted_once_when_it_completes(self):
        rows = make_rows(self.rnd, 200)
        self.write(rows)
        cd._slim_fold(self.root)
        indexed = self.index.read_bytes()
        whole = dump([{"type": "candidate", "id": "C-tail", "signal": "S8", "det": 2, "session": "s",
                       "context": {"repo": "alpha", "branch": "main"}, "evidence": {}}]).rstrip(b"\n")
        self.append_bytes(whole[:30])                # a hook died mid-write
        self.assertSameAsFullRead()
        self.assertEqual(self.index.read_bytes(), indexed)   # the partial line was not indexed
        self.append_bytes(whole[30:])                # the rest lands, still without its newline
        self.assertSameAsFullRead()
        self.assertEqual(self.index.read_bytes(), indexed)   # a valid line with no newline yet: counted, not indexed
        self.assertIn("C-tail", [r[cd._ID] for r in cd._slim_fold(self.root)[0]])
        self.append_bytes(b"\n")
        self.assertSameAsFullRead()
        ids = [r[cd._ID] for r in cd._slim_fold(self.root)[0]]
        self.assertEqual(ids.count("C-tail"), 1)
        self.assertSameAsFullRead()

    def test_a_label_in_an_unterminated_line_does_not_stick(self):
        self.write([{"type": "candidate", "id": "C-1", "signal": "S8", "session": "s",
                     "context": {"repo": "alpha", "branch": "main"}, "evidence": {}}])
        cd._slim_fold(self.root)
        self.append_bytes(b'{"type":"label","id":"C-1","verdict":"lesson"}')    # no newline
        self.assertEqual(cd._slim_fold(self.root)[0][0][cd._VERDICT], "lesson")
        self.spool.write_bytes(self.spool.read_bytes().rsplit(b"\n", 1)[0] + b"\n")  # the line is withdrawn
        self.assertEqual(cd._slim_fold(self.root)[0][0][cd._VERDICT], None)
        self.assertSameAsFullRead()

    def test_torn_and_foreign_lines_are_skipped_like_the_full_read_skips_them(self):
        self.write(make_rows(self.rnd, 80))
        self.append_bytes(b'{"type":"candidate","id":"C-torn","sig\n[1,2]\n\n"just a string"\n')
        self.append_bytes(b"\xff\xfe not utf-8 \n")
        self.append_bytes(dump(make_rows(self.rnd, 30, start=3000)))
        self.assertSameAsFullRead()
        self.append_bytes(dump(make_rows(self.rnd, 5, start=4000)))
        self.assertSameAsFullRead()


class DamagedOrMissingIndex(SpoolCase):
    def build(self):
        self.write(make_rows(self.rnd, 300))
        self.assertSameAsFullRead()
        self.assertTrue(self.index.is_file())

    def assertRebuilt(self):
        self.assertSameAsFullRead()
        good = self.index.read_bytes()
        self.assertEqual(self.parses(lambda: cd._slim_fold(self.root)), 0)   # valid again: nothing to parse
        self.assertEqual(self.index.read_bytes(), good)

    def test_a_deleted_index_is_rebuilt(self):
        self.build()
        self.index.unlink()
        self.assertRebuilt()

    def test_garbage_empty_and_truncated_indexes_are_rebuilt(self):
        self.build()
        good = self.index.read_bytes()
        for bad in (b"", b"not an index", good[:len(good) // 2], good[:20], b"\x00" * 200,
                    cd.INDEX_MAGIC + b"\x00" * 32 + b"junk"):
            self.index.write_bytes(bad)
            self.assertRebuilt()

    def test_a_flipped_byte_in_the_payload_is_caught_by_the_checksum(self):
        self.build()
        data = bytearray(self.index.read_bytes())
        data[len(data) // 2] ^= 0xFF
        self.index.write_bytes(bytes(data))
        with mock.patch.object(cd.marshal, "loads", side_effect=AssertionError("damaged payload reached marshal")):
            with open(self.spool, "rb") as fh:
                st = self.spool.stat()
                self.assertIsNone(cd._load_index(self.index, fh, st.st_size, st.st_mtime_ns))
        self.assertRebuilt()

    def test_an_index_from_another_version_is_rebuilt(self):
        self.build()
        with mock.patch.object(cd, "INDEX_VERSION", cd.INDEX_VERSION + 1):
            self.assertSameAsFullRead()          # rejects the old index and writes its own
        self.assertSameAsFullRead()              # and the real version rejects that one in turn

    def test_an_index_that_is_a_directory_fails_open(self):
        self.write(make_rows(self.rnd, 200))
        self.index.mkdir()
        self.assertSameAsFullRead()

    def test_a_failed_index_write_fails_open_and_leaves_no_temp_file(self):
        self.write(make_rows(self.rnd, 200))
        with mock.patch.object(cd.os, "replace", side_effect=PermissionError("held open")):
            self.assertSameAsFullRead()
        self.assertFalse(self.index.exists())
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")], [])
        self.assertSameAsFullRead()
        self.assertTrue(self.index.is_file())

    def test_a_reader_holding_the_index_open_does_not_break_a_hook(self):
        # On Windows this blocks the swap, so the writer must give up quietly; elsewhere it is harmless.
        self.build()
        self.append_bytes(dump(make_rows(self.rnd, 20, start=8000)))
        with open(self.index, "rb"):
            self.assertSameAsFullRead()
        self.assertSameAsFullRead()

    def test_a_crash_inside_the_indexed_read_falls_back_to_the_whole_read(self):
        self.build()
        with mock.patch.object(cd, "_indexed_fold", side_effect=RuntimeError("boom")):
            rows, muted = cd._slim_fold(self.root)
        full, full_muted = cd._fold(self.root)
        self.assertEqual((rows, muted), ([cd._row(c) for c in full], full_muted))


RACER = """
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from mnemosyne import candidates as cd
root = Path(sys.argv[2])
for _ in range(int(sys.argv[3])):
    rows, muted = cd._slim_fold(root)
    cd.untriaged_count(root, "alpha", "main", {})
"""


class ConcurrentHooks(SpoolCase):
    def test_hooks_racing_each_other_and_a_writer_never_fail_or_disagree(self):
        self.write(make_rows(self.rnd, 300))
        readers = [subprocess.Popen([sys.executable, "-I", "-c", RACER, str(MNEMOSYNE_SRC), str(self.root), "25"],
                                    stderr=subprocess.PIPE, text=True) for _ in range(4)]
        for i in range(60):
            cd.add_candidate(self.root, "S8", session="w", context={"repo": "alpha", "branch": "main"},
                             evidence={"n": i})
        for proc in readers:
            _out, err = proc.communicate(timeout=120)
            self.assertEqual((proc.returncode, err), (0, ""))
        self.assertSameAsFullRead()
        self.assertEqual(sum(1 for r in cd._slim_fold(self.root)[0] if r[cd._SESSION] == "w"), 60)
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")], [])


class SyntheticScale(SpoolCase):
    def test_a_spool_the_size_of_a_real_one_matches(self):
        self.write(make_rows(self.rnd, 13490))
        self.assertSameAsFullRead()
        self.assertEqual(self.parses(lambda: cd._slim_fold(self.root)), 0)


if __name__ == "__main__":
    unittest.main()
