"""Steps 7–8: representative article and re-ranking.

The rules are pure functions over `Candidate`s so they can be tested without a database.
Clickbait demotion is applied inside the score itself (see scoring.score).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, replace

import numpy as np

from .config import publishers, scoring


@dataclass(frozen=True)
class Rep:
    article_id: int
    publisher: str
    tier: int            # 99 for publishers outside feeds.yaml
    clickbait: bool
    published_at: str


@dataclass(frozen=True)
class Candidate:
    event_id: int                         # event id, or story id when kind == "story"
    topic: str
    s: float
    v: float
    first_age_hours: float
    reps: tuple[Rep, ...]                 # in preference order, see order_reps
    subtopics: tuple[str, ...] = ()
    breaking: bool = False
    rep: Rep | None = None               # chosen representative after re-ranking
    kind: str = "event"                   # "event" | "story" (a group of 6+ related events)
    label: str = ""                       # story label, e.g. "Nvidia"
    extra: dict = field(default_factory=dict, compare=False, hash=False)


def order_reps(reps: list[Rep]) -> tuple[Rep, ...]:
    """Highest tier first, non-clickbait headlines before flagged ones, earliest report first.
    One entry per publisher (its earliest article)."""
    seen, out = set(), []
    for r in sorted(reps, key=lambda r: (r.clickbait, r.tier, r.published_at)):
        if r.publisher not in seen:
            seen.add(r.publisher)
            out.append(r)
    return tuple(out)


def dedupe(cands: list[Candidate]) -> list[Candidate]:
    """One entry per event or story (the highest-scoring row), sorted by S."""
    best: dict[tuple[str, int], Candidate] = {}
    for c in cands:
        k = (c.kind, c.event_id)
        if k not in best or c.s > best[k].s:
            best[k] = c
    return sorted(best.values(), key=lambda c: -c.s)


def mark_breaking(cands: list[Candidate], max_age_hours: float, percentile: float) -> list[Candidate]:
    """Breaking = under max_age_hours since first report and V in the topic's top (100-percentile)%.
    V must be positive: with V mostly 0, the percentile alone would tag everything."""
    if not cands:
        return cands
    thr = float(np.percentile([c.v for c in cands], percentile))
    return [replace(c, breaking=c.first_age_hours < max_age_hours and c.v > 0 and c.v >= thr) for c in cands]


def breaking_boost(ordered: list[Candidate], top_n: int = 3) -> list[Candidate]:
    """Move breaking events into the top `top_n`. The top slots hold the breaking events
    (best S first, at most top_n) plus the best of the rest, ordered by S."""
    br = [c for c in ordered if c.breaking][:top_n]
    rest = [c for c in ordered if c not in br]
    head = sorted(br + rest[: top_n - len(br)], key=lambda c: -c.s)
    return head + [c for c in rest if c not in head]


def _pick_rep(c: Candidate, used: dict[str, int], cap: int) -> Rep | None:
    return next((r for r in c.reps if used.get(r.publisher, 0) < cap), None)


def cap_and_select(ordered: list[Candidate], top_n: int, max_per_publisher: int,
                   max_per_topic: int | None = None) -> list[Candidate]:
    """Walk the ordered list, choosing a representative for each event so that no publisher
    supplies more than `max_per_publisher` of the top_n. An event whose every candidate
    publisher is used up (or whose topic is full, on home) is skipped for a later one."""
    used: dict[str, int] = {}
    per_topic: dict[str, int] = {}
    out: list[Candidate] = []
    for c in ordered:
        if len(out) == top_n:
            break
        if max_per_topic is not None and per_topic.get(c.topic, 0) >= max_per_topic:
            continue
        rep = _pick_rep(c, used, max_per_publisher)
        if rep is None:
            continue
        used[rep.publisher] = used.get(rep.publisher, 0) + 1
        per_topic[c.topic] = per_topic.get(c.topic, 0) + 1
        out.append(replace(c, rep=rep))
    return out


def rank_topic(cands: list[Candidate], cfg: dict, subtopic: str | None = None) -> list[Candidate]:
    b, r = cfg["breaking"], cfg["rerank"]
    ordered = mark_breaking(dedupe(cands), b["max_age_hours"], b["velocity_percentile"])
    if subtopic:
        ordered = [c for c in ordered if subtopic in c.subtopics]
    return cap_and_select(breaking_boost(ordered, b["top_n"]), r["top_n"], r["max_per_publisher"])


def rank_home(cands_by_topic: dict[str, list[Candidate]], primary: set[tuple[str, int, str]], cfg: dict) -> list[Candidate]:
    """Home: each event once, under its primary topic, by S; at most max_per_topic_home per topic.
    Breaking tags come from each topic's own percentile."""
    b, r = cfg["breaking"], cfg["rerank"]
    pool = []
    for topic, cands in cands_by_topic.items():
        marked = mark_breaking(dedupe(cands), b["max_age_hours"], b["velocity_percentile"])
        pool += [c for c in marked if (c.kind, c.event_id, topic) in primary]
    return cap_and_select(dedupe(pool), r["top_n"], r["max_per_publisher"], r["max_per_topic_home"])


