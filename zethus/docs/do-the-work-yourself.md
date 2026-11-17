# Do the work yourself: stop for the person only at what only they can give

| Field | Value |
|---|---|
| Status | Accepted |
| Date | 2026-11-10 |
| Deciders | Ceryce Armstrong |
| Source | Ceryce's request after the self-rebase change, 2026-11-10 (below) |
| Enforced where | *Keep moving, and never stop silently* in [`../copilot-instructions.md`](../copilot-instructions.md); the exit-3 row of the freshness table in [`../com.github.copilot/agents/zethus.agent.md`](../com.github.copilot/agents/zethus.agent.md); *When the fetch fails*, step 3's exit table and the CI rule in [`../skills/pre-push-gates/SKILL.md`](../skills/pre-push-gates/SKILL.md); *Step 4* of [`../skills/zethus-pr-description/SKILL.md`](../skills/zethus-pr-description/SKILL.md); the messages of [`../scripts/base-freshness.py`](../scripts/base-freshness.py), [`../scripts/run-local-gates.py`](../scripts/run-local-gates.py), [`../scripts/hla-input-check.py`](../scripts/hla-input-check.py), [`../scripts/webapp-hla-input-check.py`](../scripts/webapp-hla-input-check.py) and [`../com.github.copilot/hooks/session_start.py`](../com.github.copilot/hooks/session_start.py); the hand-off, fetch and red-CI refusals in [`../com.github.copilot/hooks/stop_guard.py`](../com.github.copilot/hooks/stop_guard.py); `tests/test_zethus_no_handoffs.py` |
| Supersedes | — |
| Superseded by | — |

## Decision

A job the agent can do with its own tools (git, the shell, the kit's scripts, the gates, the CLIs
its skills wrap) is the agent's job. It never stops to hand one to the person, and never ends a
turn on one. It stops for the person only at something only they can give: a sign-off, a decision,
an approval (a merge, a write outside the repo, anything destructive), a credential or access they
hold, or physical presence. Before that stop it does everything up to it, and the stop names the
one thing left.

## Context

