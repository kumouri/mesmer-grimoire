#!/usr/bin/env python3
"""The grimoire installer: Zethus, Amphion, the shared core and Mnemosyne, for Claude Code and GitHub
Copilot, from one entry point.

    python install.py --platform all --user                   # every bundle, for your account
    python install.py --platform copilot --target path/to/repo --bundle zethus
    python install.py --platform claude --user --bundle amphion
    python install.py --platform all --user --dry-run          # the plan only; writes nothing
    python install.py --platform all --user --uninstall        # remove what it put there
    python install.py --check                                  # validate catalog.json, the core and the manifests
    python install.py --list                                   # the bundles, what each needs, which hosts
    python install.py --sync-core                              # rewrite the plugin folders' copies of core/

``catalog.json`` is the only list of what exists. The bundles, and what each installs:

    mnemosyne  delegate  mnemosyne/install.py: the package, a local memory repo, MNEMOSYNE_REPO, the Claude
                         plugin, and (Copilot) the capture hook files. Called, never copied.
    core       files     the shared core's skills (flag-or-fix, resume-interrupted-phase, pr-description)
                         into the host's skills folder. Needs mnemosyne, so the hooks come with it.
    amphion    files     Amphion's own skills, and in a repo ``.claude/amphion.config.json`` if absent.
                         Needs core.
    zethus     delegate  zethus/install.py (Copilot only; a Claude Code, Codex or Cursor port is stage 2).
                         Needs core.

``--bundle`` defaults to zethus and amphion, and so to what they need. Each bundle installs once however
many ask for it, and **each hook registers once**: only mnemosyne's installer writes hook registrations
(the Claude plugin, and with Copilot ``.github/hooks`` or ``~/.copilot/hooks``), and it is called once.

Where the skills go (``--user`` / ``--target``): Claude ``~/.claude/skills`` / ``.claude/skills``;
Copilot ``~/.copilot/skills`` / ``.github/skills``. The installer's own manifest records each file it
wrote and its SHA-256: ``~/.mesmer-grimoire/install-manifest.json`` / ``<repo>/.mesmer-grimoire/``
(repo-relative paths, so a committed manifest names no machine). Zethus and Mnemosyne keep their own
manifests where they always did; this one never lists their files, so an older Zethus installer re-run
over this one sees nothing of the core's and leaves it alone.

**Safe by construction.** The whole run is planned first, and a delegate's installer is rehearsed with
its own ``--dry-run``. If anything would conflict, nothing is written. A file this installer did not
write is never overwritten, even with ``--force``; a file it wrote and you edited needs ``--force``.
``--force`` is not passed to mnemosyne's installer (there it would repoint ``MNEMOSYNE_REPO``).
Beside an installed Amphion plugin in Claude Code, the skills are not copied (the plugin has them).
``--platform codex`` and ``cursor`` are refused: they are stage 2's host port.

``--uninstall`` removes the unedited files of the bundles that leave, and a bundle that something still
installed needs stays. Zethus and Mnemosyne are uninstalled through their own installers (user scope);
in a repo their committed files go with git. The memory repo is never removed.

The shared core (``core/``) is the one source tree for the memory hook script and its registrations, the
``memory`` config schema and the skills both kits use. The plugin folders (``mnemosyne/plugin``,
``amphion/plugin``) must be self-contained to install from a marketplace, so they carry byte copies of
the core's files, listed under ``core.mirrors`` in the catalog. Edit ``core/``, then ``--sync-core``;
``--check`` (and CI) fails while a copy differs, is missing, or has no source.

Exit codes: 0 done (or a dry run, or a clean ``--check``) · 1 a conflict, a failed delegate, or problems
found · 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_PARTS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


# --------------------------------------------------------------------------- reading the catalog


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_catalog(root: Path = ROOT) -> dict:
    return read_json(root / "catalog.json")


def closure(catalog: dict, names) -> list[str]:
    """``names`` plus everything they require, dependencies first, each once."""
    out: list[str] = []

    def visit(name: str, trail: tuple[str, ...]) -> None:
        if name in out:
            return
        if name in trail:
            raise ValueError("bundles require each other in a loop: " + " -> ".join((*trail, name)))
        if name not in catalog["bundles"]:
            raise KeyError(name)
        for dep in catalog["bundles"][name].get("requires", []):
            visit(dep, (*trail, name))
        out.append(name)

    for n in names:
        visit(n, ())
    return out


# --------------------------------------------------------------------------- the shared core's copies


def files_under(path: Path) -> list[Path]:
    """Every file below ``path`` (or ``path`` itself when it is a file), build litter skipped."""
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*")
                  if p.is_file() and not SKIP_PARTS & set(p.parts) and p.suffix not in SKIP_SUFFIXES)


def mirror_pairs(catalog: dict, root: Path = ROOT) -> list[tuple[Path, Path]]:
    """``(source file, copy file)`` for every entry of every bundle's ``mirrors``."""
    pairs: list[tuple[Path, Path]] = []
    for bundle in catalog["bundles"].values():
        for m in bundle.get("mirrors", []):
            src, dst = root / m["from"], root / m["to"]
            if src.is_file():
                pairs.append((src, dst))
            else:
                pairs += [(f, dst / f.relative_to(src)) for f in files_under(src)]
    return pairs


