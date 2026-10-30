"""Mnemosyne — a generic, git-backed reflexion memory for agent pipelines.

An agent (or a team) captures durable *lessons* from its work, recalls the relevant ones
into future work, and governs promotion of local lessons to a shared, PR-reviewed tier.
It implements the Reflexion loop (Shinn et al., 2023) with domain-agnostic, config-driven
recall axes and five hygiene mechanisms that keep signal above noise.

Public API (thin wrappers over the engine; each resolves a repo + config and returns data):

    import mnemosyne as mn
    mn.recall("migrating the ledger POST endpoint", stage="plan")     # -> [ {lesson...}, ... ]
    mn.capture("Page list endpoints at 50 by default",
               "Our standard pagination default is 50; propose it and confirm.",
               category="convention", tags="pagination,api")
    mn.reflect("Pin idempotency for every new POST endpoint",
               "Make the team decide the idempotency contract during intake.",
               reflection_of="A new POST double-posted on replay; idempotency was never specified.",
               tags="idempotency,replay", stage="plan")
    mn.promote("L-0009")
    mn.prune(apply=False)

`repo=` / `config=` override resolution (else $MNEMOSYNE_REPO / cwd and $MNEMOSYNE_CONFIG /
<repo>/mnemosyne.config.json / bundled default). Extra keyword args are treated as recall
context / lesson trigger axes (e.g. tags=..., services=...), so custom axes work with no
code change.
"""
from __future__ import annotations

from pathlib import Path

from . import core
from .config import Config, ConfigError, load_config, load_named_example
from .core import EngineError, LockTimeout, LowValueError, resolve_repo

__all__ = [
    "recall", "capture", "reflect", "promote", "export", "prune", "hygiene", "validate",
    "Config", "ConfigError", "EngineError", "LockTimeout", "LowValueError",
    "load_config", "load_named_example", "resolve_repo",
]

__version__ = "0.5.0"


def _prep(repo, config):
    repo_path = resolve_repo(repo)
    cfg = config if isinstance(config, Config) else load_config(config, repo_path)
    return cfg, repo_path


def recall(query=None, *, from_brief=None, stage=None, top=None, min_score=None,
           repo=None, config=None, as_text=False, **axes):
    """Return the lessons most relevant to the given context (list of dicts, or the text digest)."""
    cfg, repo_path = _prep(repo, config)
    from_text = Path(from_brief).read_text(encoding="utf-8") if from_brief else None
    ctx = core.build_recall_context(cfg, from_text=from_text, query=query, axes=axes, stage=stage)
    ranked, tier = core.recall(cfg, repo_path, ctx, top=top, min_score=min_score)
    if as_text:
        return core.render_digest(cfg, ranked, repo_path, tier, "text", cfg.recall_budget)
    return [{
        "id": l["id"], "title": l["title"], "category": l["category"], "confidence": l["confidence"],
        "tier": tier.get(l["id"], "shared"), "lesson": l["lesson"], "score": sc,
        "matched": why, "source": l.get("source", {}),
    } for l, sc, why in ranked]


def _fields(title, lesson, category, memory_type, confidence, rationale, stage, stages, spec,
            anchors, reflection_of, related, supersedes, shared, trigger, axes):
    trig = dict(trigger or {})
    trig.update(axes)
    return {
        "title": title, "lesson": lesson, "category": category, "memory_type": memory_type,
        "confidence": confidence, "rationale": rationale, "trigger": trig, "stage": stage,
        "stages": stages, "spec": spec, "anchors": anchors, "reflection_of": reflection_of,
        "related": related, "supersedes": supersedes, "shared": shared,
    }


def capture(title, lesson, *, category=None, memory_type=None, confidence="medium", rationale=None,
            stage=None, stages=None, spec=None, anchors=None, related=None, supersedes=None,
            shared=False, trigger=None, force=False, supersede=None, repo=None, config=None, **axes):
    """Save a decision/convention/... lesson to the local tier (or shared with shared=True)."""
    cfg, repo_path = _prep(repo, config)
    fields = _fields(title, lesson, category, memory_type, confidence, rationale, stage, stages,
                     spec, anchors, None, related, supersedes, shared, trigger, axes)
    return core.capture(cfg, repo_path, fields, force=force, supersede=supersede)


def reflect(title, lesson, reflection_of, *, category=None, memory_type=None, confidence="medium",
            rationale=None, stage=None, stages=None, spec=None, anchors=None, related=None,
            supersedes=None, shared=False, trigger=None, force=False, supersede=None,
            repo=None, config=None, **axes):
    """Save a reflexion lesson (learned-from-failure) captured from feedback on a prior run."""
    cfg, repo_path = _prep(repo, config)
    fields = _fields(title, lesson, category, memory_type, confidence, rationale, stage, stages,
                     spec, anchors, reflection_of, related, supersedes, shared, trigger, axes)
    return core.reflect(cfg, repo_path, fields, force=force, supersede=supersede)


def promote(lesson_id, *, to=None, push=False, repo=None, config=None):
    """Propose lesson(s) for a shared tier through a review PR; the local copy stays until it merges.

    Default (to=None or "shared"): commit a single local lesson alone on a review branch for this
    repo's shared tier. to=<store tier> (e.g. "team"): export the given id(s) UP to a configured
    store — see export(). The result's `pr` carries the remaining step (push, open the PR);
    push=True also pushes, exactly like `mnemosyne promote --push`. Merging the PR is the approval,
    and the next sync() retires the local copy."""
    cfg, repo_path = _prep(repo, config)
    if to in (None, "shared") and isinstance(lesson_id, str):
        return core.promote(cfg, repo_path, lesson_id, push=push)
    ids = [lesson_id] if isinstance(lesson_id, str) else list(lesson_id)
    return core.export(cfg, repo_path, ids, to, push=push)


def export(lesson_ids, to, *, push=False, repo=None, config=None):
    """Export chosen local lesson(s) UP to a broader shared store (team/enterprise, ...).

    Commits each lesson, scrubbed, under a new store-prefixed id on a review branch in the store repo
    and marks the local original for retire-on-merge. `to` is a tier label from config.stores;
    `lesson_ids` is one id or a list. Returns a dict describing the exported/skipped lessons and,
    under `pr`, the remaining step (push, open the PR), which push=True runs."""
    cfg, repo_path = _prep(repo, config)
    ids = [lesson_ids] if isinstance(lesson_ids, str) else list(lesson_ids)
    return core.export(cfg, repo_path, ids, to, push=push)


def prune(*, apply=False, cap=None, max_age_days=None, repo=None, config=None):
    """Retire (never delete) aged / over-cap low-value lessons. Dry-run unless apply=True."""
    cfg, repo_path = _prep(repo, config)
    return core.prune(cfg, repo_path, apply=apply, cap=cap, max_age_days=max_age_days)


def hygiene(*, cap=None, max_age_days=None, repo=None, config=None):
    """Report store health: duplicate pairs, never-recalled lessons, cap headroom, prune candidates."""
    cfg, repo_path = _prep(repo, config)
    return core.hygiene(cfg, repo_path, cap=cap, max_age_days=max_age_days)


def validate(*, repo=None, config=None):
    """Check schema + spine consistency; returns a result dict (ok / problems / counts)."""
    cfg, repo_path = _prep(repo, config)
    return core.validate(cfg, repo_path)