The day before, the agent had been stopping at a stale base to ask the person to rebase, when it
could rebase itself; that was fixed on 2026-11-10
([amendment](base-freshness-cadence.md#amendment-2026-11-10-zethus-rebases-a-stale-branch-itself)).
Ceryce's follow-up, paraphrased: look for every other place the agent asks a person to do work it
should be doing itself.

So every instruction surface was audited: both agent files, the working agreement, every skill,
these records, the README, the templates, every script's messages and both hooks. Each place the
agent stops, ends a turn or tells the person to run, fix, install or check something was put in one
of three classes:

| Class | Meaning | Hits |
|---|---|---|
| (a) | Work the agent can do itself. Fixed: the agent now does it and carries on | 18 |
| (b) | A real human gate: sign-off, a decision, an approval, a credential or access, physical presence. Kept, and 8 of them tightened so the agent does everything up to the gate first | 29 |
| (c) | Unclear. Behaviour kept, listed for Ceryce with a recommendation | 13 |

The (a) hits, each now the agent's:

| Was handed to the person | Now |
|---|---|
| A failed fetch (`base-freshness` exit 3) stopped the turn with "say so", and the script suggested `--no-fetch` as a way round | The agent retries and diagnoses it (*When the fetch fails*); it stops only for a credential or network access, naming it |
| A gate with only a prose `expect` was listed MANUAL and never run, so the reviewer got it unchecked | `run-local-gates` runs it and prints the output; the agent judges it against `expect` and reports its verdict |
| The SKIP verdict said only "say so in the PR" | It says to install the toolchain and re-run; only a gate the machine can't run goes to *What was not checked* |
| Red CI on the agent's own PR was "surfaced" for a person, and the done stop never read CI | The agent reads its checks, and fixes a red one on the phase's branch (`zethus-pr-description` step 4); only merging or waiving is the person's |
| The duplicate-install hook told the person to run the migration command | The agent offers it with the question tool and runs it on a picked yes |
| A missing or moved HLA document stopped the modernization pipeline to ask | The check lists HLA-looking docs in the repo; the agent fixes `modernization.hlaDoc` and asks only when none fits |
| A JSP scriptlet's behaviour "needs a person reading the block" | The agent reads the block, as `recover-business-rules` does |
| Jira transitions needed a human-supervised interactive `move` | The agent reads them over REST, read-only |
| SonarQube: `sonar-scanner` was the reader's to fetch from the docs | The agent looks for it in the build (Maven, Gradle, npm) first |
| SonarQube: after a write, the person was given the read-back command | The agent runs the read-back itself |
| SonarQube: a pending analysis was "reported" | The agent polls it, within the background-wait bound |
| Datadog: the IDs were returned "so the user can verify" | The agent reads the change back itself |
| Jenkins: the build number was returned "so the user can follow along" | The agent follows the build when the task needs its result |
| Jenkins: a missing JRE stopped the jar commands | The agent uses the REST equivalent |
| Jenkins on CloudBees: the jar was the reader's to download | The agent fetches it from `<JENKINS_URL>/jnlpJars/jenkins-cli.jar` |
| The working agreement said nothing general about who does the work | One rule: work with the agent's own tools is the agent's |
| The stop guard accepted any `Why:` with "waiting on you" or "answer" in it, including "waiting on you to run the install" | It refuses a `Why:` that waits on the person to do work, unless it names what only they can give |
| The stop guard accepted any failed-fetch stop | It refuses one that doesn't name the cause left for the person |

The (b) gates that were tightened, so the agent works up to them first: the HLA's disposition,
frontend and auth answers (the agent writes the person's answer into the HLA); a batch scheduler's
dependency cycle (the agent rules out a misread convention first); a Jira 401 or 403 (the agent
rules out its own config first); a Jenkins abort (the agent works out the build number itself);
installing `jira-cli` or `sonarqube-cli` (an offer the agent runs on yes, not a report); triggering
a SonarQube scan (an offer, not a suggestion); and a story to enrich (the agent looks for a local
draft before asking for a paste).

The (b) gates kept as they were include spec sign-off, every decision put with the question tool,
the merge, every write to Jira, Confluence, Datadog, Jenkins or SonarQube, a destructive delete, an
expired token or a missing scope, a VPN, a rebase conflict the spec can't settle, a gate-remediation
or waiver ruling, a stuck branch after the fresh-eyes leads, the refusals, and carrying a
session-review report out.

## Options considered

| Option | What it means | What it costs | |
|---|---|---|---|
| A — fix each hand-off where it lives, one general rule, and a guard | Each skill or script does its own step; the working agreement says who does the work; the stop guard refuses a hand-off | Edits across many files, one hunk in the agent file | **Chosen** |
| B — a general rule in the agent file only | One paragraph saying "do it yourself" | Every skill would still say otherwise, and a customized agent file would take a large hunk | Declined |
| C — guard only | Refuse hand-off stops, change no text | The text would keep instructing the hand-off the guard refuses | Declined |

## Consequences

- **Easier:** a stop now means the person really is the only one who can act, and its `Why:` names
  what they need to give.
- **Harder:** the agent spends longer before some stops (a retried fetch, a repo search for the
  HLA, a CI fix), and installs nothing without a picked yes.
- **Kept small in the agent file on purpose:** the agent file changes one row, the exit-3 row of
  the freshness table, which now points at *When the fetch fails*. Everything else lives in the
  skills, the scripts and the working agreement, so a customized agent file can take the change by
  hand.
- **New obligations:** a new skill or script message that stops names the one thing only the
  person can give. `tests/test_zethus_no_handoffs.py` scans every instruction surface for wording
  that hands the person a job, with an allow-list that says why each remaining gate is real.
- **Limits:** the guard reads the `Why:` line only. A `Why:` that names a credential it never
  checked gets through, as any wall named but not reached does
  ([never stop silently](never-stop-silently.md)).
