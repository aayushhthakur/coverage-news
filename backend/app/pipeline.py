"""Pipeline runner. Each stage is added as the build progresses.

    python -m app.pipeline            # full run
    python -m app.pipeline --report   # also print a stage report
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone

from . import db
from .classify import classify
from .cluster import cluster
from .images import assign_images
from .ingest import ingest
from .normalise import normalise
from .rank import ranked
from .scoring import snapshot_and_score
from .stories import group_stories

log = logging.getLogger(__name__)


def run() -> dict:
    started = datetime.now(timezone.utc).isoformat()
    with db.session() as conn:
        run_id = conn.execute("INSERT INTO runs (started_at) VALUES (?)", (started,)).lastrowid
        conn.commit()
        res = ingest()
        stats = normalise(conn, res.batches)
        stats["classified"] = classify(conn)
        stats.update(cluster(conn))
        stats.update(group_stories(conn))
        stats.update(snapshot_and_score(conn))
        try:
            stats.update(assign_images(conn))
        except Exception:  # noqa: BLE001 - images are decoration; never fail a run over them
            log.exception("image assignment failed")
        conn.execute(
            "UPDATE runs SET finished_at=?, new_articles=?, failed_feeds=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), stats["inserted"], json.dumps(res.failed), run_id),
        )
    return {"run_id": run_id, "failed": res.failed, "batches": len(res.batches), **stats}


def report_step1(summary: dict) -> None:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT publisher, known, source, COUNT(*) n FROM articles "
            "GROUP BY publisher, known, source ORDER BY known DESC, n DESC"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    print(f"\nRun {summary['run_id']}: {summary['batches']} raw batches saved, "
          f"inserted {summary['inserted']}, dropped {summary['dup_url']} dup-URL, "
          f"{summary['dup_title']} dup-title, {summary['too_old']} older than window")
    print(f"Failed sources: {summary['failed'] or 'none'}")
    known = [r for r in rows if r["known"]]
    print(f"\nArticles per publisher (feeds.yaml publishers; rss + gdelt-attributed)")
    agg: dict[str, dict] = {}
    for r in known:
        agg.setdefault(r["publisher"], {"rss": 0, "gdelt": 0})[r["source"]] += r["n"]
    for name, c in sorted(agg.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"  {name:24} {sum(c.values()):4}   (rss {c['rss']}, gdelt {c['gdelt']})")
    other = [r for r in rows if not r["known"]]
    print(f"\nGDELT articles from domains not in feeds.yaml: {sum(r['n'] for r in other)} "
          f"across {len(other)} domains (top 10: "
          + ", ".join(f"{r['publisher']} {r['n']}" for r in other[:10]) + ")")
    print(f"\nTotal articles in DB: {total}")


def report_step2(n: int = 20) -> None:
    with db.session() as conn:
        tot = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        evs = conn.execute(
            "SELECT e.id, e.topics, e.subtopics, e.first_seen, COUNT(DISTINCT a.publisher) p, COUNT(*) n "
            "FROM events e JOIN articles a ON a.event_id = e.id GROUP BY e.id ORDER BY p DESC, n DESC"
        ).fetchall()
        multi = [e for e in evs if e["p"] >= 2]
        print(f"\n{tot} events; {len(multi)} with 2+ publishers, "
              f"{sum(e['p'] >= 3 for e in evs)} with 3+. Showing the {n} largest by distinct publishers.\n")
        for e in evs[:n]:
            print(f"#{e['id']}  P={e['p']} articles={e['n']}  {json.loads(e['topics'])} "
                  f"{json.loads(e['subtopics'])}  first {e['first_seen'][5:16]}")
            for a in conn.execute("SELECT publisher, title FROM articles WHERE event_id=? ORDER BY published_at",
                                  (e["id"],)):
                print(f"    {a['publisher'][:16]:16}  {a['title'][:92]}")
            print()


def _print_ranked(conn, title: str, items) -> None:
    print(f"\n== {title} ==")
    print(f"{'#':>2} {'id':>5} {'P':>2} {'C':>5} {'V':>5} {'T':>5} {'age_h':>6} {'S':>6}  rep publisher     headline")
    for i, c in enumerate(items, 1):
        x = c.extra
        head = conn.execute("SELECT title FROM articles WHERE id=?", (c.rep.article_id,)).fetchone()[0]
        tags = ("[BREAKING] " if c.breaking else "") + ("[CB x0.5] " if x["all_clickbait"] else "") + \
            (f"[STORY: {c.label}, {conn.execute('SELECT COUNT(*) FROM events WHERE story_id=?', (c.event_id,)).fetchone()[0]} events] "
             if c.kind == "story" else "")
        ident = f"{'s' if c.kind == 'story' else 'e'}{c.event_id}"
        print(f"{i:>2} {ident:>5} {x['p']:>2} {x['c']:5.3f} {x['v']:5.3f} {x['t']:5.3f} "
              f"{x['age_hours']:6.1f} {c.s:6.3f}  {c.rep.publisher[:16]:16}  {tags}{head[:70]}")


def report_stories() -> None:
    with db.session() as conn:
        stories = conn.execute(
            "SELECT st.id, st.label, COUNT(e.id) n FROM stories st JOIN events e ON e.story_id = st.id "
            "GROUP BY st.id ORDER BY n DESC").fetchall()
        print(f"\n== STORIES ({len(stories)}): groups of 6+ related events ==")
        for st in stories:
            sc = conn.execute("SELECT p, s, topic FROM scores WHERE kind='story' AND event_id=? AND is_primary=1",
                              (st["id"],)).fetchone()
            print(f"\ns{st['id']}  \"{st['label']}\"  {st['n']} events, P={sc['p'] if sc else '-'}, "
                  f"S={sc['s']:.3f} ({sc['topic']})" if sc else f"\ns{st['id']} \"{st['label']}\" (no topic)")
            subs = conn.execute(
                "SELECT e.id, COALESCE(s.p, 0) p, COALESCE(s.s, 0) sc, "
                "(SELECT title FROM articles WHERE event_id = e.id ORDER BY published_at LIMIT 1) title "
                "FROM events e LEFT JOIN scores s ON s.kind='event' AND s.event_id=e.id AND s.is_primary=1 "
                "WHERE e.story_id=? ORDER BY sc DESC", (st["id"],)).fetchall()
            for e in subs:
                print(f"    e{e['id']:<4} P={e['p']:<2} S={e['sc']:.3f}  {e['title'][:85]}")


def report_step3() -> None:
    from .config import taxonomy
    report_stories()
    with db.session() as conn:
        _print_ranked(conn, "HOME (max 3 per topic)", ranked(conn))
        for topic in taxonomy()["topics"]:
            _print_ranked(conn, topic, ranked(conn, topic))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="print all stage reports after the run")
    ap.add_argument("--rank-only", action="store_true", help="print the step 3 rankings without a new run")
    a = ap.parse_args()
    if a.rank_only:
        report_step3()
        raise SystemExit
    s = run()
    if a.report:
        report_step1(s)
        report_step2()
        report_step3()
