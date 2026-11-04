"""Read a spec's *Gate remediation* section: the plan's answer about gates it leaves red.

A local gate (SonarQube, a linter, a type check, anything in ``gates.steps``) must be green before a
phase pushes. A plan that schedules a *later* phase to remediate something a gate checks would
otherwise leave phase 0 unable to push. So the spec carries a ``## Gate remediation`` section, and
the person signs it off with the plan, choosing one ruling per gate:

* ``push-red``        push with that gate red, because its remediation is scheduled (the only
                      ruling that waives a red gate; ``run-local-gates`` honours it)
* ``limited-phase-0`` phase 0 makes the gate pass with the smallest remediation that does
* ``reorder``         the phases were reordered so the gate passes from phase 0 on
* ``other: <text>``   an equivalent the plan names; it waives nothing, the gate still has to pass

The section is either ``None — …`` (no phase remediates anything a gate checks) or a table::

    | Gate | Remediation phase | Ruling | Approved |
    |---|---|---|---|
    | sonarqube | Phase 2 | push-red | yes — Ceryce, 2026-11-05 |

``Approved`` is ``PENDING`` until the person answers, then ``yes`` plus who and when. Stdlib only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

RULINGS = ("push-red", "limited-phase-0", "reorder", "other")
ACTIVE_STATUSES = ("SIGNED-OFF", "PARTIAL")
SECTION_RE = re.compile(r"^##\s+Gate remediation\s*$", re.IGNORECASE | re.MULTILINE)
STATUS_RE = re.compile(r"\*\*Status:\*\*\s*`?([A-Za-z-]+)")
# A phase row that reads like remediation of something a gate checks.
REMEDIATION_RE = re.compile(
    r"(?i)\bremediat\w*|\b(?:clear|fix|resolve|address)\w*\s+(?:the\s+|all\s+|remaining\s+)?"
    r"(?:\w+\s+)?(?:findings|issues|violations|warnings|smells|hotspots)\b")


@dataclass
class Ruling:
    gate: str
    phase: str
    kind: str          # one of RULINGS, or "" when unreadable
    detail: str        # text after "other:" (or the raw cell when unreadable)
    approved: bool
    spec: str          # spec path as given

    @property
    def waives(self) -> bool:
        return self.kind == "push-red" and self.approved


def status_of(text: str) -> str:
    m = STATUS_RE.search(text)
    return m.group(1).upper() if m else ""


def section(text: str, heading: str) -> str:
    """The body under ``## heading`` up to the next ``##``; ``""`` if the heading is absent."""
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$", text, re.IGNORECASE | re.MULTILINE)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^##\s", rest, re.MULTILINE)
    return rest[:nxt.start()] if nxt else rest


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_kind(cell: str) -> tuple[str, str]:
    cell = cell.strip().strip("`").strip()
    low = cell.lower()
    for kind in RULINGS:
        if low == kind or low.startswith(kind + ":"):
            return kind, cell[len(kind):].lstrip(": ").strip()
    return "", cell


def parse(text: str, spec: str = "") -> tuple[list[Ruling], bool, bool]:
    """``(rulings, has_section, says_none)`` for a spec's text."""
    body = section(text, "Gate remediation")
    if not SECTION_RE.search(text):
        return [], False, False
    rows: list[Ruling] = []
    header_seen = False
    for line in body.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = _cells(line)
        if not header_seen:
            header_seen = True       # header row
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue                 # separator row
        if len(cells) < 4 or not cells[0] or cells[0] == "…":
            continue                 # template placeholder or malformed
        kind, detail = parse_kind(cells[2])
        rows.append(Ruling(cells[0].strip("`").strip(), cells[1], kind, detail,
                           cells[3].lower().startswith("yes"), spec))
    first = next((ln.strip() for ln in body.splitlines() if ln.strip() and not ln.lstrip().startswith(">")), "")
    return rows, True, first.lower().startswith("none")


def remediation_phase_rows(text: str) -> list[str]:
    """Phase-table rows that read like remediation of what a gate checks."""
    out = []
    for line in section(text, "Phases").splitlines():
        if line.strip().startswith("|") and REMEDIATION_RE.search(line) and not set(line) <= set("|-: "):
            out.append(line.strip())
    return out


def active_rulings(repo: Path, spec_dir: str) -> dict[str, Ruling]:
    """Rulings from every signed-off (or partly built) spec, keyed by lower-cased gate name.

    A waiver wins over a non-waiving ruling for the same gate only if it is approved; the first
    approved ``push-red`` found is kept, else the last ruling seen.
    """
    found: dict[str, Ruling] = {}
    folder = repo / spec_dir
    if not folder.is_dir():
        return found
    for path in sorted(folder.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not status_of(text).startswith(ACTIVE_STATUSES):
            continue
        rows, _, _ = parse(text, path.relative_to(repo).as_posix())
        for r in rows:
            key = r.gate.lower()
            if key not in found or (r.waives and not found[key].waives):
                found[key] = r
    return found
