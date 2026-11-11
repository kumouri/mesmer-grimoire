#!/usr/bin/env python3
"""Read plain JSP + scriptlets/JSTL + servlets, no framework, for the
`webapp-target-plain-jsp-servlets` reader (see `docs/webapp-modernization.md`) — ranked target 3,
"the most rule-dense case: business logic routinely lives inline in the page." Also the canonical
reader for raw `HttpSession` usage (`session.getAttribute`/`setAttribute`), which isn't specific to
this target: `struts-reader.py` and `spring-mvc-jsp-reader.py` recover their own frameworks'
session mechanisms (ActionForm scope, `@SessionAttributes`); this construct is what a JSP scriptlet,
a plain servlet, *or* a Struts Action/Spring controller falls back to when it isn't going through
either framework's session sugar, so the scan lives in `_session_state.py` and every reader can use
it.

Recovers, each as a rule-ledger-shaped row cited to `file:line`:

- **`web.xml` `<servlet>`/`<servlet-mapping>`** — route (`url-pattern`) to servlet class,
  `kind: orchestration`.
- **`web.xml` `<security-constraint>`** — `<url-pattern>` + `<role-name>` pairs, the container-
  managed authz Struts/Spring MVC don't own here, `kind: validation`.
- **`web.xml` `<session-config><session-timeout>`** — the session lifetime contract,
  `kind: orchestration`.
- **JSP scriptlets (`<% ... %>`)** containing a conditional, loop, or JDBC call — business logic
  living inline in the page, exactly the risk this target ranks worst for, `kind: calculation`,
  `confidence: Medium` (a scriptlet's *presence* of logic is certain; its exact behaviour needs
  the block itself read, by the agent, with the same discipline `recover-business-rules` asks for).
- **JSTL `<c:if test="...">` / `<c:choose>`** — conditional view logic, `kind: validation`,
  `confidence: Medium`.
- **`session.getAttribute`/`setAttribute`** (shared scan, `_session_state.py`) — one row per
  attribute name, citing every read and write site found in the file, `destination: unclassified`
  until classified per `docs/webapp-modernization.md`'s SESSION STATE -> STATELESS design.

Exit codes: 0 read the source, findings printed (empty is a valid finding) · 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import UsageError, find_repo_root, rel  # noqa: E402
from _routes import Route, write_routes  # noqa: E402
from _session_state import SessionAttribute, scan_http_session_usage, write_session_ledger  # noqa: E402

ATTR_RE = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')
# lookahead, not \b: "servlet" is immediately followed by "-" in "<servlet-mapping>", which is a
# \w/\W boundary and would otherwise false-match that (and any other "servlet-*") element.
SERVLET_TAG_RE = re.compile(r'<servlet(?=[\s/>])([^>]*?)>(?P<body>.*?)</servlet>', re.I | re.S)
SERVLET_MAPPING_RE = re.compile(r'<servlet-mapping\b[^>]*>(?P<body>.*?)</servlet-mapping>', re.I | re.S)
SERVLET_NAME_RE = re.compile(r'<servlet-name>\s*([^<]+?)\s*</servlet-name>', re.I)
SERVLET_CLASS_RE = re.compile(r'<servlet-class>\s*([^<]+?)\s*</servlet-class>', re.I)
URL_PATTERN_RE = re.compile(r'<url-pattern>\s*([^<]+?)\s*</url-pattern>', re.I)
SECURITY_CONSTRAINT_RE = re.compile(r'<security-constraint\b[^>]*>(?P<body>.*?)</security-constraint>',
                                    re.I | re.S)
ROLE_NAME_RE = re.compile(r'<role-name>\s*([^<]+?)\s*</role-name>', re.I)
SESSION_TIMEOUT_RE = re.compile(r'<session-timeout>\s*([^<]+?)\s*</session-timeout>', re.I)
SCRIPTLET_RE = re.compile(r'<%(?!@|--)(?P<body>.*?)%>', re.S)
LOGIC_KEYWORD_RE = re.compile(r'\b(if|for|while|switch)\s*\(|\.executeQuery\(|\.executeUpdate\(', re.I)
JSTL_IF_RE = re.compile(r'<c:if\s+test\s*=\s*"(?P<test>[^"]*)"', re.I)
JSTL_CHOOSE_RE = re.compile(r'<c:choose\b', re.I)


@dataclass
class Rule:
    id: str
    rule: str
    kind: str
    where: str
    confidence: str
    why: str


def line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def parse_attrs(raw: str) -> dict[str, str]:
    return dict(ATTR_RE.findall(raw))


def read_web_xml(text: str, display: str) -> tuple[list[Rule], list[Route]]:
    rules: list[Rule] = []
    routes: list[Route] = []
    names_to_class: dict[str, str] = {}
    for m in SERVLET_TAG_RE.finditer(text):
        body = m.group("body")
        nm = SERVLET_NAME_RE.search(body)
        cm = SERVLET_CLASS_RE.search(body)
        if nm and cm:
            names_to_class[nm.group(1)] = cm.group(1)
    for m in SERVLET_MAPPING_RE.finditer(text):
        body = m.group("body")
        nm = SERVLET_NAME_RE.search(body)
        um = URL_PATTERN_RE.search(body)
        if not (nm and um):
            continue
        lineno = line_of(text, m.start())
        where = f"{display}:{lineno}"
        name, pattern = nm.group(1), um.group(1)
        klass = names_to_class.get(name, "?")
        rules.append(Rule(id=f"ROUTE-{lineno}", rule=f"route {pattern!r} -> servlet {name!r} ({klass})",
                          kind="orchestration", where=where, confidence="High",
                          why="explicit <servlet-mapping>/<servlet> pair"))
        routes.append(Route(id=pattern, path=pattern, method="", where=where))
    for m in SECURITY_CONSTRAINT_RE.finditer(text):
        body = m.group("body")
        patterns = URL_PATTERN_RE.findall(body)
        roles = ROLE_NAME_RE.findall(body)
        lineno = line_of(text, m.start())
        rules.append(Rule(id=f"AUTHZ-{lineno}",
                          rule=f"URL pattern(s) {', '.join(patterns) or '?'} require role(s): "
                               f"{', '.join(roles) or '(none named -- constraint present)'}",
                          kind="validation", where=f"{display}:{lineno}", confidence="High",
                          why="explicit <security-constraint>"))
    for m in SESSION_TIMEOUT_RE.finditer(text):
        lineno = line_of(text, m.start())
        rules.append(Rule(id=f"TIMEOUT-{lineno}", rule=f"session timeout: {m.group(1)} minute(s)",
                          kind="orchestration", where=f"{display}:{lineno}", confidence="High",
                          why="explicit <session-timeout>"))
    return rules, routes


def read_jsp(text: str, display: str) -> list[Rule]:
    rules = []
    for m in SCRIPTLET_RE.finditer(text):
        body = m.group("body")
        if not LOGIC_KEYWORD_RE.search(body):
            continue
        lineno = line_of(text, m.start())
        rules.append(Rule(id=f"SCRIPTLET-{lineno}",
                          rule="scriptlet contains conditional/loop/JDBC logic inline in the page",
                          kind="calculation", where=f"{display}:{lineno}", confidence="Medium",
                          why="a control-flow keyword or JDBC call found inside <% %>; read the "
                              "block itself (recover-business-rules) for its exact behaviour"))
    for m in JSTL_IF_RE.finditer(text):
        lineno = line_of(text, m.start())
        rules.append(Rule(id=f"JSTL-{lineno}", rule=f"<c:if test=\"{m.group('test')}\"> gates page content",
                          kind="validation", where=f"{display}:{lineno}", confidence="Medium",
                          why="explicit JSTL conditional"))
    for m in JSTL_CHOOSE_RE.finditer(text):
        lineno = line_of(text, m.start())
        rules.append(Rule(id=f"JSTL-{lineno}", rule="<c:choose> branches page content",
                          kind="validation", where=f"{display}:{lineno}", confidence="Medium",
                          why="explicit JSTL multi-way conditional"))
    return rules


def session_state_rules(session_attrs: list[SessionAttribute]) -> list[Rule]:
    rules = []
    for sa in session_attrs:
        cites = sa.writtenBy + sa.readBy
        where = cites[0] if cites else "?"
        rid_suffix = where.rsplit(":", 1)[-1] if ":" in where else sa.name
        rules.append(Rule(
            id=f"SESSTATE-{rid_suffix}",
            rule=f"session attribute {sa.name!r} written at "
                 f"{', '.join(sa.writtenBy) or '(never in this file)'}, read at "
                 f"{', '.join(sa.readBy) or '(never in this file)'} — citable under the "
                 "constitution's Session / state section",
            kind="orchestration", where=where, confidence="High",
            why="explicit session.getAttribute/setAttribute call(s)"))
    return rules


def read_file(path: Path, display: str) -> tuple[list[Rule], list[SessionAttribute], list[Route]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    suffix = path.suffix.lower()
    rules: list[Rule] = []
    routes: list[Route] = []
    if suffix == ".xml":
        rules, routes = read_web_xml(text, display)
    elif suffix in (".jsp", ".jspx"):
        rules = read_jsp(text, display)
    session_attrs = scan_http_session_usage(text, display)
    rules += session_state_rules(session_attrs)
    return rules, session_attrs, routes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="jsp-servlet-reader",
                                description="Recover route, authz, scriptlet/JSTL and raw-"
                                            "HttpSession rules from web.xml and plain JSP/servlet "
                                            "source.")
    p.add_argument("--repo", help="repository root, for display only (default: nearest .git "
                                  "ancestor of cwd)")
    p.add_argument("sources", nargs="+", help="web.xml and/or .jsp/.jspx/.java source file(s)")
    p.add_argument("--unit", default=None, help="unit name for the session-state ledger (default: "
                                                "the first source file's name)")
    p.add_argument("--out", help="write the rule ledger as JSON to this path")
    p.add_argument("--session-out", help="write the session-state ledger as JSON to this path")
    p.add_argument("--routes-out", help="write the route manifest as JSON to this path")
    args = p.parse_args(argv)
    try:
        repo = Path(args.repo).resolve() if args.repo else find_repo_root()
        all_rules: list[Rule] = []
        all_session: list[SessionAttribute] = []
        all_routes: list[Route] = []
        for s in args.sources:
            path = Path(s)
            if not path.is_file():
                raise UsageError(f"no such file: {s}")
            display = rel(path.resolve(), repo)
            rules, session_attrs, routes = read_file(path, display)
            all_rules += rules
            all_session += session_attrs
            all_routes += routes

        print(f"{len(all_rules)} rule(s), {len(all_session)} session attribute(s), "
              f"{len(all_routes)} route(s) recovered from {len(args.sources)} source file(s)")
        for r in all_rules:
            print(f"  [{r.id}] {r.rule} ({r.where}, confidence: {r.confidence})")
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
                json.dump({"rules": [asdict(r) for r in all_rules]}, fh, indent=2)
                fh.write("\n")
            print(f"wrote {rel(out_path, repo)}")
        if args.session_out and all_session:
            unit = args.unit or Path(args.sources[0]).name
            write_session_ledger(Path(args.session_out), unit, all_session)
            print(f"wrote {rel(Path(args.session_out), repo)}")
        if args.routes_out:
            write_routes(Path(args.routes_out), all_routes)
            print(f"wrote {rel(Path(args.routes_out), repo)}")
        return 0
    except UsageError as exc:
        print(f"jsp-servlet-reader: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
