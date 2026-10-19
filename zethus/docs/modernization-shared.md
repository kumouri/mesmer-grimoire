# Zethus extension: shared modernization foundation

**Status:** PARTIAL (v1 built) · **Owner:** Ceryce Armstrong · **Date:** 2026-09-27 · **Related:**
[`batch-modernization.md`](batch-modernization.md), [`webapp-modernization.md`](webapp-modernization.md),
[`../README.md`](../README.md)

> This is a design spec, not a spec-full-template change. It has no phases of its own: the three
> artifacts it defines are built once, by whichever of the two consuming specs merges first, and
> the other spec then depends on them rather than re-specifying them. Status stays `DRAFT` until
> both consuming specs are at least `PARTIAL`.
>
> **2026-09-28:** the three shared artifacts are now built, by `batch-modernization.md`'s v1 (see
> its own status note) — the rule ledger shape (`zethus/scripts/_ledger.py`, JSON per open question
> 2's "B" recommendation), the constitution template (`zethus/templates/constitution.md`), and the
> overseer as three script-gates (`zethus/scripts/overseer-gate.py`, resolving open question 1 as
> already decided: A).
>
> **2026-09-28 (later the same day):** `webapp-modernization.md` also reaches `PARTIAL` with its own
> v1 build (see its status note), so per the rule above this document's status moves to `PARTIAL`
> too. The web-app build extends, rather than forks, the three shared artifacts: the constitution
> template gains two sections — **Session / state** and **Auth shim** — added to the *same* shared
> `templates/constitution.md` and to `_ledger.py`'s `REQUIRED_SECTIONS` (a batch constitution with
> no session or web-facing auth just marks both "No rule found," the same way any inapplicable
> section already works); the overseer gains two web-app-specific gates,
> `overseer-gate.py session-state` and `overseer-gate.py http-fixtures`, alongside — not replacing —
> its three original subcommands.

## The ask

Ceryce, Telegram, 2026-09-27 01:10 CT, from the todo that motivated both extensions (due
2026-10-02, priority critical):

> "a copilot pipeline to modernize batch jobs that reuses as much of zethus as possible. So
> basically just specialized skills to work with different DB backends, different batch job
> types, different SQL dialects, different modernized architectures, RECOVERS BUSINESS RULES FROM
> CODE AS MUCH AS POSSIBLE, builds a constitution that represents the exact legacy behaviour that
> must be replicated, etc.. And maybe a special agent — lol special agent — that ensures the
> process runs correctly?"

- **Answers:** what a business-rule-recovery skill and a "behaviour constitution" artifact are,
  in a form generic across languages and target types; what the "special agent" is and how it
  plugs into Zethus's existing stage table without duplicating it.
- **Does not answer:** anything specific to one legacy stack. That's each consuming spec's job —
  see [`batch-modernization.md`](batch-modernization.md) and
  [`webapp-modernization.md`](webapp-modernization.md).

## What is true today

| # | Fact | Where | How verified |
|---|---|---|---|
| F1 | Zethus's agent runs every change through a fixed seven-stage table (Orient, Research, Spec, Implement, Tests, Docs, Gates, PR), each with a named skill and an exit condition | `agents/zethus.agent.md:14-25` | read the stage table |
| F2 | A skill is a plain `SKILL.md` with only `name` and `description` frontmatter — no schema for a skill's own inputs or outputs beyond what its prose says | `skills/research-existing-code/SKILL.md:1-4` (representative of all ten) | read the frontmatter of all ten skill files |
| F3 | `research-existing-code` already requires every claim cited to `file:line`, every negative claim backed by the search that proved it, and an explicit "what this did not cover" section | `skills/research-existing-code/SKILL.md:12-44` | read the procedure |
| F4 | Config already has a documented resolution order (`.github/zethus.config.json` → `$ZETHUS_CONFIG` → `.copilot/zethus.config.json` → `.claude/amphion.config.json` → `~/.copilot/zethus/config.json` → discovery) and shares key names with Amphion | `README.md:229-282` | read the config table |
| F5 | `run-local-gates.py` discovers gates from `gates.steps`, or from Amphion's gate keys, or from the repo's own build files, and exits non-zero on red, `3` on partial | `README.md:58` | read the scripts table row |
| F6 | The kit ships exactly four templates (`spec-full`, `spec-minimum`, `adr`, `pr`) and five scripts (`run-local-gates`, `base-freshness`, `new-adr`, `new-spec`, `docs-pointer-check`); none reads source code or extracts anything from it | `README.md:38-64` | read the kit table |
| F7 | Nothing in `zethus/` today recovers rules from legacy source, produces a behaviour-pinning artifact, runs a golden-master/characterization test, or acts as a second enforcing agent | — | `grep -ri "constitution\|golden.master\|characterization\|overseer"` across the repo → 0 hits |
| F8 | Zethus is designed to compose with Amphion by sharing config keys and headings rather than duplicating stages, and explicitly says new axes of work should become config keys or skill families, not a parallel pipeline | `README.md:331-352` | read "How it relates to Amphion" |

