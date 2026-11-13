"""Step 3: embed articles and label topics/subtopics by similarity to config/taxonomy.yaml."""
from __future__ import annotations

import json
import sqlite3
from functools import lru_cache

import numpy as np

from .config import publishers, taxonomy
from .embed import article_text, embed, to_blob


@lru_cache
def _label_vectors():
    """Returns (topic names, topic matrix, [(topic, subtopic)], subtopic matrix)."""
    tax = taxonomy()["topics"]
    topics = list(tax)
    subs = [(t, s) for t in topics for s in tax[t]["subtopics"]]
    tv = embed([f"{t}: {tax[t]['description']}" for t in topics])
    sv = embed([f"{s}: {tax[t]['subtopics'][s]}" for t, s in subs])
    return topics, tv, subs, sv


def label(vecs: np.ndarray, pubs: list[str] | None = None) -> list[tuple[list[str], list[str]]]:
    """Multi-label each row. A topic's score is the max of its own description and its
    subtopic descriptions (which are more concrete and match headlines better), plus a
    small prior for topics the article's publisher covers according to feeds.yaml."""
    cfg = taxonomy()
    topics, tv, subs, sv = _label_vectors()
    t_sim = vecs @ tv.T                                   # (n, topics)
    s_sim = vecs @ sv.T                                   # (n, subtopics)
    sub_topic_idx = np.array([topics.index(t) for t, _ in subs])
    for j in range(len(topics)):
        t_sim[:, j] = np.maximum(t_sim[:, j], s_sim[:, sub_topic_idx == j].max(axis=1))
    if pubs is not None:
        known = publishers()
        prior = np.array([[cfg.get("publisher_prior", 0.0) * (t in known.get(p, {}).get("topics", ()))
                           for t in topics] for p in pubs])
        t_sim = t_sim + prior
    out = []
    for i in range(len(vecs)):
        order = np.argsort(-t_sim[i])
        chosen = [topics[j] for j in order[: cfg["max_topics"]] if t_sim[i, j] >= cfg["topic_threshold"]]
        # keep a second topic only if it is close to the first
        if len(chosen) == 2 and t_sim[i, order[1]] < t_sim[i, order[0]] - cfg.get("second_topic_margin", 0.05):
            chosen = chosen[:1]
        chosen_subs = []
        for t in chosen:
            ks = [k for k, (tt, _) in enumerate(subs) if tt == t]
            best = max(s_sim[i, k] for k in ks)
            if best >= cfg["subtopic_threshold"]:
                chosen_subs += [subs[k][1] for k in ks if s_sim[i, k] >= best - cfg.get("subtopic_margin", 0)]
        out.append((chosen, chosen_subs))
    return out


def classify(conn: sqlite3.Connection) -> int:
    rows = conn.execute("SELECT id, title, summary, publisher FROM articles WHERE embedding IS NULL").fetchall()
    if not rows:
        return 0
    vecs = embed([article_text(r["title"], r["summary"]) for r in rows])
    for r, v, (t, s) in zip(rows, vecs, label(vecs, [r["publisher"] for r in rows])):
        conn.execute("UPDATE articles SET embedding=?, topics=?, subtopics=? WHERE id=?",
                     (to_blob(v), json.dumps(t), json.dumps(s), r["id"]))
    return len(rows)
