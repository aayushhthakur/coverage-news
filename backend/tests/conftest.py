import itertools
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ["NEWS_DISABLE_SCHEDULER"] = "1"

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
_url = itertools.count()


def iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).replace(microsecond=0).isoformat()


class Seeder:
    """Builds events directly in the DB, bypassing ingest/embedding."""

    def __init__(self, conn):
        self.conn = conn

    def event(self, topics, articles, subtopics=(), story_id=None):
        """articles: [(publisher, title, hours_ago)]; publishers must exist in feeds.yaml
        unless given as ('domain.com', title, hours_ago, False)."""
        times = [a[2] for a in articles]
        eid = self.conn.execute(
            "INSERT INTO events (first_seen,last_seen,centroid,n_articles,topics,subtopics,story_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (iso(max(times)), iso(min(times)), b"\0" * 1536, len(articles), json.dumps(list(topics)),
             json.dumps(list(subtopics)), story_id),
        ).lastrowid
        for a in articles:
            pub, title, h = a[:3]
            known = a[3] if len(a) > 3 else True
            n = next(_url)
            self.conn.execute(
                "INSERT INTO articles (url,title,title_hash,summary,publisher,known,source,published_at,"
                "fetched_at,topics,subtopics,event_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"https://example.com/{n}", title, f"h{n}", f"Summary of {title}", pub, int(known),
                 "rss", iso(h), iso(0), json.dumps(list(topics)), json.dumps(list(subtopics)), eid),
            )
        return eid

    def story(self, label="Story"):
        return self.conn.execute("INSERT INTO stories (label,created_at,updated_at) VALUES (?,?,?)",
                                 (label, iso(0), iso(0))).lastrowid

    def snapshot(self, event_id, hours_ago, publishers, kind="event"):
        self.conn.execute("INSERT INTO snapshots VALUES (?,?,?,?)", (kind, event_id, iso(hours_ago), publishers))

    def score(self):
        from app.scoring import snapshot_and_score
        return snapshot_and_score(self.conn, now=NOW)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("NEWS_DB_PATH", str(tmp_path / "test.db"))
    from app import db
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def seed(conn):
    return Seeder(conn)