def stale_mirrors(catalog: dict, root: Path = ROOT) -> list[str]:
    """Copies that are missing, differ, or have no source any more (repo-relative, sorted)."""
    bad: set[str] = set()
    expected: set[Path] = set()
    for src, dst in mirror_pairs(catalog, root):
        expected.add(dst)
        if not dst.is_file() or dst.read_bytes() != src.read_bytes():
            bad.add(dst.relative_to(root).as_posix())
    for bundle in catalog["bundles"].values():
        for m in bundle.get("mirrors", []):
            dst = root / m["to"]
            if (root / m["from"]).is_dir() and dst.is_dir():
                bad |= {f.relative_to(root).as_posix() for f in files_under(dst) if f not in expected}
    return sorted(bad)


def sync_core(catalog: dict, root: Path = ROOT) -> list[str]:
    """Write every copy from its source and drop copies with no source. Returns what changed."""
    changed: list[str] = []
    for src, dst in mirror_pairs(catalog, root):
        if not dst.is_file() or dst.read_bytes() != src.read_bytes():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            changed.append(dst.relative_to(root).as_posix())
    expected = {dst for _, dst in mirror_pairs(catalog, root)}
    for bundle in catalog["bundles"].values():
        for m in bundle.get("mirrors", []):
            dst = root / m["to"]
            if (root / m["from"]).is_dir() and dst.is_dir():
                for f in files_under(dst):
                    if f not in expected:
                        f.unlink()
                        changed.append(f.relative_to(root).as_posix())
    return changed


# --------------------------------------------------------------------------- JSON Schema (the subset)


