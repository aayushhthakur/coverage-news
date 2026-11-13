"""Group closely related events into stories.

Events are linked when their centroids are at least `stories.threshold` similar
(the 0.75 event threshold keeps each angle of a big story separate). Linked
components are trimmed of members far from the component centroid, and only
components with at least `stories.min_events` events become stories.
Story ids are kept stable across runs by matching on member overlap.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np

from .config import scoring
from .embed import from_blob

STOP = {"the", "a", "an", "and", "of", "in", "on", "for", "to", "with", "after", "as", "at", "by", "from",
        "is", "are", "was", "what", "who", "how", "why", "says", "said", "new", "us", "u.s.", "it", "his",
        "her", "its", "this", "that", "will", "can", "be", "has", "have", "into", "over", "live", "latest",
        "analysis", "opinion", "explainer", "here", "these", "but", "not", "no"}
WORD = re.compile(r"[A-Za-z][\w'’.-]*[\w]|[A-Z]")


def components(vecs: np.ndarray, threshold: float, min_member_sim: float) -> list[list[int]]:
    n = len(vecs)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    sims = vecs @ vecs.T
    for i, j in zip(*np.where(np.triu(sims, 1) >= threshold)):
        parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = []
    for g in groups.values():
        if len(g) < 2:
            continue
        # trim chained-in outliers against the component centroid, twice (centroid moves)
        for _ in range(2):
            c = vecs[g].mean(0)
            c /= np.linalg.norm(c)
            g = [i for i in g if vecs[i] @ c >= min_member_sim]
        out.append(g)
    return out


def story_label(titles: list[str]) -> str:
    """Most widespread capitalised name across member headlines; a two-word name wins
    if it appears in at least as many headlines as its first word does alone."""
    uni, bi = Counter(), Counter()
    for t in titles:
        words = [re.sub(r"['’]s$", "", w).strip(".’'") for w in WORD.findall(t)]
        caps = [w for w in words[1:] if w[0].isupper() and w.lower() not in STOP] + \
               ([words[0]] if words and words[0].lower() not in STOP and words[0][0].isupper() else [])
        uni.update(set(caps))
        pairs = {f"{a} {b}" for a, b in zip(words, words[1:])
                 if a[0].isupper() and b[0].isupper() and a.lower() not in STOP and b.lower() not in STOP}
        bi.update(pairs)
    if not uni:
        return titles[0][:40]
    top, n = uni.most_common(1)[0]
    best_bi = next(((b, m) for b, m in bi.most_common() if top in b.split()), None)
    if best_bi and best_bi[1] >= 0.8 * n:
        return best_bi[0]
    return top


def group_stories(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    cfg = scoring()["stories"]
    now = now or datetime.now(timezone.utc)
    start = (now - timedelta(hours=scoring()["cluster_window_hours"])).isoformat()
    ev = conn.execute("SELECT id, centroid, story_id FROM events WHERE last_seen >= ?", (start,)).fetchall()
    if not ev:
        return {"stories": 0}
    ids = [e["id"] for e in ev]
    old = {e["id"]: e["story_id"] for e in ev}
    vecs = np.stack([from_blob(e["centroid"]) for e in ev])
    groups = [g for g in components(vecs, cfg["threshold"], cfg["min_member_sim"]) if len(g) >= cfg["min_events"]]

    conn.execute("UPDATE events SET story_id = NULL WHERE last_seen >= ?", (start,))
    claimed: set[int] = set()
    now_iso = now.replace(microsecond=0).isoformat()
    for g in sorted(groups, key=len, reverse=True):
        members = [ids[i] for i in g]
        overlap = Counter(old[m] for m in members if old[m] and old[m] not in claimed)
        titles = [r[0] for r in conn.execute(
            f"SELECT title FROM articles WHERE event_id IN ({','.join('?' * len(members))})", members)]
        label = story_label(titles)
        if overlap:
            sid = overlap.most_common(1)[0][0]
            conn.execute("UPDATE stories SET label=?, updated_at=? WHERE id=?", (label, now_iso, sid))
        else:
            sid = conn.execute("INSERT INTO stories (label, created_at, updated_at) VALUES (?,?,?)",
                               (label, now_iso, now_iso)).lastrowid
        claimed.add(sid)
        conn.executemany("UPDATE events SET story_id=? WHERE id=?", [(sid, m) for m in members])
    return {"stories": len(groups), "events_in_stories": sum(len(g) for g in groups)}


def story_topics(conn: sqlite3.Connection, story_id: int) -> tuple[list[str], list[str]]:
    """Labels carried by at least half the member events (always at least the most common)."""
    rows = conn.execute("SELECT topics, subtopics FROM events WHERE story_id=?", (story_id,)).fetchall()
    out = []
    for col in ("topics", "subtopics"):
        c = Counter(x for r in rows for x in json.loads(r[col] or "[]"))
        out.append([k for k, v in c.most_common() if v >= len(rows) / 2] or [k for k, _ in c.most_common(1)])
    return out[0], out[1]
