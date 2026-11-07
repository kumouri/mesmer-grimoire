# Morpheus retrospective

<!-- doc-pointers: point-in-time -->

Morpheus was retired from `develop` together with the `grimoire` umbrella that composed it with
mnemosyne. The last code is kept at two tags on the same commit:

- [`morpheus-final`](https://github.com/kumouri/mesmer-grimoire/tree/morpheus-final/morpheus):
  the engine, its plugin and its tests.
- [`grimoire-final`](https://github.com/kumouri/mesmer-grimoire/tree/grimoire-final/grimoire):
  the umbrella MCP server and plugin.

The evidence behind the decision is in the
[stage 1 assessment](stage1-assessment-2026-09-30.md#13-morpheus-automatic-session-dreaming)
(§1.3 and §1.4). This page records
what morpheus was for, why it never worked, and what is worth keeping from it.

## What it was meant to do

Automatic **memory consolidation** for Claude Code sessions, a "dream" after each session:

1. `PreCompact` and `SessionEnd` hooks queued a small job in a durable spool and exited at once,
   so the session was never blocked.
2. A detached worker read the transcript delta since the last run and reflected over it with one
   of three engines: `headless` (`claude -p --bare`), `hybrid` (a Haiku extraction plus
   deterministic writing) or `deterministic` (regex, no model).
3. It wrote durable facts into Claude Code's per-project memory store (`memory/<type>-<slug>.md`
   plus `MEMORY.md`) and a log into `memory/dreams/`.
4. A `SessionStart` hook injected a short recall digest.

It also shipped a CLI, a three-tool MCP server (`dream`, `wake`, `dreams`), a skill, a command,
scheduler templates and a `settings.json` installer. The umbrella re-exported its tools alongside
mnemosyne's on one server, and its main job was to stop the two plugins' hooks double-firing.

## Why it never ran

Installed with live hooks, it produced no dream, no job and no log. Three things lined up:

1. **Its own recursion guard switched it off.** The dispatcher exited silently whenever
   `CLAUDE_CODE_CHILD_SESSION=1`
   ([`dispatch.py`](https://github.com/kumouri/mesmer-grimoire/blob/morpheus-final/morpheus/src/morpheus/dispatch.py)).
   The guard was meant to stop the worker's own `claude -p` child from dreaming about itself. But
   Claude Code sets that variable in the environment of every hook command, so the guard fired in
   the parent session too, every time. The umbrella's `grimoire_hook.py` copied the same guard.
2. **`--bare` needs an API key.** Had a job ever been queued, the default `headless` engine ran
   `claude -p --bare`. `--bare` authenticates only with `ANTHROPIC_API_KEY`, which a
   subscription-billed setup deliberately leaves unset. The docs never mentioned the requirement,
   so the next failure was already waiting behind the first.
3. **The tests hid it.** The shared test fixture removed `CLAUDE_CODE_CHILD_SESSION` before every
   test ([`tests/_util.py`](https://github.com/kumouri/mesmer-grimoire/blob/morpheus-final/tests/_util.py)),
   so the suite was green while the real hook did nothing. The maintainer guidance even told
   contributors to *preserve* the guard.

The dispatcher also swallowed every error and always exited 0, by design, so that none of this ever
produced a signal.

## Why it was retired rather than fixed

- **The hosts now do it natively.** Claude Code's auto memory writes the same `MEMORY.md` store,
  and Codex and Copilot have their own memory features. A second writer would race the native one.
- **It was the least portable piece in the repo.** Every layer depended on Claude Code: hook
  payloads, `claude -p`, the transcript JSONL format and the memory-store layout. Porting it would
  have meant a transcript parser, a headless adapter and a memory store per host.
- **Its one real consumer had outgrown it**, with its own consolidation that treats transcript text
  as untrusted and bills to the subscription.
- **Fixing it was not small.** Besides the three failures above, it kept the *first* 24,000
  characters of a long transcript and marked the rest processed, would have re-sorted a
  hand-ordered `MEMORY.md`, and its lock was shorter than a dream.

## What is worth keeping

- **A durable spool in front of a detached worker.** Hooks that only enqueue and exit can't block
  or lose work: a job interrupted by the app closing is retried at the next drain.
- **A per-session high-water mark,** so a mid-session `PreCompact` run and the later `SessionEnd`
  run never ingest the same messages twice.
- **The no-console-window spawn on Windows:** `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`,
  with `start_new_session=True` elsewhere.
- **The lesson about guards.** An environment-variable recursion guard must be tested *with the
  variable set the way the host really sets it*. A fixture that clears it proves only that the
  code runs when the guard is off.
- **The lesson about silence.** Swallowing errors to protect the host session is right, but it
  needs a matching way to see that the hook did anything: a log line per dispatch decision, or a
  `doctor` command.
