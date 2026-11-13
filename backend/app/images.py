"""Card images from Unsplash.

Each ranked event/story gets an illustrative photo for its subtopic (or topic),
picked from a cached pool of search results per query (config/images.yaml).
Photos are hotlinked from Unsplash and always shown with photographer credit.

Rate limits: demo keys allow 50 requests/hour and the pipeline runs every 15
minutes, so each run spends at most `max_requests_per_run` requests, most
visible items first; anything left over is picked up by the next run.
"""
from __future__ import annotations

import logging
import sqlite3
import zlib
from datetime import datetime, timedelta, timezone

import httpx

from .config import images, taxonomy, unsplash_key

log = logging.getLogger(__name__)
API = "https://api.unsplash.com"


class Unsplash:
    def __init__(self, key: str, http: httpx.Client | None = None):
        self.http = http or httpx.Client(
            base_url=API, timeout=15,
            headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
        )
        self.remaining: int | None = None   # from X-Ratelimit-Remaining

    def _get(self, url: str, **params) -> httpx.Response:
        r = self.http.get(url, params=params or None)
        if "X-Ratelimit-Remaining" in r.headers:
            self.remaining = int(r.headers["X-Ratelimit-Remaining"])
        r.raise_for_status()
        return r

    def search(self, query: str, per_page: int) -> list[dict]:
        r = self._get("/search/photos", query=query, per_page=per_page,
                      orientation="landscape", content_filter="high")
        return r.json().get("results", [])

    def ping_download(self, download_location: str) -> None:
        """Unsplash guideline: tell them when a photo is selected for use."""
        self._get(download_location)


def query_for(topic: str, subtopics: list[str] | tuple[str, ...]) -> str:
    q = images()["queries"]
    return next((q[s] for s in subtopics if s in q), q.get(topic, topic))


def _store_pool(conn: sqlite3.Connection, query: str, results: list[dict], now_iso: str) -> None:
    conn.execute("DELETE FROM photo_pools WHERE query=?", (query,))
    for pos, p in enumerate(results):
        user = p.get("user") or {}
        conn.execute(
            "INSERT OR REPLACE INTO photos VALUES (?,?,?,?,?,?,?,?,?)",
            (p["id"], p["urls"]["raw"], p.get("color"), p.get("blur_hash"),
             p.get("alt_description") or p.get("description"), user.get("name") or "Unknown",
             (user.get("links") or {}).get("html", "https://unsplash.com"), p["links"]["html"],
             p["links"]["download_location"]),
        )
        conn.execute("INSERT INTO photo_pools VALUES (?,?,?,?)", (query, p["id"], pos, now_iso))


def _pool(conn: sqlite3.Connection, query: str) -> tuple[list[str], str | None]:
    rows = conn.execute("SELECT photo_id, fetched_at FROM photo_pools WHERE query=? ORDER BY position",
                        (query,)).fetchall()
    return [r["photo_id"] for r in rows], (rows[0]["fetched_at"] if rows else None)


def _ranked_items(conn: sqlite3.Connection) -> list:
    """Every event/story currently on any list, most visible first (home, topics, subtopics)."""
    from .rank import ranked

    seen, out = set(), []
    lists = [ranked(conn)]
    for topic, spec in taxonomy()["topics"].items():
        lists.append(ranked(conn, topic))
        lists += [ranked(conn, topic, s) for s in spec["subtopics"]]
    for lst in lists:
        for c in lst:
            if (c.kind, c.event_id) not in seen:
                seen.add((c.kind, c.event_id))
                out.append(c)
    return out


def assign_images(conn: sqlite3.Connection, client: Unsplash | None = None,
                  now: datetime | None = None) -> dict:
    cfg = images()["unsplash"]
    key = unsplash_key()
    if not cfg.get("enabled", True) or (client is None and not key):
        return {"images": "disabled (no UNSPLASH_ACCESS_KEY)"}
    client = client or Unsplash(key)
    now = now or datetime.now(timezone.utc)
    now_iso = now.replace(microsecond=0).isoformat()
    stale_before = (now - timedelta(hours=cfg["pool_ttl_hours"])).isoformat()
    budget = cfg["max_requests_per_run"]
    stats = {"images_assigned": 0, "pools_fetched": 0, "pings": 0, "image_errors": 0}

    def can_spend() -> bool:
        return budget > 0 and (client.remaining is None or client.remaining > cfg["min_remaining"])

    items = _ranked_items(conn)
    assigned = {(r["kind"], r["item_id"]): r["photo_id"] for r in conn.execute("SELECT * FROM item_images")}
    on_screen = {assigned[(c.kind, c.event_id)] for c in items if (c.kind, c.event_id) in assigned}

    for c in items:
        if (c.kind, c.event_id) in assigned:
            continue
        query = query_for(c.topic, c.subtopics)
        pool, fetched_at = _pool(conn, query)
        if (not pool or fetched_at < stale_before) and can_spend():
            budget -= 1
            try:
                results = client.search(query, cfg["per_page"])
                if results:
                    _store_pool(conn, query, results, now_iso)
                    pool, _ = _pool(conn, query)
                stats["pools_fetched"] += 1
            except Exception as e:  # noqa: BLE001
                stats["image_errors"] += 1
                log.warning("unsplash search %r failed: %s", query, e)
        if not pool:
            continue
        # prefer photos not already on screen, then pick deterministically per item
        fresh = [p for p in pool if p not in on_screen] or pool
        photo = fresh[zlib.crc32(f"{c.kind}:{c.event_id}".encode()) % len(fresh)]
        conn.execute("INSERT INTO item_images (kind, item_id, photo_id, query, assigned_at) VALUES (?,?,?,?,?)",
                     (c.kind, c.event_id, photo, query, now_iso))
        on_screen.add(photo)
        stats["images_assigned"] += 1

    pending = conn.execute(
        "SELECT DISTINCT i.photo_id, p.download_location FROM item_images i JOIN photos p ON p.id = i.photo_id "
        "WHERE i.download_pinged = 0").fetchall()
    for r in pending:
        if not can_spend():
            break
        budget -= 1
        try:
            client.ping_download(r["download_location"])
            conn.execute("UPDATE item_images SET download_pinged=1 WHERE photo_id=?", (r["photo_id"],))
            stats["pings"] += 1
        except Exception as e:  # noqa: BLE001
            stats["image_errors"] += 1
            log.warning("unsplash download ping failed: %s", e)
    return stats


def _utm(url: str) -> str:
    src = images()["unsplash"]["utm_source"]
    return f"{url}{'&' if '?' in url else '?'}utm_source={src}&utm_medium=referral"


def image_for(conn: sqlite3.Connection, kind: str, item_id: int) -> dict | None:
    r = conn.execute(
        "SELECT p.* FROM item_images i JOIN photos p ON p.id = i.photo_id WHERE i.kind=? AND i.item_id=?",
        (kind, item_id)).fetchone()
    if not r:
        return None
    return {
        "raw": r["raw_url"],           # add &w=…&h=…&fit=crop&auto=format to size it
        "color": r["color"],
        "blur_hash": r["blur_hash"],
        "alt": r["alt"] or "",
        "illustrative": True,          # a stock photo for the topic, not a photo of this event
        "credit": {
            "name": r["photographer"],
            "profile_url": _utm(r["photographer_url"]),
            "photo_url": _utm(r["html_url"]),
            "unsplash_url": _utm("https://unsplash.com/"),
        },
    }
