"""Signal detectors for the lessons-capture hooks (stdlib only; no git, no network, no model).

Phase 0 matched bare keywords, and a month of shadow data showed that was noise: the bare words
*never* and *always* (S4), *do not* / *don't* / *instead* anywhere in a prompt (S5), and any
command that failed and then passed (S6) mostly fired on standing agent instructions, task briefs
and watchdog kills, not on a person teaching the agent something (docs/lessons-capture-spec.md,
§5.1 and §5.2). These detectors are the tightened shape the spec asks for:

S4 (explicit-remember)  A directive in the user's own words: ``remember to|that|this``, ``from now
        on``, or ``always|never`` followed by a verb, where the word opens its clause (an imperative),
        not one buried in a sentence about something else.
S5 (correction)         ``no,`` opening the prompt, ``that's wrong``, a clause that opens with
        ``don't|do not`` and a verb, or an imperative verb with ``instead`` in the same clause.
Neither fires inside a **brief** (a long or structured prompt: a task brief, a pasted document, a
quoted instruction file), and the engine also drops a clause it has already seen in this project,
because a standing rule re-fires in every session (`candidates.instruction_repeat`).
S6 (fail-then-succeed)  Not a watchdog kill, not navigation or a plain read, not a heredoc or
        quoting retry, and not the same command run again unchanged (`s6_exclusion`).

Every rule here is a pattern or a short word list, so a decision is explainable and a false
positive can be traced to its rule. None of it reads a transcript or calls a model.
"""
from __future__ import annotations

import re

BRIEF_CHARS = 1200   # a prompt longer than this is a brief or a pasted document, not a direct instruction
BRIEF_LINES = 4      # this many list / heading / numbered lines make a prompt a structured document

# Words that may sit before an imperative without making it part of something else's sentence.
_LEAD = (r"(?:please|and|but|also|so|ok|okay|yes|no|now|then|just|hey|btw|actually|oh|wait|hmm|"
         r"going forward|next time|from now on|you (?:must|should|need to|have to|will)|"
         r"make sure (?:you|to)|be sure to)")
_LEAD_RE = re.compile(rf"^(?:{_LEAD}\b[\s,:;\-]*)*$", re.I)
_BOUNDARY = re.compile(r"[.!?;:\n]")

# After "always" / "never" a verb follows when it is a directive. These are the words that mean it
# is a statement instead ("it never worked", "we always did", "never again" read as prose).
_NOT_A_VERB = frozenset(
    "is are was were be been being am has have had having do does did will would can could should "
    "shall may might must the a an i we you it they he she this that these those there here in on at "
    "of for with to from by as if when while again ever mind more less".split())
# After "don't" a correction names the wrong action. These openings are chat, not correction.
_NOT_A_CORRECTION = frozenset(
    "you worry think know mind see say really understand need want have forget get".split())
# An imperative verb in the same clause as "instead" ("use X instead").
_IMPERATIVES = frozenset(
    "use do try make put call run write name go keep switch change replace prefer add remove move "
    "rename read check ask say send show take pick choose set".split())

_REMEMBER = re.compile(r"\bremember\s*(?:to\b|that\b|this\b|:|,)", re.I)
_FROM_NOW_ON = re.compile(r"\bfrom now on\b", re.I)
_ALWAYS_NEVER = re.compile(r"\b(always|never)\s+([a-z][a-z'’-]*)", re.I)
_NO_OPENER = re.compile(r"^\s*no\s*[,.!]", re.I)
_THATS_WRONG = re.compile(r"\bthat(?:['’]s| is) (?:wrong|not right|incorrect)\b", re.I)
_DONT = re.compile(r"\b(?:don['’]?t|do not)\s+([a-z][a-z'’-]*)", re.I)
_INSTEAD = re.compile(r"\binstead\b", re.I)
_LISTISH = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|#{1,6}\s|>\s|\|)")
_WRAPPER = re.compile(r"^\s*<[a-z][a-z0-9_-]*[ >]", re.I)


