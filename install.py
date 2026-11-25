#!/usr/bin/env python3
"""The grimoire installer: one entry point for the kits in this repo.

    python install.py --check                  # validate catalog.json, the shared core and the plugin manifests
    python install.py --list                   # the bundles, what each needs and which hosts it supports
    python install.py --sync-core              # rewrite the plugin folders' copies of core/ from core/

``catalog.json`` is the only list of what exists. The shared core (``core/``) is the one source tree
for the memory hook script and its registrations, the ``memory`` config schema and the skills Zethus
and Amphion both use. The plugin folders (``mnemosyne/plugin``, ``amphion/plugin``) must be
self-contained to install from a marketplace, so they carry byte copies of the core's files, listed
under ``core.mirrors`` in the catalog. Edit ``core/``, then ``--sync-core``; ``--check`` (and CI) fails
while a copy differs, is missing, or has no source.

Exit codes: 0 fine · 1 problems found (``--check``) or a stale copy · 2 usage error.
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
    p = argparse.ArgumentParser(prog="install.py", description="The grimoire installer.")
    p.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    p.add_argument("--check", action="store_true",
                   help="validate catalog.json, the shared core's copies and the plugin manifests")
    p.add_argument("--list", action="store_true", help="list the bundles")
    p.add_argument("--sync-core", action="store_true",
                   help="rewrite the plugin folders' copies of core/ from core/")
    return p


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    root = Path(args.root).resolve()
    if not (args.check or args.list or args.sync_core):
        p.print_usage(sys.stderr)
        print("install.py: nothing to do: pass --check, --list or --sync-core", file=sys.stderr)
        return 2
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
