"""Step 1a: pull RSS feeds and GDELT, saving each raw response under data/raw/YYYY-MM-DD/."""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser
import httpx

from .config import RAW_DIR, feeds, scoring

log = logging.getLogger(__name__)
UA = "Mozilla/5.0 (compatible; NewsRankPrototype/0.1)"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# A single combined query per run: GDELT throttles hard (429s) on bursts, and
# topic labelling happens downstream anyway.
GDELT_QUERY = (
    "(war OR election OR sanctions OR ceasefire OR inflation OR tariffs OR economy OR "
    "\"artificial intelligence\" OR cyberattack OR cricket OR football OR tennis OR boxing)"
)


@dataclass
class RawBatch:
    source: str              # 'rss' | 'gdelt'
    name: str                # feed name or gdelt topic
    payload: dict            # JSON-serialisable raw response
    fetched_at: str


@dataclass
class IngestResult:
    batches: list[RawBatch] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _save(batch: RawBatch) -> None:
    now = datetime.now(timezone.utc)
    d = RAW_DIR / now.strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{now.strftime('%H%M%S')}_{batch.source}_{_slug(batch.name)}.json"
    path.write_text(json.dumps(
        {"source": batch.source, "name": batch.name, "fetched_at": batch.fetched_at, "payload": batch.payload},
        default=str, ensure_ascii=False,
    ))


def _fetch_feed(feed: dict) -> RawBatch | str:
    try:
        r = httpx.get(feed["url"], headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
        if not parsed.entries:
            return feed["name"]
        # feedparser results contain time.struct_time; keep only what we need, as JSON.
        entries = [
            {
                "title": e.get("title", ""),
                "summary": e.get("summary", "") or e.get("description", ""),
                "link": e.get("link", ""),
                "published": e.get("published") or e.get("updated"),
                "published_parsed": list(e["published_parsed"][:6]) if e.get("published_parsed")
                else list(e["updated_parsed"][:6]) if e.get("updated_parsed") else None,
            }
            for e in parsed.entries
        ]
        return RawBatch("rss", feed["name"], {"url": feed["url"], "entries": entries},
                        datetime.now(timezone.utc).isoformat())
    except Exception as e:  # noqa: BLE001
        log.warning("feed %s failed: %s", feed["name"], e)
        return feed["name"]


def _fetch_gdelt() -> RawBatch | str:
    cfg = scoring()["gdelt"]
    params = {
        "query": f"{GDELT_QUERY} sourcelang:english",
        "mode": "ArtList",
        "format": "json",
        "maxrecords": cfg["max_records"],
        "timespan": cfg["timespan"],
        "sort": "DateDesc",
    }
    for attempt in range(3):
        if attempt:
            time.sleep(20 * attempt)
        try:
            r = httpx.get(GDELT_URL, params=params, headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
            if not r.text.lstrip().startswith("{"):
                raise ValueError(f"non-JSON reply: {r.text[:80]!r}")
            articles = r.json().get("articles", [])
            if not articles:
                log.warning("gdelt returned no articles")
                return "GDELT (empty)"
            return RawBatch("gdelt", "all", {"query": params["query"], "articles": articles},
                            datetime.now(timezone.utc).isoformat())
        except Exception as e:  # noqa: BLE001
            log.warning("gdelt attempt %d failed: %s", attempt + 1, str(e).splitlines()[0])
    return "GDELT"


def ingest() -> IngestResult:
    res = IngestResult()
    with ThreadPoolExecutor(12) as ex:
        for out in ex.map(_fetch_feed, feeds()):
            (res.failed.append if isinstance(out, str) else res.batches.append)(out)
    if scoring()["gdelt"]["enabled"]:
        out = _fetch_gdelt()
        (res.failed.append if isinstance(out, str) else res.batches.append)(out)
    for b in res.batches:
        _save(b)
    return res