def looks_like_brief(prompt: str) -> bool:
    """A task brief, a pasted document or a quoted instruction file: not one person's direct words.
    Long, or structured (many list / heading lines, a fenced block), or opening with a markup tag."""
    text = prompt or ""
    if len(text) > BRIEF_CHARS or "```" in text or _WRAPPER.match(text):
        return True
    return sum(1 for ln in text.splitlines() if _LISTISH.match(ln)) >= BRIEF_LINES


def clause_start(text: str, pos: int) -> int:
    """Index where the clause containing `pos` begins: just after the previous . ! ? ; : or newline."""
    start = 0
    for m in _BOUNDARY.finditer(text, 0, pos):
        start = m.end()
    return start


def clause_end(text: str, pos: int, limit: int = 240) -> int:
    m = _BOUNDARY.search(text, pos, min(len(text), pos + limit))
    return m.start() if m else min(len(text), pos + limit)


def opens_clause(text: str, pos: int) -> bool:
    """True when only lead-in words sit between the clause start and `pos`."""
    return bool(_LEAD_RE.match(text[clause_start(text, pos):pos].strip()))


def _norm(clause: str) -> str:
    return " ".join(clause.split()).casefold()


def s4_matches(text: str) -> list:
    """[(matched phrase, start, end)] for each S4 directive in `text`, in order."""
    out = []
    for m in _FROM_NOW_ON.finditer(text):
        out.append((m.group(0), m.start(), m.end()))
    for m in _REMEMBER.finditer(text):
        if opens_clause(text, m.start()):
            out.append((m.group(0).strip(), m.start(), m.end()))
    for m in _ALWAYS_NEVER.finditer(text):
        if m.group(2).casefold() not in _NOT_A_VERB and opens_clause(text, m.start()):
            out.append((m.group(1), m.start(), m.end()))
    return sorted(out, key=lambda t: t[1])


def s5_matches(text: str) -> list:
    out = []
    m = _NO_OPENER.match(text)
    if m:
        out.append((m.group(0).strip(), m.start(), m.end()))
    for m in _THATS_WRONG.finditer(text):
        out.append((m.group(0), m.start(), m.end()))
    for m in _DONT.finditer(text):
        if m.group(1).casefold() not in _NOT_A_CORRECTION and opens_clause(text, m.start()):
            out.append((m.group(0), m.start(), m.end()))
    for m in _INSTEAD.finditer(text):
        cs = clause_start(text, m.start())
        words = re.findall(r"[a-z]+", text[cs:m.start()].casefold())
        if words:
            lead = [w for w in words if not _LEAD_RE.match(w)]
            if lead and lead[0] in _IMPERATIVES:
                out.append((m.group(0), m.start(), m.end()))
    return sorted(out, key=lambda t: t[1])


def standing_clause(text: str, start: int) -> str:
    """The normalized clause a match opens, used to recognise the same instruction in a later session."""
    return _norm(text[clause_start(text, start):clause_end(text, start)])


# --------------------------------------------------------------------------------------- S6

WATCHDOG_EXITS = frozenset({124, 130, 137, 143})   # timeout, interrupt, killed, terminated
NAVIGATION = frozenset(
    "cd ls dir pwd sleep set-location push-location pop-location pushd popd which where test echo "
    "true false cat head tail type get-content get-childitem get-location select-string grep "
    "find stat file wc".split())
_PARSE_ERROR = re.compile(
    r"unexpected EOF|syntax error|unterminated|unexpected token|ParserError|MissingEndParenthesis|"
    r"TerminatorExpectedAtEndOfString|missing file specification", re.I)
_HEREDOC = re.compile(r"<<-?\s*['\"]?\w|@['\"]\s*$", re.M)


def program_of(head: str) -> str:
    first = (head or "").split(" ")[0].casefold()
    return first[:-4] if first.endswith(".exe") else first


def s6_exclusion(head: str, exit_code, command: str = "", error_text: str = ""):
    """Why a failure must not become an S6 candidate, or None when it may. The reason is a short
    word that the decision log records."""
    if exit_code in WATCHDOG_EXITS:
        return "watchdog"
    if program_of(head) in NAVIGATION:
        return "navigation"
    if _HEREDOC.search(command or ""):
        return "heredoc"
    if _PARSE_ERROR.search(error_text or ""):
        return "quoting"
    return None
