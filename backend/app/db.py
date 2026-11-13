from __future__ import annotations

import sqlite3
from contextlib import contextmanager

from .config import db_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY,
    url           TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    title_hash    TEXT NOT NULL UNIQUE,
    summary       TEXT NOT NULL DEFAULT '',
    publisher     TEXT NOT NULL,
    known         INTEGER NOT NULL,          -- 1 if publisher is in feeds.yaml
    source        TEXT NOT NULL,             -- 'rss' | 'gdelt'
    published_at  TEXT NOT NULL,             -- ISO8601 UTC
    fetched_at    TEXT NOT NULL,
    topics        TEXT,                      -- JSON list, set by classify
    subtopics     TEXT,                      -- JSON list, set by classify
    embedding     BLOB,                      -- float32, set by classify
    clickbait     INTEGER,
    event_id      INTEGER
);
CREATE INDEX IF NOT EXISTS ix_articles_published ON articles(published_at);
CREATE INDEX IF NOT EXISTS ix_articles_event ON articles(event_id);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY,
    first_seen    TEXT NOT NULL,             -- earliest member published_at
    last_seen     TEXT NOT NULL,             -- latest member published_at
    centroid      BLOB NOT NULL,             -- normalised mean member embedding
    n_articles    INTEGER NOT NULL,
    topics        TEXT,                      -- JSON list
    subtopics     TEXT                       -- JSON list
);
CREATE INDEX IF NOT EXISTS ix_events_last ON events(last_seen);

-- A story groups 6+ closely related events (e.g. every angle of one scandal).
-- It is ranked as one entry and opens to show its sub-events.
CREATE TABLE IF NOT EXISTS stories (
    id            INTEGER PRIMARY KEY,
    label         TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    kind          TEXT NOT NULL DEFAULT 'event',   -- 'event' | 'story'
    event_id      INTEGER NOT NULL,                -- event id or story id
    taken_at      TEXT NOT NULL,
    publishers    INTEGER NOT NULL,                -- distinct feeds.yaml publishers at this time
    PRIMARY KEY (kind, event_id, taken_at)
);

-- One row per (event, topic): an event scored for each topic it carries,
-- because T and the half-life depend on the topic. Replaced every run.
CREATE TABLE IF NOT EXISTS scores (
    kind          TEXT NOT NULL DEFAULT 'event',   -- 'event' | 'story'
    event_id      INTEGER NOT NULL,                -- event id or story id
    topic         TEXT NOT NULL,
    is_primary    INTEGER NOT NULL,
    p             INTEGER NOT NULL,
    added_1h      INTEGER NOT NULL,
    tier1         INTEGER NOT NULL,
    tier1_size    INTEGER NOT NULL,
    c             REAL NOT NULL,
    v             REAL NOT NULL,
    t             REAL NOT NULL,
    age_hours     REAL NOT NULL,             -- since latest article (used in decay)
    first_age_hours REAL NOT NULL,           -- since first report (shown; breaking rule)
    decay         REAL NOT NULL,
    all_clickbait INTEGER NOT NULL,
    s             REAL NOT NULL,
    computed_at   TEXT NOT NULL,
    PRIMARY KEY (kind, event_id, topic)
);

-- Unsplash photos (hotlinked, never re-hosted), pools of photos per query, and the
-- photo assigned to each ranked event/story.
CREATE TABLE IF NOT EXISTS photos (
    id            TEXT PRIMARY KEY,
    raw_url       TEXT NOT NULL,             -- urls.raw; sized with w/h params at render time
    color         TEXT,
    blur_hash     TEXT,
    alt           TEXT,
    photographer  TEXT NOT NULL,
    photographer_url TEXT NOT NULL,
    html_url      TEXT NOT NULL,
    download_location TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS photo_pools (
    query         TEXT NOT NULL,
    photo_id      TEXT NOT NULL,
    position      INTEGER NOT NULL,
    fetched_at    TEXT NOT NULL,
    PRIMARY KEY (query, photo_id)
);
CREATE TABLE IF NOT EXISTS item_images (
    kind          TEXT NOT NULL,
    item_id       INTEGER NOT NULL,
    photo_id      TEXT NOT NULL,
    query         TEXT NOT NULL,
    assigned_at   TEXT NOT NULL,
    download_pinged INTEGER NOT NULL DEFAULT 0,   -- Unsplash asks us to hit download_location once
    PRIMARY KEY (kind, item_id)
);

CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    new_articles  INTEGER,
    failed_feeds  TEXT                       -- JSON list
);
"""


MIGRATIONS = [
    "ALTER TABLE events ADD COLUMN story_id INTEGER",
]


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    for m in MIGRATIONS:
        try:
            conn.execute(m)
        except sqlite3.OperationalError:
            pass  # already applied
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