def schema_problems(value, schema: dict, where: str = "$") -> list[str]:
    """Why ``value`` does not satisfy ``schema``. Reads only the keywords ``core/memory.schema.json``
    uses (``type``, ``enum``, ``properties``, ``additionalProperties``, ``required``, ``items``,
    ``oneOf``, ``minimum``): this repo's CI is stdlib-only."""
    kinds = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int}
    if "oneOf" in schema:
        hits = sum(1 for s in schema["oneOf"] if not schema_problems(value, s, where))
        return [] if hits == 1 else [f"{where}: matches none of the allowed shapes"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{where}: {value!r} is not one of {schema['enum']}"]
    kind = schema.get("type")
    if kind:
        ok = isinstance(value, kinds[kind]) and not (kind == "integer" and isinstance(value, bool))
        if not ok:
            return [f"{where}: expected {kind}"]
    problems: list[str] = []
    if "minimum" in schema and isinstance(value, int) and value < schema["minimum"]:
        problems.append(f"{where}: {value} is below {schema['minimum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"{where}: missing {key!r}")
        for key, item in value.items():
            if key in props:
                problems += schema_problems(item, props[key], f"{where}.{key}")
            elif schema.get("additionalProperties") is False:
                problems.append(f"{where}: unknown key {key!r}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            problems += schema_problems(item, schema["items"], f"{where}[{i}]")
    return problems


# --------------------------------------------------------------------------- --check


def check(root: Path = ROOT) -> list[str]:
    """Every way the catalog, the shared core and the plugin manifests disagree. Empty when fine."""
    problems: list[str] = []
    try:
        catalog = load_catalog(root)
    except (OSError, ValueError) as exc:
        return [f"catalog.json: {exc}"]
    bundles = catalog.get("bundles")
    if not isinstance(bundles, dict) or not bundles:
        return ["catalog.json: no bundles"]
    hosts = catalog.get("hosts", {})
    built = {h for h, v in hosts.items() if v.get("built")}

    for name, b in sorted(bundles.items()):
        for dep in b.get("requires", []):
            if dep not in bundles:
                problems.append(f"{name}: requires {dep!r}, which is not a bundle")
        for h in b.get("hosts", []):
            if h not in built:
                problems.append(f"{name}: lists host {h!r}, which is not built (catalog hosts)")
        if not b.get("hosts"):
            problems.append(f"{name}: no hosts")
        if b.get("kind") == "delegate" and not (root / b.get("installer", "")).is_file():
            problems.append(f"{name}: installer {b.get('installer')!r} does not exist")
    try:
        closure(catalog, bundles)
    except (ValueError, KeyError) as exc:
        problems.append(f"requires: {exc}")
        return problems

    core = bundles.get("core", {})
    for key in ("memorySchema",):
        if key in core and not (root / core[key]).is_file():
            problems.append(f"core: {core[key]} does not exist")
    for key, rel in (core.get("hooks") or {}).items():
        if not (root / rel).is_file():
            problems.append(f"core: hooks.{key} {rel} does not exist")
    core_skills = core.get("skills", [])
    for skill in core_skills:
        if not (root / core.get("source", "core") / "skills" / skill / "SKILL.md").is_file():
            problems.append(f"core: skill {skill!r} has no SKILL.md under {core.get('source', 'core')}/skills")
    on_disk = ({p.name for p in (root / "core" / "skills").iterdir() if p.is_dir()}
               if (root / "core" / "skills").is_dir() else set())
    for stray in sorted(on_disk - set(core_skills)):
        problems.append(f"core: core/skills/{stray} is not listed in the catalog")

    for rel in stale_mirrors(catalog, root):
        problems.append(f"{rel}: differs from its source in core/ (edit core/, then python install.py --sync-core)")

    amphion = bundles.get("amphion", {})
    if amphion:
        skills_dir = root / amphion["source"] / "skills"
        wanted = set(amphion.get("skills", [])) | set(core_skills)
        have = {p.name for p in skills_dir.iterdir() if p.is_dir()} if skills_dir.is_dir() else set()
        for missing in sorted(wanted - have):
            problems.append(f"amphion: {skills_dir.relative_to(root).as_posix()}/{missing} is missing")
        for extra in sorted(have - wanted):
            problems.append(f"amphion: {skills_dir.relative_to(root).as_posix()}/{extra} is in no bundle's skill list")

    problems += plugin_problems(catalog, root)
    problems += memory_config_problems(catalog, root)
    return problems


def plugin_problems(catalog: dict, root: Path) -> list[str]:
    """The marketplaces and plugin manifests against ``catalog.plugins``, both ways."""
    problems: list[str] = []
    listed: dict[str, set[str]] = {}
    for p in catalog.get("plugins", []):
        listed.setdefault(p["marketplace"], set()).add(p["name"])
        if p["bundle"] not in catalog["bundles"]:
            problems.append(f"plugins: {p['name']} names bundle {p['bundle']!r}, which does not exist")
            continue
        try:
            market = {e["name"]: e for e in read_json(root / p["marketplace"])["plugins"]}
        except (OSError, ValueError, KeyError) as exc:
            problems.append(f"{p['marketplace']}: {exc}")
            continue
        entry = market.get(p["name"])
        if entry is None:
            problems.append(f"{p['marketplace']}: no entry for {p['name']}")
            continue
        if entry.get("source") != p["source"]:
            problems.append(f"{p['marketplace']}: {p['name']} source is {entry.get('source')!r}, "
                            f"the catalog says {p['source']!r}")
        try:
            version = read_json(root / p["manifest"]).get("version")
        except (OSError, ValueError) as exc:
            problems.append(f"{p['manifest']}: {exc}")
            continue
        if entry.get("version") != version:
            problems.append(f"{p['marketplace']}: {p['name']} is {entry.get('version')!r} but "
                            f"{p['manifest']} says {version!r}")
    for marketplace, names in listed.items():
        try:
            entries = {e["name"] for e in read_json(root / marketplace)["plugins"]}
        except (OSError, ValueError, KeyError):
            continue
        for extra in sorted(entries - names):
            problems.append(f"{marketplace}: {extra} is in the marketplace but not in the catalog")
    return problems


def memory_config_problems(catalog: dict, root: Path) -> list[str]:
    """Each kit's example config: its ``memory`` block, if any, must satisfy the core's schema."""
    rel = catalog["bundles"].get("core", {}).get("memorySchema")
    if not rel:
        return []
    try:
        schema = read_json(root / rel)
    except (OSError, ValueError) as exc:
        return [f"{rel}: {exc}"]
    problems: list[str] = []
    for name, b in sorted(catalog["bundles"].items()):
        example = (b.get("config") or {}).get("example")
        if not example:
            continue
        try:
            block = read_json(root / example).get("memory")
        except (OSError, ValueError) as exc:
            problems.append(f"{example}: {exc}")
            continue
        if block is not None:
            problems += [f"{example}: {p}" for p in schema_problems(block, schema, "memory")]
    return problems




# --------------------------------------------------------------------------- the installer

BUILT = ("claude", "copilot")
MANIFEST_NAME = "install-manifest.json"
DELEGATE_MODULES = {"mnemosyne": "mnemosyne_install", "zethus": "zethus_install"}


def delegate(name: str, root: Path = ROOT):
    """A kit's own installer, loaded once under the name its sibling installers use, so every caller
    (and every test fake) sees one module. It is *called*, never copied."""
    key = DELEGATE_MODULES[name]
    module = sys.modules.get(key)
    if module is None:
        import importlib.util
        path = root / load_catalog(root)["bundles"][name]["installer"]
        spec = importlib.util.spec_from_file_location(key, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[key] = module
        spec.loader.exec_module(module)
    return module


def call(name: str, argv: list[str], quiet: bool = False, root: Path = ROOT) -> tuple[int, str]:
    """Run a kit installer's ``main``. ``quiet`` captures its output (a rehearsal); a usage error
    that exits is turned into its code."""
    import contextlib
    import io
    buf = io.StringIO()
    mod = delegate(name, root)
    try:
        if quiet:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = mod.main(argv)
        else:
            code = mod.main(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
    return int(code or 0), buf.getvalue()


def sha256(data: bytes) -> str:
    import hashlib
    return hashlib.sha256(data).hexdigest()


class Scope:
    """Where one run writes: the user's home, or a repository. Manifest keys are absolute for a user
    install and repo-relative for a repo, so a committed manifest names no machine."""

    def __init__(self, target: Path | None):
        self.target = target
        self.base = target if target is not None else Path.home()

    @property
    def user(self) -> bool:
        return self.target is None

    def skills_root(self, host: str) -> Path:
        if host == "claude":
            return self.base / ".claude" / "skills"
        return self.base / (".copilot" if self.user else ".github") / "skills"

    def manifest_path(self) -> Path:
        return self.base / ".mesmer-grimoire" / MANIFEST_NAME

    def key(self, path: Path) -> str:
        return path.as_posix() if self.user else path.relative_to(self.base).as_posix()

    def path(self, key: str) -> Path:
        return Path(key) if self.user else self.base / key

    def show(self, path: Path) -> str:
        try:
            return ("~/" if self.user else "") + path.resolve().relative_to(self.base.resolve()).as_posix()
        except ValueError:
            return path.as_posix()


def read_manifest(scope: Scope) -> dict:
    try:
        doc = read_json(scope.manifest_path())
    except (OSError, ValueError):
        return {"version": 1, "bundles": {}, "files": {}}
    if not isinstance(doc, dict):
        return {"version": 1, "bundles": {}, "files": {}}
    doc.setdefault("bundles", {})
    doc.setdefault("files", {})
    return doc


def write_manifest(scope: Scope, doc: dict) -> None:
    path = scope.manifest_path()
    if not doc["files"] and not any(doc["bundles"].values()):
        if path.is_file():
            path.unlink()
            prune(path.parent, scope.base)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"_readme": "Files install.py wrote, with their SHA-256, and the bundles asked for on each "
                       "host. install.py --uninstall removes the unedited ones.",
            "version": 1, "bundles": {h: sorted(v) for h, v in sorted(doc["bundles"].items()) if v},
            "files": dict(sorted(doc["files"].items()))}
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(body, fh, indent=2)
        fh.write("\n")


def prune(start: Path, stop: Path) -> None:
    """Remove empty folders from ``start`` upward, never ``stop`` or anything above it."""
    here = start
    while here != stop and stop in here.parents:
        try:
            here.rmdir()
        except OSError:
            return
        here = here.parent


class Step:
    def __init__(self, dest: Path, data: bytes, bundle: str, host: str, action: str, note: str = ""):
        self.dest, self.data, self.bundle, self.host, self.action, self.note = dest, data, bundle, host, action, note


def skill_payloads(catalog: dict, bundle: str, root: Path) -> list[tuple[str, bytes]]:
    """``(path below the skills root, bytes)`` for the skills a bundle installs: the core's from
    ``core/skills``, a kit's own from its plugin folder."""
    b = catalog["bundles"][bundle]
    base = root / b["source"] / "skills"
    out = []
    for skill in b.get("skills", []):
        for f in files_under(base / skill):
            out.append(((Path(skill) / f.relative_to(base / skill)).as_posix(), f.read_bytes()))
    return out


def plan_files(catalog: dict, root: Path, scope: Scope, host: str, bundles: list[str],
               manifest: dict) -> list[Step]:
    steps: list[Step] = []
    skills = scope.skills_root(host)
    for bundle in bundles:
        if catalog["bundles"][bundle].get("kind") != "files":
            continue
        for rel, data in skill_payloads(catalog, bundle, root):
            dest = skills / rel
            have = dest.read_bytes() if dest.is_file() else None
            recorded = manifest["files"].get(scope.key(dest), {}).get("sha256")
            if have is None:
                action, note = "create", ""
            elif sha256(have) == sha256(data):
                action, note = "same", ""
            elif recorded is None:
                action, note = "foreign", "not installed by install.py"
            elif sha256(have) == recorded:
                action, note = "update", ""
            else:
                action, note = "conflict", "edited since install"
            steps.append(Step(dest, data, bundle, host, action, note))
    planned = {scope.key(s.dest) for s in steps}
    owned_here = {b for b in bundles}
    for key, rec in sorted(manifest["files"].items()):
        if rec.get("host") == host and rec.get("bundle") in owned_here and key not in planned:
            path = scope.path(key)
            if path.is_file() and sha256(path.read_bytes()) == rec.get("sha256"):
                steps.append(Step(path, b"", rec["bundle"], host, "remove", "no longer part of the bundle"))
    return steps


def plan_config(catalog: dict, root: Path, scope: Scope, bundles: list[str]) -> list[tuple[Path, Path, str]]:
    """Each kit's example config, written into a *repo* install only, and never over a file that is
    there. ``(source, dest, action)``; the action is create or keep. A user install writes none: a
    default config in the home would override discovery in every repo."""
    out: list[tuple[Path, Path, str]] = []
    if scope.user:
        return out
    seen: set[Path] = set()
    for bundle in bundles:
        cfg = catalog["bundles"][bundle].get("config") or {}
        if bundle != "amphion" or "dest" not in cfg:
            continue
        dest = scope.base / cfg["dest"]
        if dest in seen:
            continue
        seen.add(dest)
        out.append((root / cfg["example"], dest, "keep" if dest.exists() else "create"))
    return out


def effective(catalog: dict, requested: list[str], host: str) -> list[str]:
    """What installs on ``host``: the requested bundles that support it, and what those need."""
    here = [b for b in requested if host in catalog["bundles"][b]["hosts"]]
    return [b for b in closure(catalog, here) if host in catalog["bundles"][b]["hosts"]]


def claude_amphion_plugin() -> str | None:
    """The Amphion plugin's id if Claude Code has it: it carries every skill this would copy."""
    mn = delegate("mnemosyne")
    claude = mn.which("claude")
    if not claude:
        return None
    return next((p for p in mn.installed_plugins(claude) if p.startswith("amphion@")), None)


def mnemosyne_argv(args, hosts: list[str], scope: Scope, dry: bool) -> list[str]:
    argv: list[str] = []
    if "copilot" in hosts:
        argv += ["--user"] if scope.user else ["--target", str(scope.target)]
    if args.memory_repo:
        argv += ["--repo", args.memory_repo]
    if args.copilot_hooks_dir and "copilot" in hosts:
        argv += ["--copilot-hooks-dir", args.copilot_hooks_dir]
    if args.python:
        argv += ["--python", args.python]
    if dry:
        argv.append("--dry-run")
    return argv


def zethus_argv(args, scope: Scope, dry: bool) -> list[str]:
    argv = ["--user"] if scope.user else ["--target", str(scope.target)]
    if args.force:
        argv.append("--force")
    if dry:
        argv.append("--dry-run")
    return argv


def say(label: str, what: str, note: str = "") -> None:
    print(f"{label:9} {what}" + (f"  ({note})" if note else ""))


def install(args, catalog: dict, root: Path, hosts: list[str], requested: list[str], scope: Scope) -> int:
    sets = {h: effective(catalog, requested, h) for h in hosts}
    for h in hosts:
        skipped = [b for b in requested if h not in catalog["bundles"][b]["hosts"]]
        for b in skipped:
            say("skip", f"{b} on {h}", f"{b} supports {', '.join(catalog['bundles'][b]['hosts'])} only")
    active = {h: s for h, s in sets.items() if s}
    if not active:
        print("install: nothing to install: none of the requested bundles supports the requested "
              "host(s)", file=sys.stderr)
        return 2
    everything = [b for b in closure(catalog, requested) if any(b in s for s in active.values())]
    manifest = read_manifest(scope)
    amphion_plugin = claude_amphion_plugin() if "claude" in active and not args.force else None

    # ---- plan everything, then refuse before writing anything
    file_steps: dict[str, list[Step]] = {}
    for h, bundles in active.items():
        if h == "claude" and amphion_plugin:
            say("skip", f"Claude Code skills in {scope.show(scope.skills_root('claude'))}",
                f"the Amphion plugin {amphion_plugin} carries them; --force copies them anyway")
            continue
        file_steps[h] = plan_files(catalog, root, scope, h, bundles, manifest)
    foreign = [s for ss in file_steps.values() for s in ss if s.action == "foreign"]
    edited = [s for ss in file_steps.values() for s in ss if s.action == "conflict"]
    refusals: list[str] = []
    for s in foreign:
        refusals.append(f"{scope.show(s.dest)}  (not installed by install.py: never overwritten, even with --force)")
    if not args.force:
        refusals += [f"{scope.show(s.dest)}  (a file you edited: --force overwrites it)" for s in edited]
    for name in ("mnemosyne", "zethus"):
        if name not in everything:
            continue
        hs = [h for h in active if name in active[h]]
        argv = (mnemosyne_argv(args, hs, scope, True) if name == "mnemosyne"
                else zethus_argv(args, scope, True))
        code, out = call(name, argv, quiet=True, root=root)
        if code != 0:
            lines = [ln for ln in out.splitlines() if ln.strip()]
            more = f"\n    ... and {len(lines) - 12} more line(s)" if len(lines) > 12 else ""
            refusals.append(f"{name}: its installer would refuse (python {catalog['bundles'][name]['installer']} "
                            f"{' '.join(a for a in argv if a != '--dry-run')} says why):\n    "
                            + "\n    ".join(lines[:12]) + more)
    if refusals:
        print("install: nothing was written. These need a decision first:")
        for line in refusals:
            print(f"  {line}")
        return 1

    # ---- do it, in dependency order
    dry = args.dry_run
    code_all = 0
    for bundle in everything:
        b = catalog["bundles"][bundle]
        print(f"== {bundle}")
        if b["kind"] == "delegate":
            hs = [h for h in active if bundle in active[h]]
            argv = (mnemosyne_argv(args, hs, scope, dry) if bundle == "mnemosyne"
                    else zethus_argv(args, scope, dry))
            code = call(bundle, argv, root=root)[0]
            if code != 0:
                print(f"install: {bundle}'s installer failed ({code}); stopping here")
                code_all = max(code_all, code)
                break
            continue
        for h, steps in file_steps.items():
            for s in [x for x in steps if x.bundle == bundle]:
                label = {"create": "create", "update": "update", "same": "same", "conflict": "overwrite",
                         "remove": "remove"}[s.action]
                say(label, f"{scope.show(s.dest)}  [{h}]", s.note if s.action == "remove" else "")
                if dry or s.action == "same":
                    if s.action == "same" and not dry:
                        manifest["files"][scope.key(s.dest)] = {"sha256": sha256(s.data), "bundle": s.bundle, "host": h}
                    continue
                if s.action == "remove":
                    s.dest.unlink()
                    manifest["files"].pop(scope.key(s.dest), None)
                    prune(s.dest.parent, scope.skills_root(h).parent)
                    continue
                s.dest.parent.mkdir(parents=True, exist_ok=True)
                s.dest.write_bytes(s.data)
                manifest["files"][scope.key(s.dest)] = {"sha256": sha256(s.data), "bundle": s.bundle, "host": h}
        for src, dest, action in plan_config(catalog, root, scope, [bundle]):
            say(action, scope.show(dest), "an existing config is never overwritten" if action == "keep" else "edit it")
            if not dry and action == "create":
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(src.read_bytes())
    if not dry:
        for h in active:
            manifest["bundles"][h] = sorted(set(manifest["bundles"].get(h, [])) | {b for b in requested if b in active[h]})
        write_manifest(scope, manifest)
    print("dry run: nothing written" if dry else
          ("installed." if code_all == 0 else "installed in part; see above"))
    return code_all


def uninstall(args, catalog: dict, root: Path, hosts: list[str], requested: list[str] | None, scope: Scope) -> int:
    manifest = read_manifest(scope)
    recorded = manifest["bundles"]
    if not recorded and not manifest["files"] and not requested:
        print(f"uninstall: no install recorded ({scope.show(scope.manifest_path())} is missing); "
              "name a --bundle to remove one a kit's own installer put there")
        return 1
    dry = args.dry_run
    leaving: dict[str, list[str]] = {}
    keep_sets: dict[str, list[str]] = {}
    remaining_by_host: dict[str, list[str]] = {}
    for h in hosts:
        have = list(recorded.get(h, []))
        gone = list(requested) if requested is not None else have
        remaining = [b for b in have if b not in gone]
        remaining_by_host[h] = remaining
        remaining_here = [b for b in remaining if h in catalog["bundles"][b]["hosts"]]
        keep_sets[h] = effective(catalog, remaining_here, h)
        asked = [b for b in gone if h in catalog["bundles"][b]["hosts"]]
        before = effective(catalog, sorted(set(have) | set(asked)), h) if (have or asked) else []
        leaving[h] = [b for b in before if b not in keep_sets[h]]
    kept = 0
    for key, rec in sorted(manifest["files"].items()):
        h, bundle = rec.get("host"), rec.get("bundle")
        if h not in leaving or bundle not in leaving[h]:
            continue
        path = scope.path(key)
        if not path.is_file():
            say("gone", scope.show(path))
            manifest["files"].pop(key)
            continue
        if sha256(path.read_bytes()) != rec.get("sha256") and not args.force:
            kept += 1
            say("keep", scope.show(path), "edited since install; --force removes it")
            continue
        say("remove", scope.show(path))
        if not dry:
            path.unlink()
            manifest["files"].pop(key)
            prune(path.parent, scope.skills_root(h).parent)
    code = 0
    still_needed = {b for s in keep_sets.values() for b in s}
    gone_everywhere = {b for ls in leaving.values() for b in ls} - still_needed
    for name in ("zethus", "mnemosyne"):
        if name not in gone_everywhere:
            continue
        if not scope.user:
            say("note", f"{name} in this repo", "its committed files are removed with git, as its own installer says")
            continue
        argv = ["--user", "--uninstall"] if name == "zethus" else ["--uninstall"]
        if args.force:
            argv.append("--force")
        if dry:
            argv.append("--dry-run")
        print(f"== {name}")
        code = max(code, call(name, argv, root=root)[0])
    if not dry:
        for h in hosts:
            if h in recorded:
                recorded[h] = remaining_by_host[h]
        write_manifest(scope, manifest)
    print("dry run: nothing removed" if dry else
          "uninstalled." + (f" {kept} edited file(s) kept." if kept else ""))
    return 1 if (kept and code == 0) else code


# --------------------------------------------------------------------------- cli


def list_bundles(catalog: dict) -> str:
    lines = []
    for name, b in catalog["bundles"].items():
        needs = ", ".join(b.get("requires", [])) or "-"
        lines.append(f"{name:10} hosts: {', '.join(b['hosts']):15} needs: {needs}")
        lines.append(f"{'':10} {b['summary']}")
    unbuilt = [h for h, v in catalog.get("hosts", {}).items() if not v.get("built")]
    if unbuilt:
        lines.append(f"not built yet: {', '.join(unbuilt)} (stage 2; docs/lessons-capture-spec.md)")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="install.py", description="The grimoire installer: Zethus, Amphion, the shared core and "
        "Mnemosyne, for Claude Code and GitHub Copilot.")
    p.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    p.add_argument("--platform", action="append", metavar="HOST",
                   help="claude, copilot or all; repeat or comma-separate (default: all)")
    where = p.add_mutually_exclusive_group()
    where.add_argument("--user", action="store_true", help="install for your account (~/.claude, ~/.copilot)")
    where.add_argument("--target", metavar="DIR", help="install into this repository")
    p.add_argument("--bundle", action="append", metavar="NAME",
                   help="zethus, amphion, core or mnemosyne; repeat or comma-separate (default: all)")
    p.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    p.add_argument("--force", action="store_true", help="overwrite files you edited")
    p.add_argument("--uninstall", action="store_true", help="remove what this installer put there")
    p.add_argument("--memory-repo", metavar="PATH", help="mnemosyne's memory repo (its --repo)")
    p.add_argument("--copilot-hooks-dir", metavar="PATH", help="mnemosyne's --copilot-hooks-dir")
    p.add_argument("--python", metavar="PATH", help="mnemosyne's --python: the interpreter the hooks run")
    p.add_argument("--check", action="store_true",
                   help="validate catalog.json, the shared core's copies and the plugin manifests")
    p.add_argument("--list", action="store_true", help="list the bundles")
    p.add_argument("--sync-core", action="store_true",
                   help="rewrite the plugin folders' copies of core/ from core/")
    return p


def split(values: list[str] | None) -> list[str]:
    return [x.strip() for v in values or [] for x in v.split(",") if x.strip()]


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    root = Path(args.root).resolve()
    installing = args.user or args.target
    if not (args.check or args.list or args.sync_core or installing or args.uninstall):
        p.print_usage(sys.stderr)
        print("install.py: nothing to do: pass --user or --target, or --check, --list or --sync-core",
              file=sys.stderr)
        return 2
    code = 0
    if args.sync_core:
        changed = sync_core(load_catalog(root), root)
        for c in changed:
            print(f"write     {c}")
        print(f"synced: {len(changed)} file(s) changed" if changed else "synced: every copy is current")
    if args.list:
        print(list_bundles(load_catalog(root)))
    if args.check:
        problems = check(root)
        for line in problems:
            print(f"check: {line}")
        if problems:
            print(f"check: {len(problems)} problem(s)")
            return 1
        print("check: catalog, shared core and plugin manifests agree")
    if not installing and not args.uninstall:
        return code
    if not installing:
        p.error("--uninstall needs --user or --target")
    catalog = load_catalog(root)
    problems = check(root)
    if problems:
        for line in problems:
            print(f"check: {line}", file=sys.stderr)
        print("install: the catalog does not check out; nothing was written", file=sys.stderr)
        return 1
    names = split(args.platform) or ["all"]
    hosts: list[str] = []
    for n in names:
        if n == "all":
            hosts += [h for h in BUILT if h not in hosts]
        elif n in BUILT:
            hosts += [n] if n not in hosts else []
        elif n in catalog["hosts"]:
            print(f"install: --platform {n} is not built yet: it is stage 2's host port "
                  "(docs/lessons-capture-spec.md, Phase 4)", file=sys.stderr)
            return 2
        else:
            p.error(f"unknown --platform {n!r}: claude, copilot or all")
    asked = split(args.bundle)
    for b in asked:
        if b not in catalog["bundles"]:
            p.error(f"unknown --bundle {b!r}: " + ", ".join(catalog["bundles"]))
    scope = Scope(Path(args.target).resolve() if args.target else None)
    if scope.target is not None and not scope.target.is_dir():
        print(f"install: target is not a directory: {args.target}", file=sys.stderr)
        return 2
    if args.uninstall:
        return uninstall(args, catalog, root, hosts, asked or None, scope)
    requested = asked or [b for b in catalog["bundles"] if b not in ("core", "mnemosyne")] or list(catalog["bundles"])
    return install(args, catalog, root, hosts, requested, scope)


if __name__ == "__main__":
    sys.exit(main())