# ---- database loading -------------------------------------------------------------------

def _reps_for(conn: sqlite3.Connection, where: str, params: tuple, tiers: dict) -> list[Rep]:
    return [Rep(a["id"], a["publisher"], tiers.get(a["publisher"], 99) if a["known"] else 99,
                bool(a["clickbait"]), a["published_at"])
            for a in conn.execute(f"SELECT id, publisher, known, clickbait, published_at FROM articles "
                                  f"WHERE {where}", params)]


def load_candidates(conn: sqlite3.Connection) -> tuple[dict[str, list[Candidate]], set[tuple[str, int, str]]]:
    """Ranking pool: stories, plus events that are not part of a story."""
    from .stories import story_topics

    tiers = {n: p["tier"] for n, p in publishers().items()}
    rows = conn.execute(
        "SELECT s.*, e.subtopics, e.story_id, st.label FROM scores s "
        "LEFT JOIN events e ON s.kind = 'event' AND e.id = s.event_id "
        "LEFT JOIN stories st ON s.kind = 'story' AND st.id = s.event_id"
    ).fetchall()
    event_s = {r["event_id"]: r["s"] for r in rows if r["kind"] == "event" and r["is_primary"]}
    by_topic: dict[str, list[Candidate]] = {}
    primary = set()
    rep_cache: dict[tuple[str, int], tuple[Rep, ...]] = {}
    for r in rows:
        if r["kind"] == "event" and r["story_id"] is not None:
            continue                      # shown inside its story instead
        key = (r["kind"], r["event_id"])
        if key not in rep_cache:
            if r["kind"] == "event":
                reps = order_reps(_reps_for(conn, "event_id=?", (r["event_id"],), tiers))
            else:
                # lead with the best-scoring sub-event's preferred articles, then the rest
                members = sorted((e[0] for e in conn.execute("SELECT id FROM events WHERE story_id=?",
                                                              (r["event_id"],))),
                                 key=lambda e: -event_s.get(e, 0))
                ordered: list[Rep] = []
                for m in members:
                    ordered += order_reps(_reps_for(conn, "event_id=?", (m,), tiers))
                reps = order_reps_keep_order(ordered)
            rep_cache[key] = reps
        subtopics = (json.loads(r["subtopics"] or "[]") if r["kind"] == "event"
                     else story_topics(conn, r["event_id"])[1])
        by_topic.setdefault(r["topic"], []).append(Candidate(
            event_id=r["event_id"], topic=r["topic"], s=r["s"], v=r["v"], first_age_hours=r["first_age_hours"],
            reps=rep_cache[key], subtopics=tuple(subtopics), kind=r["kind"], label=r["label"] or "",
            extra=dict(r),
        ))
        if r["is_primary"]:
            primary.add((r["kind"], r["event_id"], r["topic"]))
    return by_topic, primary


def order_reps_keep_order(reps: list[Rep]) -> tuple[Rep, ...]:
    """Like order_reps, but keeps the given order apart from moving clickbait last
    and keeping one entry per publisher."""
    seen, out = set(), []
    for r in sorted(reps, key=lambda r: r.clickbait):   # stable sort
        if r.publisher not in seen:
            seen.add(r.publisher)
            out.append(r)
    return tuple(out)


def ranked(conn: sqlite3.Connection, topic: str | None = None, subtopic: str | None = None) -> list[Candidate]:
    by_topic, primary = load_candidates(conn)
    cfg = scoring()
    if topic is None:
        return rank_home(by_topic, primary, cfg)
    return rank_topic(by_topic.get(topic, []), cfg, subtopic)
