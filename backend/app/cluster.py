"""Step 4: group articles into events.

Incremental, so event ids stay stable across runs (snapshots depend on that):
new articles are taken in publication order and each joins the open event whose
centroid is most similar, if that similarity reaches the threshold; otherwise it
starts a new event. An event is open to an article only while the article is
within `cluster_window_hours` of the event's first report.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta

import numpy as np

from .config import scoring
from .embed import from_blob, to_blob


def _event_labels(conn: sqlite3.Connection, event_id: int) -> tuple[list[str], list[str]]:
    """Event topics: labels carried by at least half the members (always at least the most common)."""
    rows = conn.execute("SELECT topics, subtopics FROM articles WHERE event_id=?", (event_id,)).fetchall()
    out = []
    for col in ("topics", "subtopics"):
        c = Counter(x for r in rows for x in json.loads(r[col] or "[]"))
        keep = [k for k, v in c.most_common() if v >= len(rows) / 2] or [k for k, _ in c.most_common(1)]
        out.append(keep)
    return out[0], out[1]


def cluster(conn: sqlite3.Connection, threshold: float | None = None) -> dict:
    cfg = scoring()
    threshold = cfg["cluster_threshold"] if threshold is None else threshold
    window = timedelta(hours=cfg["cluster_window_hours"])

    new = conn.execute(
        "SELECT id, published_at, embedding FROM articles "
        "WHERE event_id IS NULL AND embedding IS NOT NULL ORDER BY published_at"
    ).fetchall()
    if not new:
        return {"assigned": 0, "new_events": 0}
    earliest = datetime.fromisoformat(new[0]["published_at"]) - window
    ev_rows = conn.execute(
        "SELECT id, first_seen, last_seen, centroid, n_articles FROM events WHERE first_seen >= ?",
        (earliest.isoformat(),),
    ).fetchall()
    ids = [r["id"] for r in ev_rows]
    first = [datetime.fromisoformat(r["first_seen"]) for r in ev_rows]
    last = [r["last_seen"] for r in ev_rows]
    sums = [from_blob(r["centroid"]) * r["n_articles"] for r in ev_rows]   # running sums
    counts = [r["n_articles"] for r in ev_rows]
    created = 0
    touched_ids: set[int] = set()

    for a in new:
        v = from_blob(a["embedding"])
        t = datetime.fromisoformat(a["published_at"])
        best, best_sim = None, threshold
        if ids:
            C = np.stack([s / np.linalg.norm(s) for s in sums])
            sims = C @ v
            for j in np.argsort(-sims):
                if sims[j] < threshold:
                    break
                if abs(t - first[j]) <= window:
                    best, best_sim = j, sims[j]
                    break
        if best is None:
            eid = conn.execute(
                "INSERT INTO events (first_seen,last_seen,centroid,n_articles) VALUES (?,?,?,1)",
                (a["published_at"], a["published_at"], to_blob(v)),
            ).lastrowid
            ids.append(eid); first.append(t); last.append(a["published_at"]); sums.append(v.copy()); counts.append(1)
            created += 1
        else:
            eid = ids[best]
            sums[best] = sums[best] + v
            counts[best] += 1
            last[best] = max(last[best], a["published_at"])
            first[best] = min(first[best], t)
        conn.execute("UPDATE articles SET event_id=? WHERE id=?", (eid, a["id"]))
        touched_ids.add(eid)

    idx = {e: i for i, e in enumerate(ids)}
    for eid in touched_ids:
        i = idx[eid]
        topics, subtopics = _event_labels(conn, eid)
        conn.execute(
            "UPDATE events SET first_seen=?, last_seen=?, centroid=?, n_articles=?, topics=?, subtopics=? WHERE id=?",
            (first[i].isoformat(), last[i], to_blob(sums[i] / np.linalg.norm(sums[i])), counts[i],
             json.dumps(topics), json.dumps(subtopics), eid),
        )
    return {"assigned": len(new), "new_events": created, "events_touched": len(touched_ids)}
