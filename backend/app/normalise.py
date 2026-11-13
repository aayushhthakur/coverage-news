"""Step 1b: turn raw batches into article rows; drop duplicates by URL and normalised-title hash."""
from __future__ import annotations

import hashlib
import html
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from datetime import timedelta

from .config import domain_map, scoring
from .ingest import RawBatch

SUMMARY_MAX = 280   # short summaries only; we never store or show full text
TRACKING = re.compile(r"^(utm_|fbclid|gclid|ocid|cmpid|mc_|at_|ns_|ito$|traffic_source)")
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def canonical_url(url: str) -> str:
    p = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if not TRACKING.match(k.lower())]
    return urlunsplit((p.scheme.lower() or "https", p.netloc.lower().removeprefix("www."),
                       p.path.rstrip("/") or "/", urlencode(q), ""))


def clean_text(s: str) -> str:
    return WS.sub(" ", html.unescape(TAG.sub(" ", s or ""))).strip()


def normalise_title(title: str, publisher: str = "") -> str:
    t = unicodedata.normalize("NFKC", title).lower()
    # drop trailing " - Publisher" / " | Publisher" suffixes
    t = re.sub(r"\s+[-|–—]\s+[^-|–—]{2,40}$", "", t) if publisher else t
    t = re.sub(r"[^\w\s]", " ", t)
    return WS.sub(" ", t).strip()


def title_hash(title: str) -> str:
    return hashlib.sha1(normalise_title(title, "x").encode()).hexdigest()


def truncate(s: str, n: int = SUMMARY_MAX) -> str:
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0]
    return cut.rstrip(",;:-") + "…"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _rss_rows(b: RawBatch):
    for e in b.payload["entries"]:
        title, url = clean_text(e["title"]), e["link"]
        if not title or not url:
            continue
        pp = e.get("published_parsed")
        published = datetime(*pp, tzinfo=timezone.utc) if pp else datetime.fromisoformat(b.fetched_at)
        yield {
            "url": canonical_url(url), "title": title, "summary": truncate(clean_text(e["summary"])),
            "publisher": b.name, "known": 1, "source": "rss", "published_at": _iso(published),
        }


def _gdelt_rows(b: RawBatch):
    dmap = domain_map()
    for a in b.payload["articles"]:
        if a.get("language", "English") != "English" or not a.get("title"):
            continue
        domain = (a.get("domain") or urlsplit(a["url"]).netloc).lower().removeprefix("www.")
        publisher = dmap.get(domain) or next((n for d, n in dmap.items() if domain.endswith("." + d)), None)
        published = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        yield {
            "url": canonical_url(a["url"]), "title": clean_text(a["title"]), "summary": "",
            "publisher": publisher or domain, "known": int(publisher is not None), "source": "gdelt",
            "published_at": _iso(published),
        }


def normalise(conn: sqlite3.Connection, batches: list[RawBatch]) -> dict:
    """Insert new articles. Returns counts of inserted and dropped rows."""
    now = _iso(datetime.now(timezone.utc))
    seen_urls = {r[0] for r in conn.execute("SELECT url FROM articles")}
    seen_hashes = {r[0] for r in conn.execute("SELECT title_hash FROM articles")}
    # Anything older than the clustering window can never join an event; skip it.
    oldest = _iso(datetime.now(timezone.utc) - timedelta(hours=scoring()["cluster_window_hours"]))
    stats = {"inserted": 0, "dup_url": 0, "dup_title": 0, "too_old": 0, "future": 0}
    # RSS first so a publisher's own feed wins over the GDELT copy of the same story.
    for b in sorted(batches, key=lambda b: b.source != "rss"):
        rows = _rss_rows(b) if b.source == "rss" else _gdelt_rows(b)
        for r in rows:
            if r["published_at"] < oldest:
                stats["too_old"] += 1
                continue
            if r["url"] in seen_urls:
                stats["dup_url"] += 1
                continue
            h = title_hash(r["title"])
            if h in seen_hashes:
                stats["dup_title"] += 1
                continue
            if r["published_at"] > now:   # clock skew in feeds: clamp to now
                r["published_at"] = now
                stats["future"] += 1
            conn.execute(
                "INSERT INTO articles (url,title,title_hash,summary,publisher,known,source,published_at,fetched_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (r["url"], r["title"], h, r["summary"], r["publisher"], r["known"], r["source"],
                 r["published_at"], now),
            )
            seen_urls.add(r["url"])
            seen_hashes.add(h)
            stats["inserted"] += 1
    return stats
