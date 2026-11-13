"""HTTP API.

    GET /home                       top 10 across topics
    GET /topics/{topic}?subtopic=   top 10 for a topic or subtopic
    GET /events/{id}                publishers by tier, report timeline, score breakdown
    GET /stories/{id}               same for a story, plus its sub-events
    GET /health                     last run, counts, failed feeds

    uvicorn app.main:app --port 8000      (from backend/)

The pipeline runs in-process every `schedule_minutes` (config/scoring.yaml);
set NEWS_DISABLE_SCHEDULER=1 to turn that off.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import publishers, scoring, taxonomy
from .images import image_for
from .rank import Candidate, ranked

log = logging.getLogger(__name__)
TOPIC_ALIASES = {"tech": "Technology"}
_run_lock = threading.Lock()


def run_pipeline_once() -> None:
    if not _run_lock.acquire(blocking=False):
        log.info("pipeline already running; skipping")
        return
    try:
        from .pipeline import run
        log.info("pipeline run: %s", run())
    except Exception:  # noqa: BLE001
        log.exception("pipeline run failed")
    finally:
        _run_lock.release()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    sched = None
    if os.environ.get("NEWS_DISABLE_SCHEDULER") != "1":
        from apscheduler.schedulers.background import BackgroundScheduler
        from datetime import datetime, timezone
        sched = BackgroundScheduler(timezone="UTC")
        sched.add_job(run_pipeline_once, "interval", minutes=scoring()["schedule_minutes"],
                      next_run_time=datetime.now(timezone.utc), max_instances=1, coalesce=True)
        sched.start()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="News events", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


# ---- helpers ----------------------------------------------------------------------------

def _canonical_topic(topic: str) -> str:
    t = TOPIC_ALIASES.get(topic.lower())
    if t:
        return t
    for name in taxonomy()["topics"]:
        if name.lower() == topic.lower():
            return name
    raise HTTPException(404, f"unknown topic {topic!r}")


def _member_where(kind: str) -> str:
    return ("event_id = ?" if kind == "event"
            else "event_id IN (SELECT id FROM events WHERE story_id = ?)")


def _breakdown(row) -> dict:
    """Score components exactly as used for ranking, for the 'Why this is ranked here' sheet."""
    cfg = scoring()
    return {
        "topic": row["topic"],
        "publishers": row["p"],
        "total_publishers": len(publishers()),
        "added_last_hour": row["added_1h"],
        "tier1_publishers": row["tier1"],
        "tier1_list_size": row["tier1_size"],
        "c": round(row["c"], 4),
        "v": round(row["v"], 4),
        "t": round(row["t"], 4),
        "age_hours": round(row["age_hours"], 2),
        "first_report_age_hours": round(row["first_age_hours"], 2),
        "half_life_hours": cfg["half_life_hours"][row["topic"]],
        "decay": round(row["decay"], 4),
        "all_clickbait": bool(row["all_clickbait"]),
        "s": round(row["s"], 4),
        "weights": cfg["weights"],
    }


def _card(conn, c: Candidate, rank: int) -> dict:
    a = conn.execute("SELECT title, summary, url, publisher FROM articles WHERE id=?",
                     (c.rep.article_id,)).fetchone()
    summary = a["summary"] or next(
        (r[0] for r in conn.execute(f"SELECT summary FROM articles WHERE {_member_where(c.kind)} "
                                    "AND summary != '' ORDER BY published_at", (c.event_id,))), "")
    first = conn.execute(f"SELECT MIN(published_at) FROM articles WHERE {_member_where(c.kind)}",
                         (c.event_id,)).fetchone()[0]
    out = {
        "kind": c.kind,
        "id": c.event_id,
        "rank": rank,
        "headline": a["title"],
        "summary": summary,
        "publisher": a["publisher"],
        "url": a["url"],
        "first_reported_at": first,
        "sources": c.extra["p"],
        "breaking": c.breaking,
        "topic": c.topic,
        "subtopics": list(c.subtopics),
        "score": _breakdown(c.extra),
        "image": image_for(conn, c.kind, c.event_id),
    }
    if c.kind == "story":
        out["label"] = c.label
        out["sub_event_count"] = conn.execute("SELECT COUNT(*) FROM events WHERE story_id=?",
                                              (c.event_id,)).fetchone()[0]
    return out


def _detail(conn, kind: str, item_id: int) -> dict:
    tiers = {n: p["tier"] for n, p in publishers().items()}
    arts = conn.execute(
        f"SELECT id, title, summary, url, publisher, known, published_at, clickbait FROM articles "
        f"WHERE {_member_where(kind)} ORDER BY published_at", (item_id,)).fetchall()
    if not arts:
        raise HTTPException(404, f"{kind} {item_id} not found")
    score = conn.execute("SELECT * FROM scores WHERE kind=? AND event_id=? ORDER BY is_primary DESC LIMIT 1",
                         (kind, item_id)).fetchone()

    # one row per publisher: its first report
    first_by_pub: dict[str, dict] = {}
    for a in arts:
        first_by_pub.setdefault(a["publisher"], a)
    groups: dict[str, list] = {"1": [], "2": [], "3": [], "other": []}
    for pub, a in first_by_pub.items():
        tier = str(tiers[pub]) if a["known"] and pub in tiers else "other"
        groups[tier].append({"publisher": pub, "title": a["title"], "url": a["url"],
                             "published_at": a["published_at"]})
    timeline = [{"publisher": a["publisher"], "tier": tiers.get(a["publisher"]) if a["known"] else None,
                 "title": a["title"], "url": a["url"], "published_at": a["published_at"]} for a in arts]

    # headline: the representative article, as ranked lists would show it (for a story,
    # taken from its best-scoring sub-event)
    pool = arts
    if kind == "story":
        best = conn.execute(
            "SELECT e.id FROM events e LEFT JOIN scores s ON s.kind='event' AND s.event_id=e.id AND s.is_primary=1 "
            "WHERE e.story_id=? ORDER BY COALESCE(s.s, 0) DESC LIMIT 1", (item_id,)).fetchone()
        pool = [a for a in arts if a["id"] in {r[0] for r in conn.execute(
            "SELECT id FROM articles WHERE event_id=?", (best[0],))}] or arts
    lead = min(pool, key=lambda a: (a["clickbait"], tiers.get(a["publisher"], 99) if a["known"] else 99,
                                    a["published_at"]))
    out = {
        "kind": kind,
        "id": item_id,
        "headline": lead["title"],
        "summary": lead["summary"] or next((a["summary"] for a in arts if a["summary"]), ""),
        "first_reported_at": arts[0]["published_at"],
        "last_reported_at": arts[-1]["published_at"],
        "article_count": len(arts),
        "publishers_by_tier": groups,
        "timeline": timeline,
        "score": _breakdown(score) if score else None,
        "image": image_for(conn, kind, item_id),
    }
    if kind == "event":
        ev = conn.execute("SELECT topics, subtopics, story_id FROM events WHERE id=?", (item_id,)).fetchone()
        out.update(topics=json.loads(ev["topics"] or "[]"), subtopics=json.loads(ev["subtopics"] or "[]"),
                   story_id=ev["story_id"])
    else:
        st = conn.execute("SELECT label FROM stories WHERE id=?", (item_id,)).fetchone()
        subs = conn.execute(
            "SELECT e.id, e.first_seen, COALESCE(s.p, 0) p, COALESCE(s.s, 0) sc FROM events e "
            "LEFT JOIN scores s ON s.kind='event' AND s.event_id=e.id AND s.is_primary=1 "
            "WHERE e.story_id=? ORDER BY sc DESC, e.first_seen DESC", (item_id,)).fetchall()
        sub_events = []
        for e in subs:
            a = conn.execute("SELECT title FROM articles WHERE event_id=? ORDER BY known DESC, published_at LIMIT 1",
                             (e["id"],)).fetchone()
            sub_events.append({"id": e["id"], "headline": a["title"], "sources": e["p"],
                               "s": round(e["sc"], 4), "first_reported_at": e["first_seen"]})
        out.update(label=st["label"] if st else "", sub_events=sub_events)
    return out


# ---- routes ---------------------------------------------------------------------------------

@app.get("/home")
def home():
    with db.session() as conn:
        return {"items": [_card(conn, c, i) for i, c in enumerate(ranked(conn), 1)]}


@app.get("/topics/{topic}")
def topic_list(topic: str, subtopic: str | None = Query(None)):
    name = _canonical_topic(topic)
    subs = list(taxonomy()["topics"][name]["subtopics"])
    if subtopic is not None:
        match = next((s for s in subs if s.lower() == subtopic.lower()), None)
        if match is None:
            raise HTTPException(404, f"unknown subtopic {subtopic!r} for {name}")
        subtopic = match
    with db.session() as conn:
        items = [_card(conn, c, i) for i, c in enumerate(ranked(conn, name, subtopic), 1)]
    return {"topic": name, "subtopic": subtopic, "subtopics": subs, "items": items}


@app.get("/events/{event_id}")
def event(event_id: int):
    with db.session() as conn:
        return _detail(conn, "event", event_id)


@app.get("/stories/{story_id}")
def story(story_id: int):
    with db.session() as conn:
        return _detail(conn, "story", story_id)


@app.get("/health")
def health():
    with db.session() as conn:
        last = conn.execute("SELECT * FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "status": "ok" if last else "no_runs_yet",
            "running": _run_lock.locked(),
            "last_run_at": last["finished_at"] if last else None,
            "last_run_new_articles": last["new_articles"] if last else 0,
            "article_count": conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
            "event_count": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "story_count": conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0],
            "failed_feeds": json.loads(last["failed_feeds"]) if last and last["failed_feeds"] else [],
        }
