"""Validate candidate RSS feeds and write config/feeds.yaml.

Fetches every candidate, drops any that fail, return no items, or whose newest
item is older than STALE_DAYS, then prints the surviving list for review.

    python scripts/build_feeds.py
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "config" / "feeds.yaml"
STALE_DAYS = 7
UA = "Mozilla/5.0 (compatible; NewsRankPrototype/0.1)"

G, S, E, T = "Geopolitics", "Sports", "Economics", "Technology"

# name, url, topics, tier, domains (used to map GDELT results onto publishers)
CANDIDATES = [
    # Geopolitics / world
    ("BBC News", "https://feeds.bbci.co.uk/news/world/rss.xml", [G, E, T], 1, ["bbc.co.uk", "bbc.com"]),
    ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml", [G, E, S], 1, ["aljazeera.com"]),
    ("The Guardian", "https://www.theguardian.com/world/rss", [G, E], 1, ["theguardian.com"]),
    ("New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", [G], 1, ["nytimes.com"]),
    ("NPR", "https://feeds.npr.org/1004/rss.xml", [G], 1, ["npr.org"]),
    ("Deutsche Welle", "https://rss.dw.com/rdf/rss-en-world", [G], 1, ["dw.com"]),
    ("Washington Post", "https://feeds.washingtonpost.com/rss/world", [G], 1, ["washingtonpost.com"]),
    ("France 24", "https://www.france24.com/en/rss", [G], 2, ["france24.com"]),
    ("Sky News", "https://feeds.skynews.com/feeds/rss/world.xml", [G], 2, ["news.sky.com", "skynews.com"]),
    ("The Independent", "https://www.independent.co.uk/news/world/rss", [G], 2, ["independent.co.uk"]),
    ("CBS News", "https://www.cbsnews.com/latest/rss/world", [G], 2, ["cbsnews.com"]),
    ("ABC News", "https://abcnews.go.com/abcnews/internationalheadlines", [G], 2, ["abcnews.go.com"]),
    ("Foreign Policy", "https://foreignpolicy.com/feed/", [G], 2, ["foreignpolicy.com"]),
    ("The Hindu", "https://www.thehindu.com/news/international/feeder/default.rss", [G], 2, ["thehindu.com"]),
    ("UN News", "https://news.un.org/feed/subscribe/en/news/all/rss.xml", [G], 2, ["news.un.org"]),
    ("Euronews", "https://www.euronews.com/rss?level=theme&name=news", [G], 2, ["euronews.com"]),
    ("Times of India", "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms", [G], 3, ["timesofindia.indiatimes.com"]),
    ("CNN", "http://rss.cnn.com/rss/edition_world.rss", [G], 2, ["cnn.com"]),
    # Economics
    ("CNBC", "https://www.cnbc.com/id/20910258/device/rss/rss.html", [E], 1, ["cnbc.com"]),
    ("Financial Times", "https://www.ft.com/rss/home", [E, G], 1, ["ft.com"]),
    ("Wall Street Journal", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", [E], 1, ["wsj.com"]),
    ("The Economist", "https://www.economist.com/finance-and-economics/rss.xml", [E], 1, ["economist.com"]),
    ("MarketWatch", "https://feeds.content.dowjones.io/public/rss/mw_topstories", [E], 2, ["marketwatch.com"]),
    ("Yahoo Finance", "https://finance.yahoo.com/news/rssindex", [E], 3, ["finance.yahoo.com"]),
    ("Economic Times", "https://economictimes.indiatimes.com/rssfeedstopstories.cms", [E], 3, ["economictimes.indiatimes.com"]),
    ("Fortune", "https://fortune.com/feed/fortune-feeds/?id=3230629", [E], 2, ["fortune.com"]),
    # Technology
    ("The Verge", "https://www.theverge.com/rss/index.xml", [T], 1, ["theverge.com"]),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", [T], 1, ["arstechnica.com"]),
    ("TechCrunch", "https://techcrunch.com/feed/", [T], 1, ["techcrunch.com"]),
    ("Wired", "https://www.wired.com/feed/rss", [T], 1, ["wired.com"]),
    ("Engadget", "https://www.engadget.com/rss.xml", [T], 2, ["engadget.com"]),
    ("MIT Technology Review", "https://www.technologyreview.com/feed/", [T], 2, ["technologyreview.com"]),
    ("The Register", "https://www.theregister.com/headlines.atom", [T], 2, ["theregister.com"]),
    ("ZDNet", "https://www.zdnet.com/news/rss.xml", [T], 3, ["zdnet.com"]),
    # Sports
    ("BBC Sport", "https://feeds.bbci.co.uk/sport/rss.xml", [S], 1, []),
    ("ESPN", "https://www.espn.com/espn/rss/news", [S], 1, ["espn.com"]),
    ("ESPNcricinfo", "https://www.espncricinfo.com/rss/content/story/feeds/0.xml", [S], 1, ["espncricinfo.com"]),
    ("Sky Sports", "https://www.skysports.com/rss/12040", [S], 1, ["skysports.com"]),
    ("CBS Sports", "https://www.cbssports.com/rss/headlines/", [S], 2, ["cbssports.com"]),
    ("Yahoo Sports", "https://sports.yahoo.com/rss/", [S], 3, ["sports.yahoo.com"]),
    ("NDTV Sports", "https://feeds.feedburner.com/ndtvsports-latest", [S], 3, ["sports.ndtv.com"]),
    ("Guardian Sport", "https://www.theguardian.com/uk/sport/rss", [S], 2, []),
    ("ESPN FC", "https://www.espn.com/espn/rss/soccer/news", [S], 2, []),
    ("Bad Left Hook", "https://www.badlefthook.com/rss/index.xml", [S], 3, ["badlefthook.com"]),
    ("Tennis.com", "https://www.tennis.com/rss", [S], 3, ["tennis.com"]),
]


def check(c):
    name, url, topics, tier, domains = c
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
        r.raise_for_status()
        f = feedparser.parse(r.content)
        n = len(f.entries)
        if n == 0:
            return c, False, "no items"
        newest = max(
            (datetime(*e[k][:6], tzinfo=timezone.utc) for e in f.entries
             for k in ("published_parsed", "updated_parsed") if e.get(k)),
            default=None,
        )
        if newest is None:
            return c, True, f"{n} items, no dates"
        age = (datetime.now(timezone.utc) - newest).days
        if age > STALE_DAYS:
            return c, False, f"stale, newest item {age}d old"
        return c, True, f"{n} items, newest {age}d old"
    except Exception as e:  # noqa: BLE001
        return c, False, f"{type(e).__name__}: {str(e)[:80]}"


def main():
    t0 = time.time()
    with ThreadPoolExecutor(12) as ex:
        results = list(ex.map(check, CANDIDATES))
    kept = []
    print(f"{'':2} {'publisher':24} {'tier':4} {'topics':32} result")
    for (name, url, topics, tier, domains), ok, msg in results:
        print(f"{'OK' if ok else '--':2} {name:24} {tier:<4} {','.join(topics):32} {msg}")
        if ok:
            kept.append({"name": name, "url": url, "topics": topics, "tier": tier, "domains": domains})
    OUT.write_text(
        "# Generated by scripts/build_feeds.py; edit freely.\n"
        "# name = publisher (distinct names are counted, never feeds or articles)\n"
        "# domains = hostnames used to attribute GDELT results to this publisher\n"
        + yaml.safe_dump({"feeds": kept}, sort_keys=False, allow_unicode=True)
    )
    print(f"\nKept {len(kept)}/{len(CANDIDATES)} feeds -> {OUT.relative_to(ROOT)} ({time.time()-t0:.1f}s)")
    return 0 if 30 <= len(kept) <= 40 else 1


if __name__ == "__main__":
    sys.exit(main())