**What this did not cover:** the scripts' internals beyond what their docstrings and the README
table describe (`run-local-gates.py`'s per-toolchain discovery logic was not read line-by-line);
Amphion's skills, beyond the parts of the Zethus README that describe the shared vocabulary; any
code outside `mesmer-grimoire`. The parked research on shipping Zethus as a Copilot plugin
(`2026-09-24-copilot-plugin-packaging.md`, not part of this repo) was read for compatibility only.

## Design

### Three shared artifacts

Both consuming specs plug the same three things into Zethus's existing pipeline. They are
specified once here so neither spec re-derives them, and so a future third modernization target
(a third legacy stack Zethus doesn't cover yet) can reuse them without touching either spec.

#### 1. Business-rule recovery (skill: `recover-business-rules`)

A skill in the shape of `research-existing-code` (F3), aimed at legacy source instead of a live
codebase question. Its job is to turn implicit behaviour — a magic number, a null check with no
comment, a `WHEN OTHERS THEN NULL` handler, a commented-out branch, a hard-coded holiday list —
into an explicit, numbered, citable rule.

- **Input:** one or more legacy source units (a Java class, a `ksh` script, a PL/SQL package body,
  a `.sql` migration, a JSP, a `web.xml`), plus the language/dialect context needed to read them.
- **Output — the rule ledger,** one row per rule:

  | # | Rule | Kind | Where (`file:line`) | Confidence | Why |
  |---|---|---|---|---|---|
  | R1 | Orders over $10,000 require a second approval | validation | `OrderValidator.java:142` | High | explicit `if` with a named constant |
  | R2 | Retry a failed remote call up to 3 times, 5 s apart | error-handling | `retry.ksh:31-38` | High | explicit loop and `sleep 5` |
  | R3 | The nightly run skips weekends | scheduling | `CRONTAB:4` @ crontab entry | Medium | inferred from `0 2 * * 1-5`; no comment confirms intent |

  - **Kind** is one of: validation, calculation, orchestration/ordering, side effect,
    error-handling, scheduling, formatting. Add a kind only when an existing one doesn't fit;
    don't invent a new one per rule.
  - **Confidence** is the same two-level discipline `fresh-eyes-investigation` already uses
    (established / conjecture, `skills/fresh-eyes-investigation/SKILL.md:33`), widened to three
    levels because legacy rule recovery routinely finds things that are readable but not certain:
    - **High** — the code states the rule outright (an explicit condition, a named constant, a
      documented format).
    - **Medium** — the rule is inferred from behaviour that has more than one plausible reading
      (a schedule expression with no comment, a default value that might be intentional or might
      be nobody having set it).
    - **Low** — the rule is a guess from naming or structure alone, with no behavioural evidence.
  - **Why** is one line: cite the read, or name the gap that keeps this from being High.
- **Rule:** every row needs a citation, exactly like `research-existing-code`. A rule with no
  citation is a hypothesis, not a recovered rule, and doesn't go in the ledger.
- **Format:** the ledger is a Markdown table (pastes into the constitution and the spec directly,
  matching every other Zethus artifact), with an optional companion YAML/JSON file
  (`rules/<unit>.yaml`, one entry per row, same fields) so the overseer (below) can check coverage
  mechanically instead of by re-reading prose. See [Open questions](#open-questions).

#### 2. The behaviour constitution (template: `templates/constitution.md`)

A new template, the same weight as `templates/adr.md`: one file, one field table, then sections,
plain Markdown, pastes cleanly into a wiki. Its job is to state, in one place, the legacy
behaviour that a modernization must reproduce exactly — not what the code *should* do, what it
*does* do, each line backed by rule ledger ids from artifact 1.

| Section | Captures | Backed by |
|---|---|---|
| Inputs | Parameters, files, env vars, request shapes, their formats and validation | rule ids |
| Outputs | Files, tables, messages, responses, their formats | rule ids |
| Side effects | External calls, notifications, writes outside the primary output | rule ids |
| Ordering | Sequencing and concurrency guarantees (or their absence) | rule ids |
| Error & restart semantics | What happens on failure mid-run: rollback, partial output, checkpoint, idempotency on rerun | rule ids |
| Commit / transaction boundaries | Where a unit of work commits, and what "done" means before that point | rule ids |
| File / message formats | Encodings, delimiters, fixed-width layouts, schemas | rule ids |
| Exit / status contract | Exit codes, HTTP statuses, error payloads, and what each means to the caller | rule ids |
| Scheduling / invocation contract | What triggers it, what it depends on, its SLA | rule ids |
| Session / state *(added 2026-09-28, web-app v1)* | Every session/state attribute, cited to `file:line`, classified into one of five stateless destinations (see [`webapp-modernization.md`](webapp-modernization.md)); a target with no clean HTTP boundary (a portlet, a JSF/Wicket/Vaadin component tree) records its component-state transitions here too | rule ids |
| Auth shim *(added 2026-09-28, web-app v1)* | The legacy authz mechanism preserved exactly behind an interface — roles, realms, session timeout — before any OAuth2/OIDC replacement, itself a later, separately decided phase | rule ids |

Each row is written as a **checkable statement**, not a description: "exits 0 only when every
input file was processed; exits 4 on a single record's validation failure without processing the
rest" reads as a test to write, where "handles validation errors" does not. A section with no
recovered rules says so explicitly ("no ordering guarantee found — treated as unordered until a
golden master says otherwise"), the same way an empty *Not covered* section in
`research-existing-code` is a stated result, not an omission (F3).

**When it's written:** during Stage 2 (Spec), as part of — not instead of — the spec's own "What
is true today" section (F3's citation discipline already lives there; the constitution is where
that discipline gets a legacy-behaviour-shaped home). **When it's checked:** before Stage 3
(Implement) may start, by the overseer below.

#### 3. Characterization / golden-master tests

Not a new skill so much as a required reading of `test-plan` and `implement-phase`'s existing
"Phase 0 changes no behaviour" rule (`skills/implement-phase/SKILL.md:27-29`) for modernization
work specifically: **Phase 0 is "capture the legacy behaviour the constitution describes as an
automated, replayable fixture," and it ships before anything is rewritten.** Each fixture pins one
constitution row: a recorded input plus the exact output/side-effect/exit-code the legacy code
produced for it, generated by running the *legacy* system, not by hand-authoring an expectation
from reading the code. `test-plan`'s mutation check (`skills/test-plan/SKILL.md:38-41`) applies
unchanged: break the ported/rewritten code on purpose and confirm the golden master catches it.

Both consuming specs give this its stack-specific shape (a DB/file fixture for batch, an
HTTP-level fixture for the web app); this document fixes only the shared rule: **a golden master
exists for every constitution row before that row's code may change**, and a row with no fixture
is an explicit gap the overseer refuses to let past, not a silent one.

#### 4. The overseer — a stage gate, not a second pipeline

The ask half-jokingly calls for "a special agent." The design choice is **not** a second Copilot
custom agent that competes with `zethus` for the session — that would duplicate the seven-stage
table F1 already owns, and Zethus's whole design principle is one enforcing pipeline, not two
(F8). Instead, the overseer is a **new exit-condition check at two existing stage boundaries**,
built the same way `base-freshness.py` already gates Stage 0 (F1, README.md:59): a script with an
unambiguous exit code, invoked by the `zethus` agent, not a second brain.

**Decided (2026-09-28):** this extension's v1 targets the Copilot CLI as its harness, matching the
base Zethus kit's own primary validation target (README.md's Copilot-client table); other Copilot
clients aren't excluded, just not what v1 is built and gated against.

| Stage boundary | Overseer checks | Exit 0 | Exit 1 |
|---|---|---|---|
| Before Stage 3 (Implement) starts | Every constitution section has content or an explicit "no rule found"; no `High`-impact row is still `Low` confidence without a recorded waiver (ADR) | proceed | list the gaps, refuse |
| Before Stage 4 (Tests) reports done | Every constitution row has a golden-master fixture id; the fixture actually ran against legacy output, not authored by hand | proceed | list uncovered rows, refuse |
| Any stage, on tool setup | A credential visible in the agent's own config/environment resolves to a higher environment than the one the run is configured for | proceed | flag the credential, refuse to use it |
| *(added 2026-09-28, web-app v1)* Before a flow may be marked migrated | Every session-state attribute cited by the flow is classified into one of five stateless destinations, and none is still read via `HttpSession` in the new code | proceed | list the unclassified/lingering attributes, refuse |
| *(added 2026-09-28, web-app v1)* Alongside the golden-master check | Every HTTP-shaped fixture has the fields a replay needs, and none looks like it captured real user data | proceed | list the gaps, refuse |

This reuses `base-freshness.py`'s pattern exactly: stdlib Python, one purpose, an exit code the
agent's refusal table can act on (`agents/zethus.agent.md:96-109` already has the shape for this —
"decline, and say why" — this just adds these rows). The credential row is a standing safety check
rather than a stage boundary: **v1's job stops at detection** — flagging the credential and
refusing to use it — not at remediation; reporting it to security and rotating it are left to the
human running the pipeline.

**Decided (2026-09-28): "script-gates now, agent later."** v1 ships deterministic script-gates at
these stage boundaries only — no second agent — resolving [Open questions](#open-questions)
question 1 below. A documented extension point is left for later: every gate above already produces
a plain exit code plus a gap list, and that pair is the contract an agent reviewer would consume
too, so a future agent-based check slots in as another consumer of the same contract — a richer
judgment call layered on top — not a rewrite of the script gates or the stage boundaries they sit
at. Building it is triggered by evidence, not schedule: once a real modernization run surfaces a gap
the deterministic checks structurally can't catch (a judgment call, not a missing citation or a
missing fixture id), that gap is the spec for the second `.agent.md`.

### Mapping onto Zethus's stages

| Zethus stage | Reused as-is | New for modernization |
|---|---|---|
| 0 · Orient | Unchanged: `base-freshness.py`, config resolution | — |
| 1 · Research | `research-existing-code`'s citation discipline (F3) | `recover-business-rules` — same discipline, aimed at legacy source, output is a rule ledger not a facts table |
| 2 · Spec | `write-spec-full` structure, sign-off, ADRs for every disposition decision | The constitution is authored inside the spec's "What is true today," backed by the rule ledger |
| — | — | **Overseer gate:** constitution completeness, before Implement opens |
| 3 · Implement | `implement-phase`'s Phase 0 rule, its classification table for unplanned work | Phase 0 is redefined, for this work only, as "golden masters exist for every constitution row" |
| 4 · Tests | `test-plan`'s mutation check | Golden-master fixtures generated from the legacy system, not authored |
| — | — | **Overseer gate:** every constitution row has a fixture, before Tests reports done |
| 5 · Docs | `docs-sync-check`, `docSync.map` | The constitution is a doc under the map: code changing without the constitution updating is exactly what `--sync-base` already flags (F5) |
| 6 · Gates | `run-local-gates.py`, `gates.steps` | A `characterization-suite` gate step, same mechanism, new command |
| 7 · PR | `zethus-pr-description`'s evidence sections | Evidence adds: rule-ledger coverage, constitution diff, golden-master pass table |

### What's new vs. reused

| Reused unchanged | New |
|---|---|
| Seven-stage pipeline, refusal model, sign-off rule | `recover-business-rules` skill |
| `write-spec-full` / `write-adr` / `test-plan` / `zethus-pr-description` procedures | `templates/constitution.md` |
| `run-local-gates.py`, `base-freshness.py`, config resolution order | Overseer stage-gate script(s) (three new exit-condition checks) |
| `docs-sync-check` + `docSync.map` | A confidence vocabulary (High/Medium/Low) for recovered rules |
| Branch models, PR template, gate mechanism | Per-stack characterization-test shape (specified per consuming spec) |

## Open questions

1. **Should the overseer stay a script-gate, or become a second `.agent.md` later?** Options:
   (A) script-gate only, as designed above; (B) a second custom agent from day one. **DECIDED
   (2026-09-28): A — script-gates now, agent later.** v1 ships deterministic script-gates at the
   stage boundaries above, reusing `base-freshness.py`'s proven shape and keeping one pipeline (F8);
   a documented extension point for adding an agent reviewer is left in the
   [overseer design](#4-the-overseer--a-stage-gate-not-a-second-pipeline) above, to be built once
   real modernization runs show what the script-gates miss — not on a fixed revisit schedule. ·
   Decided by: Ceryce.
2. **Markdown-only rule ledger, or Markdown plus a machine-checkable companion file?** Options:
   (A) Markdown table only; (B) Markdown plus a YAML/JSON ledger the overseer scripts read
   directly. **DECIDED (2026-09-28, batch v1): B**, as a JSON companion specifically
   (`rules/<unit>.json`, see `_ledger.py`) rather than YAML — the kit's scripts are stdlib-only, and
   JSON needs no hand-rolled parser the way YAML would. The overseer's coverage check (constitution
   row → fixture id) is exactly the kind of check `docs-pointer-check.py` already proves is worth
   scripting rather than eyeballing. · Decided by: implementer, per this question's own routing.
3. **Does a `Low`-confidence rule ever block a phase outright, or only require a recorded
   waiver?** Options: (A) always requires a waiver (ADR), never blocks by itself; (B) blocks
   automatically above some proportion of `Low` rows. **Recommended: A** — a hard numeric
   threshold invites gaming it by re-labelling rows; a waiver is a person's decision, recorded,
   same as every other Zethus decision. · Decides: Ceryce.
4. **Does `recover-business-rules` get one skill with per-language sections, or one skill per
   language/reader?** Options: (A) one skill, sectioned by source shape; (B) a skill per shape
   (Java, `ksh`, PL/SQL, SQL, JSP), each following a shared shape document. **Recommended: B** —
   matches Zethus's own "each skill works standalone" rule
   (`README.md:358-359`) and lets a consuming spec install only the readers its stack needs. ·
   Decides: whoever specs the first consuming skill's implementation.
