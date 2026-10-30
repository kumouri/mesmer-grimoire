# Mnemosyne — design

## Problem

An agent (or a team) is good at not wasting effort on what the current materials already answer.
It is **bad at not repeating itself across runs**. Every run starts cold: a gap hit last week (an
unspecified idempotency contract, a state transition nobody pinned, a soft-delete that looked like
a hard delete) is re-discovered the hard way, and a decision already settled (the house
persistence pattern, the audit-on-PII rule) is re-debated. The agent has no memory of its own
mistakes or the team's accumulated rulings.

## Goal

Give the agent a **reflexion memory**: durable *lessons* it **recalls** at the start of a task and
**applies**, plus a **reflect-and-capture** step that turns feedback (a review catch, a broken
assumption, an implementation landmine) into a lesson so the same miss never happens twice. It
must distribute to everyone using it, **announce itself** (no silent memory), and stay small and
portable — stdlib only, git for storage and distribution.

## The Reflexion loop

This implements [Reflexion (Shinn et al., 2023)](https://arxiv.org/abs/2303.11366): an agent that
improves not by retraining but by **verbally reflecting on feedback and storing those reflections
in an episodic buffer it consults on the next attempt**.

| Reflexion component | Here |
|---|---|
| **Actor** (produces a trajectory) | a stage's run → its artifact |
| **Evaluator** (scores it) | downstream reality: a reviewer, a test, the next stage |
| **Self-reflection** (verbal lesson from feedback) | `mnemosyne reflect` — "what should we have done?" |
| **Episodic memory buffer** | the git store (`memory/lessons.jsonl`) |
| **Recall on next trial** | `mnemosyne recall --stage` at the start of each stage |

Modern agent-memory practice frames the same store along three axes — **episodic** (a reflection
tied to a specific past event), **semantic** (a consolidated standing fact/decision), and
**procedural** (a rule that changes how the work is run). A lesson carries both a topical
`category` (mistake / decision / convention / security / architecture / process) and a
`memory_type` along that axis.

A lesson also carries a lifecycle **stage** — orthogonal to both — so the loop learns across a
whole `intake → plan → implement → review` trail rather than only at the front. `recall --stage
plan` boosts planning lessons; a lesson captured downstream defaults to recalling in *its* stage
**and** the front stage, so the build feeds the next round of work. `source.stage` records where a
lesson was learned; `trigger.stages` controls where it fires (empty = everywhere).

## Domain-agnostic by construction: config-driven axes

Nothing about a specific pipeline is hardcoded. A `mnemosyne.config.json` defines:

- the **lifecycle stages** and which one is the "front" stage lessons feed back into;
- the **recall axes** — the dimensions a lesson's `trigger` is scored on — each with a `weight`
  and a `match` strategy: `set` (case-insensitive overlap, e.g. tags, components), `glob`
  (bidirectional fnmatch, e.g. service names), or `glob_scalar` (a scalar context value vs a list
  of patterns, e.g. an HTTP endpoint vs `POST *`);
- a **controlled vocabulary** and **stopwords** used to auto-extract context from a free-text
  brief;
- the **enums** (categories, memory types, confidence multipliers) and **thresholds** (dedup,
  prune age, active cap).

The engine's scorer loops over `config.axes`; adding a `components` axis to the config gives you
`--components` on the CLI and a scored `trigger.components` with no code change. Two example
configs ship: a minimal `default` (tags + stages + free-text) and `software-eng` (tags,
components, work-types, source-systems, services, endpoint-patterns).

## The core decision: git, not a new service

The store and the distribution channel are the **same git repo**, chosen over standing up a
dedicated service.

| | **Git (chosen)** | Dedicated service |
|---|---|---|
| New infra | none | a service, its store, its on-call |
| Distribution | native (`git pull`) | every client calls an endpoint |
| Review / audit of new lessons | native (PR + `CODEOWNERS`) | build a review path |
| Recall quality | lexical + metadata (great for procedural/semantic rules) | can add vector recall |
| Operational cost | ~zero | real |

Two findings make git-first principled rather than a workaround. Hybrid retrieval — embedding
similarity *plus* metadata filters — is what real agents need, and structured key lookup already
works well for procedural rules and profiles; our lessons are exactly procedural/semantic rules
with strong metadata, so lexical+metadata recall fits the data. And file-based memory is
competitive in practice (Letta's filesystem memory scored 74% on LoCoMo, beating several
specialized memory libraries). Files in git are the right default, with a clean upgrade path
(the MCP server, or a vector index) if recall ever outgrows them.

## Architecture

**Two tiers, then N.** A captured lesson lands in the **local** tier (`memory/local.jsonl`,
gitignored) instantly — zero friction. It shapes only *your* work until you **promote** it:
`mnemosyne promote` proposes it for the **shared** tier (`memory/lessons.jsonl`, committed) through
a review PR. A reviewer approves before it becomes team-wide, so one bad lesson can't silently
poison everyone — the cost of a wrong shared lesson is high (it steers every future run), so it
gets a human gate. Agent proposes, human disposes.

**Merging the review PR is the approval.** There is no separate approve step. The lesson on the
review branch already carries `review.state: approved`; it takes effect when the PR merges into the
default branch. Until then the local original is **kept**, marked `proposed` with
`source.exported_to`, so it keeps steering your work and keeps its id. The next `sync` sees the
merged copy on the default branch and in the working tree, and retires the local original (status
`retired`, reason recorded, record kept).

Staging lives in the engine (`core.stage_review_pr`), not in any one surface, so the CLI, the MCP
`promote` tool and `mn.promote()` behave identically. It never touches a working tree: it builds
the review branch with git plumbing from the default branch (`origin/HEAD`, else `HEAD`) plus
exactly the promoted lesson, with `LESSONS.md` rendered to match. So nothing else that happens to
be uncommitted rides along, you stay on your branch, and a store's cached clone stays on its
default branch, where `sync` can see the merge. It returns the step left to run by hand (push, open
the PR); with `push` set it pushes too. Nothing in the engine opens or merges the PR. A memory repo
outside git has no review to wait for, so there `promote` moves the lesson straight into the shared
tier as `proposed`.

**Ids are never reused.** A new id is allocated above every id in the local tier, the working
tree's shared tier and the shared tier as committed on `HEAD`, the remote default branches and
every local or remote `reflexion/*` review branch. If a promoted lesson's id turns out to be taken
on a committed branch anyway (a teammate's lesson you hadn't fetched), the shared copy gets a fresh
id and records `source.exported_from`. When ids do collide, the reviewed shared record wins in
every view, and `validate` reports the collision rather than letting the local lesson vanish.

**Nothing leaves the local tier unscrubbed.** `promote`, `export` and `capture --shared` pass every
outgoing lesson through `core.scrub_lesson`. The author is `$MNEMOSYNE_AUTHOR`, else `unknown`,
never the OS login. Absolute anchor paths become repo-relative or are dropped, and home-directory,
drive, UNC and WSL paths in free text become `<path>`. A clean scrub is not clearance to publish;
the review PR stays the gate.

**Broader tiers (federation).** Beyond its own local+shared tiers, a repo can federate with
additional **stores** — separate mnemosyne memory repos declared in `config.stores`, each a broader
shared tier (e.g. `team`, `enterprise`). A store is addressed by a git **url** (mnemosyne clones it
into a cache — `$MNEMOSYNE_CACHE`, else `~/.mnemosyne/stores` — and `sync` pulls it), or a **path**
to an existing repo. Each store carries a distinct id **prefix** (e.g. `T`/`E`), which is what lets
federated lessons share one id space without ever colliding. `recall` reads the union of primary +
every store **already on disk**. It never touches the network: it never clones or pulls, and a store
that isn't fetched yet, or can't be read, is skipped with a note, never a failure. `sync` is the
network path: it clones missing stores and pulls the rest. (`export`, being a write, may also clone
the one store it writes to.) `promote --to <tier>` (or `export`) commits chosen local lessons *up*
to a store, scrubbed, under new store-prefixed ids on one review branch in *that* store's repo.
The local originals are kept and marked until the store's PR merges; the next `sync` then retires
them, leaving the store copies authoritative. A store that isn't a git repo has no PR to merge, so
`export` writes into it as `proposed` and `sync` retires an original only once its copy reads
`approved`. Usage tracking always writes to the primary gitignored sidecar; stores are read-only for
usage.

**Source of truth = the JSONL.** `memory/lessons.jsonl` is authoritative; `memory/LESSONS.md` is a
**generated** human view, regenerated on every write and committed so PR diffs are readable.
Lessons are authored **only through the engine** — never hand-edited — which keeps ids, stamps,
dedup, supersession, and the rendered view consistent. `mnemosyne validate` enforces the schema
and spine consistency.

**Crash-safe writes.** Every rewrite of a store file (`lessons.jsonl`, `local.jsonl`, the usage
sidecar, `LESSONS.md`) goes through `core.atomic_write_text`: write a temp file in the same
directory, `fsync` it, then `os.replace` it over the original (and, on POSIX, `fsync` the directory
so the rename itself survives a power cut). `os.replace` is atomic within one filesystem, so a
process killed mid-save leaves either the old file or the new one, never a truncated store. On
Windows a concurrent reader briefly holding the file open blocks the swap, so the replace retries a
few times.

**Serialised writers.** Atomicity alone does not stop a lost update: two processes that each read
the store, add a lesson and swap the file in would leave only the second one's lesson. So every
read-modify-write of a repo's store files (capture/reflect, promote, export, prune `--apply`,
sync's retire-on-merge, the usage bump, rendering `LESSONS.md` and validate's render-and-restore)
runs under `core.store_lock(repo)`, which holds the read, the change and the atomic write as one
step. It is an OS lock on `memory/.store.lock` (`fcntl.flock` on POSIX, `msvcrt.locking` on
Windows; stdlib only), not "the lockfile exists", so the kernel releases it when its holder exits
or crashes: a dead holder never wedges the store and there is no stale-lock cleanup to race over.
The lockfile is never deleted and is gitignored; it records the last holder's pid for diagnostics.
The lock is re-entrant within a process, and `export` (which writes the primary repo and a store
repo) takes both locks in sorted path order so two exports can't deadlock each other. A writer
waits at most `MNEMOSYNE_LOCK_TIMEOUT` seconds (default 10), then fails with `LockTimeout` (CLI
exit 4) naming the lock and its last holder. The usage bump is best-effort, so a recall that can't
get the lock skips the bump rather than failing. Reads take no lock: the atomic swap means a reader
always sees one whole version of each file.

