"""Shared helpers for the Zethus scripts: repo root, config, slugs, templates.

Stdlib only. The scripts are installed as a set — into ``.github/zethus/scripts/`` in a consuming
repo, or ``~/.copilot/zethus/scripts/`` for a user-level install — so each one imports this module
from its own directory.

Config resolution mirrors Amphion's: the project's own answer first, then the user's defaults,
then repository evidence, then ask. The first file found wins (``--config`` beats all of them):

1. ``.github/zethus.config.json`` — committed, shared with the team.
2. ``$ZETHUS_CONFIG`` — a path (relative paths are taken from the repo root).
3. ``.copilot/zethus.config.json`` — per-repo but untracked: for repos whose ``.github/`` you may
   not change. Keep it out of git with ``.git/info/exclude``, not ``.gitignore``.
4. ``.claude/amphion.config.json`` — Amphion's config; the key names match wherever they overlap
   (``gates``, ``branchModel``, ``docSync``) — one project, one set of answers.
5. ``~/.copilot/zethus/config.json`` — the user's defaults for every repo.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
from pathlib import Path

KIT_DIR = Path(__file__).resolve().parent.parent   # .../zethus, .github/zethus or ~/.copilot/zethus
TEMPLATES_DIR = KIT_DIR / "templates"

CONFIG_ENV = "ZETHUS_CONFIG"


def user_home() -> Path:
    """The user-level Zethus home: ``~/.copilot/zethus``. It is where Copilot's user files live."""
    return Path.home() / ".copilot" / "zethus"


def config_candidates(repo: Path) -> list[Path]:
    """Every place a config may live, in resolution order (see the module docstring)."""
    paths = [repo / ".github" / "zethus.config.json"]
    env = os.environ.get(CONFIG_ENV, "").strip()
    if env:
        paths.append(Path(env) if Path(env).is_absolute() else repo / env)
    paths += [repo / ".copilot" / "zethus.config.json",
              repo / ".claude" / "amphion.config.json",
              user_home() / "config.json"]
    return paths

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class UsageError(Exception):
    """A problem the user must fix; printed without a traceback, exit code 2."""


def find_repo_root(start: Path | None = None) -> Path:
    """Nearest ancestor holding ``.git`` (a dir, or a file in a worktree); else ``start``."""
    here = Path(start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return here


def load_config(repo: Path, explicit: str | None = None) -> tuple[dict, Path | None]:
    """Return ``(config, path)``. No config is a valid answer: ``({}, None)``."""
    if explicit:
        paths = [Path(explicit) if Path(explicit).is_absolute() else repo / explicit]
        if not paths[0].is_file():
            raise UsageError(f"config not found: {explicit}")
    else:
        paths = config_candidates(repo)
    for path in paths:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise UsageError(f"{rel(path, repo)} is not valid JSON: {exc}") from exc
            if not isinstance(data, dict):
                raise UsageError(f"{rel(path, repo)} must hold a JSON object")
            return data, path
    return {}, None


def cfg(config: dict, dotted: str, default=None):
    """Read ``a.b.c`` from nested dicts, returning ``default`` for any missing hop."""
    node = config
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def slugify(title: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    slug = slug[:max_len].rstrip("-")
    if not slug:
        raise UsageError(f"title {title!r} has no letters or digits to build a file name from")
    return slug


def today() -> str:
    return _dt.date.today().isoformat()


def check_date(value: str) -> str:
    if not DATE_RE.match(value):
        raise UsageError(f"date must be YYYY-MM-DD, got {value!r}")
    try:
        _dt.date.fromisoformat(value)
    except ValueError as exc:
        raise UsageError(f"not a real date: {value}") from exc
    return value


def fill(template: str, values: dict[str, str]) -> str:
    """Substitute ``{{key}}`` placeholders. Unknown placeholders are left for the author."""
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def read_template(name: str, override: str | None, repo: Path) -> str:
    path = Path(override) if override else TEMPLATES_DIR / name
    if override and not path.is_absolute():
        path = repo / path
    if not path.is_file():
        raise UsageError(f"template not found: {path.name} (looked in {rel(path.parent, repo)})")
    return path.read_text(encoding="utf-8")


def rel(path: Path, repo: Path) -> str:
    """Repo-relative POSIX path for display; never print an absolute host path we can avoid."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(repo.resolve()).as_posix()
    except ValueError:
        pass
    try:
        return "~/" + resolved.relative_to(Path.home().resolve()).as_posix()
    except (ValueError, RuntimeError):
        return Path(path).as_posix()


def git(repo: Path, *args: str) -> subprocess.CompletedProcess | None:
    """Run git; ``None`` when git is missing. Never raises on a non-zero exit."""
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except (FileNotFoundError, OSError):
        return None


HLA_HINT_RE = re.compile(r"high[- ]level architecture|^\s*(?:default stored-procedure disposition"
                         r"|auth strategy)\s*:", re.I | re.M)


def hla_candidates(repo: Path, limit: int = 5) -> list[str]:
    """Tracked docs that look like a target HLA: its title, one of its required lines, or "hla" in
    the file name. An HLA check lists these so the agent finds the document itself before it asks.
    """
    proc = git(repo, "ls-files", "--", "*.md", "*.txt", "*.adoc")
    if proc is None or proc.returncode != 0:
        return []
    found = []
    for name in proc.stdout.splitlines():
        path = repo / name
        try:
            if path.stat().st_size > 1_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "hla" in path.stem.lower() or HLA_HINT_RE.search(text):
            found.append(name)
            if len(found) == limit:
                break
    return found


def hla_lookup(repo: Path, problem: str) -> str:
    """The next step when the configured HLA is missing: look in the repo first, then ask."""
    found = hla_candidates(repo)
    if found:
        return (f"{problem} The repo has HLA-looking docs: {', '.join(found)}. Read them; if one "
                "is the target HLA, set modernization.hlaDoc to it (or pass --hla) and re-run. Ask "
                "the person only if none of them is.")
    return (f"{problem} No tracked doc looks like an HLA (searched *.md, *.txt and *.adoc for "
            "'High-Level Architecture' and the required lines), so ask the person where it is, "
            "with the question tool. Not assuming a default.")


def write_new(path: Path, text: str) -> None:
    """Create ``path``; refuse to overwrite. Newlines are always LF."""
    if path.exists():
        raise UsageError(f"refusing to overwrite existing file: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
