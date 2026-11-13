"""Steps 5–6: publisher-count snapshots and event scores.

    C = log(1 + P) / log(1 + N)
    V = publishers added in the last hour / P   (0 if P < velocity_min_publishers)
    T = Tier 1 publishers covering the event / size of the topic's Tier 1 list
    S = (wC*C + wV*V + wT*T) * 2^(-a/h)   (x0.5 if every headline is clickbait)

P counts distinct feeds.yaml publishers, never articles.
"""
from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta, timezone

from .clickbait import is_clickbait
from .config import publishers, scoring, tier1_list


# ---- pure functions (unit-tested) -------------------------------------------------

def coverage(p: int, n: int) -> float:
    return math.log1p(p) / math.log1p(n) if n > 0 else 0.0


def velocity(added_last_hour: int, p: int, min_publishers: int = 3) -> float:
    if p < min_publishers or p == 0:
        return 0.0
    return min(max(added_last_hour, 0), p) / p


def tier_score(tier1_covering: int, tier1_size: int) -> float:
    return tier1_covering / tier1_size if tier1_size else 0.0


def decay(age_hours: float, half_life: float) -> float:
    return 2 ** (-max(age_hours, 0.0) / half_life)


def score(c: float, v: float, t: float, age_hours: float, half_life: float,
          weights: dict, all_clickbait: bool = False, clickbait_multiplier: float = 0.5) -> float:
    s = (weights["coverage"] * c + weights["velocity"] * v + weights["tier"] * t) * decay(age_hours, half_life)
    return s * clickbait_multiplier if all_clickbait else s


# ---- database stage -----------------------------------------------------------------

def _hours(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 3600


def flag_clickbait(conn: sqlite3.Connection) -> None:
    for r in conn.execute("SELECT id, title FROM articles WHERE clickbait IS NULL").fetchall():
        conn.execute("UPDATE articles SET clickbait=? WHERE id=?", (int(is_clickbait(r["title"])), r["id"]))


def _score_item(conn: sqlite3.Connection, kind: str, item_id: int, arts: list, topics: list[str],
                now: datetime, now_iso: str, hour_ago: str, cfg: dict, n_total: int) -> int:
    """Snapshot and score one event or story from its articles (sorted by published_at)."""
    first_by_pub: dict[str, str] = {}
    for a in arts:
        if a["known"]:
            first_by_pub.setdefault(a["publisher"], a["published_at"])
    p = len(first_by_pub)
    conn.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)", (kind, item_id, now_iso, p))

    # Publishers added in the last hour: compare with the latest snapshot at least an
    # hour old; if none exists yet (first runs), fall back to article timestamps.
    prev = conn.execute(
        "SELECT publishers FROM snapshots WHERE kind=? AND event_id=? AND taken_at<=? "
        "ORDER BY taken_at DESC LIMIT 1", (kind, item_id, hour_ago),
    ).fetchone()
    baseline = prev["publishers"] if prev else sum(t <= hour_ago for t in first_by_pub.values())
    added = max(p - baseline, 0)

    age = _hours(now, datetime.fromisoformat(arts[-1]["published_at"]))
    first_age = _hours(now, datetime.fromisoformat(arts[0]["published_at"]))
    all_cb = all(a["clickbait"] for a in arts)
    for i, topic in enumerate(topics):
        t1 = tier1_list(topic)
        t1_cov = len(t1 & first_by_pub.keys())
        c = coverage(p, n_total)
        v = velocity(added, p, cfg["velocity_min_publishers"])
        t = tier_score(t1_cov, len(t1))
        h = cfg["half_life_hours"][topic]
        s = score(c, v, t, age, h, cfg["weights"], all_cb, cfg["clickbait_all_flagged_multiplier"])
        conn.execute(
            "INSERT INTO scores VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (kind, item_id, topic, int(i == 0), p, added, t1_cov, len(t1), c, v, t, age, first_age,
             decay(age, h), int(all_cb), s, now_iso),
        )
    return len(topics)


def snapshot_and_score(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    from .stories import story_topics

    cfg = scoring()
    now = now or datetime.now(timezone.utc)
    now_iso = now.replace(microsecond=0).isoformat()
    hour_ago = (now - timedelta(hours=1)).isoformat()
    window_start = (now - timedelta(hours=cfg["cluster_window_hours"])).isoformat()
    n_total = len(publishers())
    flag_clickbait(conn)
    conn.execute("DELETE FROM scores")
    args = (now, now_iso, hour_ago, cfg, n_total)
    cols = "publisher, known, published_at, clickbait"
    rows = 0

    # Every event is scored (sub-events need scores to order them inside a story).
    events = conn.execute("SELECT id, topics FROM events WHERE last_seen >= ? AND topics IS NOT NULL",
                          (window_start,)).fetchall()
    for e in events:
        arts = conn.execute(f"SELECT {cols} FROM articles WHERE event_id=? ORDER BY published_at",
                            (e["id"],)).fetchall()
        rows += _score_item(conn, "event", e["id"], arts, json.loads(e["topics"] or "[]"), *args)

    # Stories are scored over the union of their members' articles: P, V and T count
    # distinct publishers across every angle of the story.
    stories = conn.execute("SELECT DISTINCT story_id FROM events WHERE story_id IS NOT NULL "
                           "AND last_seen >= ?", (window_start,)).fetchall()
    for (sid,) in stories:
        arts = conn.execute(
            f"SELECT {cols} FROM articles WHERE event_id IN (SELECT id FROM events WHERE story_id=?) "
            "ORDER BY published_at", (sid,)).fetchall()
        rows += _score_item(conn, "story", sid, arts, story_topics(conn, sid)[0], *args)

    conn.execute("DELETE FROM snapshots WHERE taken_at < ?", (window_start,))
    return {"events_scored": len(events), "stories_scored": len(stories), "score_rows": rows}