**Thin by design.** The agent never reads the store. It runs one command and relays the one-line
result. All scanning, ranking, writing, git work, and validation live in the engine, keeping the
per-run token cost near zero.

## Recall algorithm

`recall` takes context — extracted from a brief (`--from-brief`) or given explicitly per axis —
and scores every active lesson by weighted overlap against its `trigger`: each axis contributes
`weight × matches`, a `--stage` match adds `stage_weight`, and free-text query keywords found in
the title/lesson add a small capped bump. An empty trigger gets a small floor so "always worth a
glance" lessons still surface. The sum is scaled by **confidence** (high 1.0 / medium 0.85 /
low 0.6). Top-N above a minimum score are returned, each with its **matched reasons** shown, and
the output capped to a character **budget** so the paste stays small. Deliberately transparent and
debuggable — no opaque similarity score.

## Hygiene — keeping signal above noise

A reflexion store's failure mode is the opposite of forgetting: it **accretes**. Five mechanisms
keep signal above noise.

1. **Don't bank missing-deliverable / transient failures.** Reflecting on "the build produced no
   output" or "a re-run fixed it" is a *process retry*, not a lesson. A guard refuses these
   (exit 3 / `LowValueError`) unless forced; a genuine domain failure (a trigger that didn't fire)
   is not matched and saves normally.
2. **Dedup by reinforcement.** On capture, the engine finds the best same-category near-duplicate
   (title+lesson Jaccard blended with tag Jaccard) and, at/above the threshold, **reinforces** it
   — bumping a counter (and eventually confidence) instead of adding a record.
3. **Track real usage without churning the store.** `recall` writes usage to a **gitignored
   sidecar** (`memory/usage.local.json`); prune/stats merge it with the authored baseline. Reads
   never produce noisy diffs that would fight the PR gate.
4. **Collapse at recall.** Even with dedup, seeds and edits can leave near-identical twins; recall
   drops the lower-scored one so a digest never spends its budget twice.
5. **Prune and cap.** `prune` retires — never deletes — aged, never-recalled, low/medium-confidence
   lessons and enforces an active cap (retiring lowest-value lessons over it; high-confidence and
   ever-recalled lessons are protected). Dry-run by default; `--apply` writes `status=retired` + a
   reason, keeping the record for audit.

## Transparency contract

Every command prints a quotable line the surfaces relay verbatim:

- **recall** → `RECALL: N reflexion lesson(s) applied … (L-…, L-…). Source: …` — the user sees what
  prior knowledge is steering the work and can veto any of it.
- **capture / reflect** → `SAVED: L-00NN captured to LOCAL reflexion memory — "…"` + the promote hint.
- **promote** → `PROMOTED: L-00NN committed alone on review branch reflexion/L-00NN …`.

Memory is never applied behind the user's back, and never shared unreviewed.

## Governance

Lessons are **superseded, never silently deleted** (`--supersede` marks the old one and links the
replacement), so the history of what was learned — and later corrected — stays auditable. When the
memory lives in its own git repo, use `docs/lesson-review-checklist.md` as the pull-request
template and `CODEOWNERS` to route shared-store changes to the right reviewers.

## Packaging

One engine, three delivery layers (see the [README](../README.md)):

- **CLI / library** — `mnemosyne …` or `import mnemosyne`; the stdlib foundation.
- **Claude Code plugin** — a skill + hooks (recall on prompt, sync on session start) + `/recall`,
  `/reflect`, `/promote` commands.
- **MCP server** — the same operations as MCP tools for any MCP client.

## References

- Shinn et al., *Reflexion: Language Agents with Verbal Reinforcement Learning*, NeurIPS 2023 — <https://arxiv.org/abs/2303.11366>
- *Types of AI Agent Memory (episodic/semantic/procedural)* — <https://atlan.com/know/types-of-ai-agent-memory/>
- *What Is AI Agent Memory?* (hybrid retrieval) — <https://www.ibm.com/think/topics/ai-agent-memory>
- *7 Steps to Mastering Memory in Agentic AI* (Letta filesystem / LoCoMo) — <https://machinelearningmastery.com/7-steps-to-mastering-memory-in-agentic-ai-systems/>
