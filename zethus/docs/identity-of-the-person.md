# Name the person Zethus works for, never a placeholder

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-19 |
| Deciders | Ceryce Armstrong |
| Recorded by | Claude Code (AI agent). It wrote this record; the *Choices made inside the ask* below are its proposals, which stand once the change is merged |
| Source | Ceryce's report, 2026-11-19, paraphrased below |
| Enforced where | [`../scripts/_identity.py`](../scripts/_identity.py) (`resolve`, `require`, `is_placeholder`); [`../scripts/identity.py`](../scripts/identity.py); [`../scripts/new-adr.py`](../scripts/new-adr.py) and [`../scripts/new-spec.py`](../scripts/new-spec.py) (no `TBD` default; exit 2 instead of a placeholder); the `sessionStart` hook, [`../com.github.copilot/hooks/session_start.py`](../com.github.copilot/hooks/session_start.py); the templates (`adr.md`, `spec-full.md`, `spec-minimum.md`, `pr.md`, `constitution.md`); the `write-adr`, `write-spec-full`, `write-spec-minimum` and `zethus-pr-description` skills; [`../copilot-instructions.md`](../copilot-instructions.md) (*Who you work for*); the agent's Stage 0 row and *How you behave at every turn*; `tests/test_zethus_identity.py` |
| Supersedes | — |
| Superseded by | — |

## Decision

Every doc Zethus writes names the real person who asked for, approved or decided something, as
they write their name, resolved in this order, with each step and the winning source in the run
log:

1. **Config:** `identity.name` and `identity.handle`, the person's own choice, read from every
   config file, most personal first.
2. **Git:** `git config user.name` in the repo being worked in.
3. **The forge account:** `gh api user`, its name, else its login.
4. **Nobody found:** ask the person once, at the start of the session, and offer to save the
   answer to config. Never write a placeholder.

The agent records itself only as the author of the text (*Written by*, *Recorded by*), never as
an owner, approver or decider.

## Context

Ceryce's report, paraphrased: Zethus has no way to tell who it is working for, so in its ADRs and
other docs, wherever it records who asked for, approved or decided something, it writes
"Requester" or a similar stand-in.

The code showed why. `new-adr.py` defaulted `--deciders` to `TBD`, `new-spec.py` defaulted
`--owner` to `TBD`, and the spec templates' ask section quoted "the requester's exact words". No
script, skill or hook knew a name, so the agent filled the gaps with role words. A record whose
decider is `TBD` is no record of who decided: the one fact an ADR exists to keep is missing, and
nothing flagged it.

## How it works now

- **One resolver.** [`../scripts/_identity.py`](../scripts/_identity.py) holds the order above.
  The first source that yields a name or a handle wins whole; fields are never mixed across
  sources, so each answer traces to one place. `identity.py` reports it, with the trace, and the
  agent runs it at Stage 0.
- **The scripts fill it in.** `new-adr.py` writes *Deciders* and `new-spec.py` writes *Owner* and
  *Requested by* from the resolver unless a flag names someone else. With no one to name, or a
  flag that is a placeholder (`TBD`, `Requester`, `the user`, `<name>` …), they write nothing and
  exit 2, telling the agent to ask.
- **The session starts knowing.** The plugin's `sessionStart` hook resolves offline (config, then
  git) and announces the name with the working agreement, or says it found none.
- **Asking.** When nothing resolves, the agent asks once with the harness's question tool and
  offers to save the answer; on a yes, `identity.py --save --name "…"` merges `identity` into
  `~/.copilot/zethus/config.json`, or with `--to repo` into the repo's untracked
  `.copilot/zethus.config.json`. Never into the committed `.github/zethus.config.json`.
- **Both hosts.** Resolution lives in a stdlib script, not in a host feature, so it runs the same
  under the Copilot CLI, VS Code, IntelliJ and Claude Code. The hook is a Copilot convenience on
  top; where it doesn't run (repo mode, Claude Code), the agent's Stage 0 call does the same work.
  The question tool is the host's own (`ask_user`, `AskUserQuestion`, …), as
  [ask with the question tool](ask-with-the-question-tool.md) already says.

### Choices made inside the ask

- **Most personal config first, for identity only.** Every other key comes from the first config
  file found. Identity is about the person, not the project: a team's committed config naming one
  person would put that name on every teammate's records, and a committed file that merely exists
  must not hide each person's own file. So `identity.py` reads every config, personal ones first.
- **The forge step is lazy.** `gh api user` is a network call. It runs only when config and git
  both gave nothing, with a timeout, and `ZETHUS_IDENTITY_FORGE=off` or `--no-forge` skips it.
  The hook always skips it: it has ten seconds and must never wait on the network.
- **No email.** `git config user.email` would answer when `user.name` doesn't, but every ADR and
  spec is committed, often to a public repo, and an address there is a leak. Only names and
  handles are written.
- **The log holds no values.** The run log records each step, whether it gave a name, a handle or
  an error, and which source won, never the name itself. A log is for debugging, and the
  [log from the start](log-from-the-start.md) rule keeps personal data out of it.
- **Names as written.** No case change, no `@` added, no splitting into first and last.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — a resolver: config, git, forge, then ask once | The order above, in one stdlib module every script, skill and hook uses | One module, one CLI, a lazy network call that rarely runs | **Chosen** |
| B — always ask the person | No resolution; a question at the start of every session | A question the repo could have answered, every session | Declined |
| C — config only | `identity.name` or nothing | Every user must set it first; until then the placeholders stay | Declined |
| D — keep `TBD` and fix it in review | Nothing changes | The reviewer becomes the only check, and the report shows it isn't one | Declined |

## Consequences

- **Easier:** a record says who decided without anyone filling it in, and the source is traceable.
- **Harder:** `new-adr.py` and `new-spec.py` can now fail where they used to write `TBD`. That
  failure is the point: it puts the question to the person instead of into the record.
- **New obligations:** any new template field or skill step that records a person goes through the
  resolver and names the agent only as author. `tests/test_zethus_identity.py` pins the order, the
  refusal of placeholders, the log, and the wording in the templates, skills, agent and agreement.

## Why not the others

- **B:** asks for what git already knows, every session, which is the friction the
  [question tool decision](ask-with-the-question-tool.md) set out to cut.
- **C:** leaves every install without config exactly where the report found it.
- **D:** the report is the evidence that review doesn't catch it.

## Revisit when

A host exposes the signed-in person's identity to agents directly (a documented variable or tool),
which would make a better step 2 than git; or a forge other than GitHub needs step 3.
