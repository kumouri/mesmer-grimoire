#!/usr/bin/env python3
"""Keep the Zethus plugin's root mirror of its agent and hook in step with the canonical copies.

Two Copilot hosts read one plugin from places that don't overlap:

* The **Copilot CLI** (1.0.105, 1.0.106-2) sees the Agent Plugins 1.0 ``$schema`` in ``plugin.json``
  and reads agents and hooks *only* from ``com.github.copilot/agents/`` and
  ``com.github.copilot/hooks/hooks.json``. It logs that the root ones are "no longer read".
* **IntelliJ's Copilot language server** (plugin 1.20.0, server 1.555.7) ignores ``$schema`` and
  reads agents only from ``agents/`` and hooks only from ``hooks.json`` or ``hooks/hooks.json`` at the
  plugin root, plus paths named by top-level ``agents``/``hooks`` keys. The 1.0 manifest schema is
  closed, and the CLI logs those keys as unknown and ignores them, so they are no way out.

So the canonical files stay under ``com.github.copilot/``, where ``install.py`` also reads them, and
this script writes the root copies the language server needs:

    com.github.copilot/agents/*.agent.md -> agents/*.agent.md   (links one folder shallower)
    com.github.copilot/hooks/hooks.json  -> hooks/hooks.json     (byte copy; same script, same root)

Neither host reads both places, so nothing loads or fires twice there. Edit only the canonical
files, then run this. ``tests/test_copilot_plugins.py`` fails while the mirror is stale.

    python scripts/sync_zethus_plugin_root.py           # write the mirror
    python scripts/sync_zethus_plugin_root.py --check   # exit 1 if it is stale, write nothing

Exit codes: 0 in step (or written) · 1 stale with ``--check`` · 2 usage error.
"""
from __future__ import annotations

import sys
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent / "zethus"
VENDOR = KIT / "com.github.copilot"
GENERATED = ("<!-- Generated from com.github.copilot/agents/{name} by "
             "scripts/sync_zethus_plugin_root.py. Edit that file, then re-run the script. -->\n\n")


def mirror_agent(text: str, name: str) -> str:
    """The canonical agent as it reads one folder below the kit root instead of two."""
    head, sep, body = text.partition("\n---\n")
    if not text.startswith("---\n") or not sep:
        raise ValueError(f"{name}: no frontmatter")
    body = body.replace("](../../", "](../")
    body = body.replace("else two folders above this file's folder", "else the folder above this file's folder")
    return f"{head}{sep}\n{GENERATED.format(name=name)}{body.lstrip(chr(10))}"


def expected() -> dict[Path, bytes]:
    """Every root-mirror file and the bytes it should hold."""
    out: dict[Path, bytes] = {}
    for src in sorted((VENDOR / "agents").glob("*.agent.md")):
        text = mirror_agent(src.read_text(encoding="utf-8"), src.name)
        out[KIT / "agents" / src.name] = text.encode("utf-8")
    out[KIT / "hooks" / "hooks.json"] = (VENDOR / "hooks" / "hooks.json").read_bytes()
    return out


def stale() -> list[Path]:
    """Mirror files that are missing, differ, or have no canonical source any more."""
    want = expected()
    bad = [p for p, data in want.items() if not p.is_file() or p.read_bytes() != data]
    bad += [p for p in (KIT / "agents").glob("*") if p not in want]
    bad += [p for p in (KIT / "hooks").glob("*") if p not in want]
    return sorted(set(bad))


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if any(a in ("-h", "--help") for a in args):
        print(__doc__)
        return 0
    if set(args) - {"--check"}:
        print(f"sync_zethus_plugin_root: unknown argument(s): {' '.join(sorted(set(args) - {'--check'}))}",
              file=sys.stderr)
        return 2
    bad = stale()
    rel = [p.relative_to(KIT.parent).as_posix() for p in bad]
    if "--check" in args:
        for r in rel:
            print(f"stale: {r}")
        if bad:
            print("Run: python scripts/sync_zethus_plugin_root.py")
            return 1
        print("zethus plugin root mirror: in step.")
        return 0
    want = expected()
    for path in bad:
        if path in want:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(want[path])
            print(f"wrote {path.relative_to(KIT.parent).as_posix()}")
        else:
            path.unlink()
            print(f"removed {path.relative_to(KIT.parent).as_posix()}")
    if not bad:
        print("zethus plugin root mirror: in step.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
