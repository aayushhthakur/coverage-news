"""Card summaries and long-form write-ups for events and stories.

Engine "extractive" (the only one for now): every sentence comes verbatim from the
feed summaries of the item's articles, with its publisher attached. Nothing is
generated except short connective lines built from metadata (who reported first,
which names recur). Sentences are scored by how widely their words are used across
publishers, so the summary reflects what all the angles have in common.

The output shape (summary text; sections of blocks, each with its sources; sources
ranked by use) is what an LLM writer should return later too.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from .config import publishers, scoring

STOP = set("""
a about above after again against all also am an and any are aren't as at be because been before being below
between both but by can can't could did didn't do does doesn't doing don't down during each few for from further
had hasn't has have haven't having he he'd he'll he's her here here's hers herself him himself his how how's i
i'd i'll i'm i've if in into is isn't it it's its itself let's me more most mustn't my myself no nor not of off
on once only or other ought our ours ourselves out over own same shan't she she'd she'll she's should shouldn't
so some such than that that's the their theirs them themselves then there there's these they they'd they'll
they're they've this those through to too under until up very was wasn't we we'd we'll we're we've were weren't
what what's when when's where where's which while who who's whom why why's with won't would wouldn't you you'd
you'll you're you've your yours yourself yourselves says said say saying told according reported reports report
new one two three first last year years week day days time also just like may might will still now amid per
mr ms dr monday tuesday wednesday thursday friday saturday sunday today yesterday tomorrow
""".split())
MONTHS = {"January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December", "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec"}
DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
# capitalised words that are not names on their own
NOT_NAMES = MONTHS | DAYS | {
    "The", "A", "An", "In", "On", "At", "As", "After", "But", "And", "Or", "It", "He", "She", "They", "We", "His",
    "Her", "Their", "This", "That", "These", "Those", "When", "While", "What", "Who", "How", "Why", "Where", "If",
    "President", "Prime", "Minister", "CEO", "Chief", "Executive", "Officer", "Secretary", "Mr", "Ms", "Dr",
    "Former", "New", "Breaking", "Live", "Watch", "Analysis", "Opinion", "Here", "Some", "Many", "More", "Most",
    "Officials", "Sources", "Police", "Government", "State", "Federal", "National", "Thursday's", "Friday's",
    "Saturday's", "Sunday's", "Monday's", "Tuesday's", "Wednesday's", "Ministry", "Health", "Department", "With",
}
INVISIBLE = re.compile(r"[\u00ad\u034f\u200b-\u200f\u2060\ufeff]")
# feeds often glue a standfirst to the body or append "Full report: …" without punctuation
GLUE = re.compile(r"(?<=[a-z0-9,’'”])\s+(?=(?:An|The|Full report:|Analysis:|Live:|Watch:|Read more|"
                  r"Good morning|Good evening|PRESS REVIEW)\b)")
# context-free openers and promos make no sense out of their original paragraph
DROP = re.compile(r"^(he|she|they|it|his|her|their|its|this|that|these|those|but|and|yet|so|also|meanwhile|"
                  r"here|there|plus|now|still|instead)\b|\b(episode|podcast|newsletter|uncanny valley|we (look|break down|unpack|"
                  r"explain)|the team unpacks|sign up|subscribe|press review|full report|analysis:|live updates|"
                  r"latest updates)\b", re.I)
BOILERPLATE = [
    re.compile(r"^in today[’']s (newsletter|briefing)\s*:?\s*", re.I),
    re.compile(r"^(watch|listen|live|explainer|analysis|opinion)\s*[:|-]\s*", re.I),
    re.compile(r"\s*(continue reading|read more|click here|sign up|subscribe)\b.*$", re.I),
]
ABBREV = re.compile(r"\b(U\.S|U\.K|U\.N|E\.U|Mr|Ms|Mrs|Dr|St|Gen|Lt|Col|Sgt|Rep|Sen|Gov|No|vs|Inc|Ltd|Co|Jr|Sr|"
                    r"Jan|Feb|Mar|Apr|Aug|Sept|Sep|Oct|Nov|Dec|a\.m|p\.m|e\.g|i\.e)\.")
SPLIT = re.compile(r"(?<=[.!?])[\"”’)]?\s+(?=[\"“‘(]?[A-Z0-9])")
ENDS_OK = re.compile(r"[.!?][\"”’)]?$")
WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")
CAPSEQ = re.compile(r"(?:[A-Z][\w’'.-]*(?:\s+(?:of|de|al|bin|von|van)\s+)?\s?){1,4}")
LOCATIVE = re.compile(r"\b(?:in|at|from|across|near|inside|outside|into|throughout)\s+(?:the\s+)?"
                      r"(?:(?:northern|southern|eastern|western|central|north|south|east|west)(?:ern)?\s+)?"
                      r"([A-Z][\w’']+(?:\s+[A-Z][\w’']+){0,2})")

CUES = {
    "why": re.compile(r"\b(because|after|following|due to|amid|over (?:allegations|claims|concerns|fears)|"
                      r"in response|prompt\w*|spark\w*|trigger\w*|as a result|reason|blam\w+|accus\w+|"
                      r"alleg\w+|suspect\w*|investigat\w+|probe|demand\w*|caused?|led to)\b", re.I),
    "how": re.compile(r"\b(by|through|via|using|announc\w+|statement|agree\w*|deal|plan\w*|propos\w+|vote\w*|"
                      r"ruled?|signed|launch\w*|confirm\w*|met|meeting|talks|struck|hit|scored|won|beat|"
                      r"released|filed|ordered|moved)\b", re.I),
    "impact": re.compile(r"\b(could|would|may|might|expected to|threat\w*|risk\w*|fear\w*|impact\w*|affect\w*|"
                         r"cost\w*|damage\w*|hurt\w*|benefit\w*|concern\w*|uncertain\w*|warn\w*|jobs?|prices?|"
                         r"shares?|stocks?|investors?|fans|consumers?|workers?|civilians?|residents?|patients?|"
                         r"voters?|customers?|families|economy|collateral|wounded|killed|injured)\b", re.I),
    "when": re.compile(r"\b(on (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
                       r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
                       r" \d{1,2}|earlier this (?:week|month|year)|last (?:week|month|year)|since \d{4}|"
                       r"overnight|this week)\b", re.I),
}
STAKEHOLDERS = [
    ("Investors and markets", re.compile(r"\b(investors?|shareholders?|shares|stocks?|markets?|retirement|"
                                         r"valuation|bonds?|traders?)\b", re.I)),
    ("Governments and regulators", re.compile(r"\b(government|officials?|lawmakers?|congress|parliament|"
                                              r"ministers?|administration|regulators?|white house|kremlin|"
                                              r"washington|beijing|authorities|leaders)\b", re.I)),
    ("Businesses", re.compile(r"\b(compan(?:y|ies)|firms?|industry|businesses|suppliers?|providers?|"
                              r"operators?|chipmakers?|manufacturers?)\b", re.I)),
    ("People on the ground", re.compile(r"\b(civilians?|residents?|patients?|families|children|victims?|"
                                        r"people|commuters|citizens|refugees|migrants|wounded|killed)\b", re.I)),
    ("Workers", re.compile(r"\b(workers?|employees?|staff|jobs?|unions?|layoffs?)\b", re.I)),
    ("Consumers", re.compile(r"\b(consumers?|customers?|users?|buyers?|shoppers?|prices?|bills?)\b", re.I)),
    ("Players and fans", re.compile(r"\b(players?|fans|supporters|squad|team|club|coach|manager|captain)\b", re.I)),
    ("Voters and parties", re.compile(r"\b(voters?|candidates?|part(?:y|ies)|electorate|campaign)\b", re.I)),
]
TITLES = {"what": "What happened", "why": "Why it happened", "where": "Where", "who": "Who is involved",
          "when": "When", "how": "How it unfolded", "impact": "What it means for those involved"}


@dataclass
class Sent:
    text: str
    publisher: str
    url: str
    published_at: str
    tier: int | None
    is_title: bool = False
    words: frozenset = field(default_factory=frozenset)
    score: float = 0.0


def _stem(w: str) -> str:
    w = w.lower().replace("’", "'")
    w = re.sub(r"'s$", "", w)
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def content_words(text: str) -> frozenset:
    return frozenset(_stem(w) for w in WORD.findall(text) if w.lower().replace("’", "'") not in STOP and len(w) > 2)


def split_sentences(summary: str) -> list[str]:
    s = INVISIBLE.sub("", summary).strip()
    for rx in BOILERPLATE:
        s = rx.sub("", s)
    protected = ABBREV.sub(lambda m: m.group(0).replace(".", "§"), s)
    out = []
    for chunk in SPLIT.split(protected):
        for part in GLUE.split(chunk):
            part = part.replace("§", ".").strip()
            n = len(part.split())
            # drop fragments cut off by feed truncation ("…"), with no closing punctuation,
            # rhetorical questions, and sentences that only work in their original context
            if (part.endswith("…") or not ENDS_OK.search(part) or part.rstrip("\"”’)").endswith("?")
                    or n < 6 or n > 60 or DROP.search(part)):
                continue
            out.append(part)
    return out


def _jaccard(a: frozenset, b: frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _articles(conn: sqlite3.Connection, kind: str, item_id: int) -> list[sqlite3.Row]:
    where = "event_id = ?" if kind == "event" else "event_id IN (SELECT id FROM events WHERE story_id = ?)"
    return conn.execute(f"SELECT id, title, summary, url, publisher, known, published_at FROM articles "
                        f"WHERE {where} ORDER BY published_at", (item_id,)).fetchall()


def build_sentences(rows) -> tuple[list[Sent], list[Sent]]:
    """(summary sentences, headline sentences), each scored by cross-publisher word use."""
    tiers = {n: p["tier"] for n, p in publishers().items()}
    sents, titles = [], []
    for r in rows:
        tier = tiers.get(r["publisher"]) if r["known"] else None
        seen_here = set()
        for t in split_sentences(r["summary"] or ""):
            if t not in seen_here:
                seen_here.add(t)
                sents.append(Sent(t, r["publisher"], r["url"], r["published_at"], tier, False, content_words(t)))
        titles.append(Sent(r["title"].strip(), r["publisher"], r["url"], r["published_at"], tier, True,
                           content_words(r["title"])))
    # word weight = number of distinct publishers using it (headlines and summaries)
    by_pub: dict[str, set] = defaultdict(set)
    for s in sents + titles:
        by_pub[s.publisher] |= s.words
    weight = Counter(w for ws in by_pub.values() for w in ws)
    for s in sents + titles:
        s.score = _score(s, weight)
    return sents, titles


def _score(s: Sent, weight: Counter, covered: frozenset | set = frozenset()) -> float:
    """Cross-publisher weight of the sentence's words not already covered."""
    if not s.words:
        return 0.0
    base = sum(weight[w] for w in s.words - covered) / len(s.words) ** 0.5
    return base * (1.1 if s.tier == 1 else 1.0)


def _weights(sents: list[Sent], titles: list[Sent]) -> Counter:
    by_pub: dict[str, set] = defaultdict(set)
    for s in sents + titles:
        by_pub[s.publisher] |= s.words
    return Counter(w for ws in by_pub.values() for w in ws)


class Picker:
    """Hands out sentences, never the same one twice and never a near-duplicate."""

    def __init__(self, pool: list[Sent], avoid: list[frozenset] = (), max_overlap: float = 0.5):
        self.pool = sorted(pool, key=lambda s: -s.score)
        self.used: list[Sent] = []
        self.avoid = list(avoid)
        self.max_overlap = max_overlap

    def ok(self, s: Sent) -> bool:
        return all(_jaccard(s.words, u.words) < self.max_overlap for u in self.used) and \
            all(_jaccard(s.words, a) < 0.6 for a in self.avoid)

    def take(self, pred=lambda s: True, n: int = 1) -> list[Sent]:
        out = []
        for s in self.pool:
            if len(out) >= n:
                break
            if s not in self.used and pred(s) and self.ok(s):
                self.used.append(s)
                out.append(s)
        return out


def card_summary(rows, headline: str = "") -> str:
    """~60-90 words of the most widely shared sentences, skipping a repeat of the headline."""
    lo, hi = scoring().get("writeup", {}).get("card_words", [60, 90])
    sents, titles = build_sentences(rows)
    weight = _weights(sents, titles)
    # the headline is shown above the summary, so its words count as already said
    covered = set(content_words(headline))
    out, words, left = [], 0, list(sents)
    while words < lo and left:
        # each next sentence is the one adding the most widely used words not yet covered
        fits = [s for s in left if not words or words + len(s.text.split()) <= hi]
        if not fits:
            break
        best = max(fits, key=lambda s: _score(s, weight, covered))
        left.remove(best)
        if _score(best, weight, covered) < 0.35 * best.score or \
                any(_jaccard(best.words, content_words(t)) >= 0.35 for t in out):
            continue
        out.append(best.text)
        covered |= best.words
        words += len(best.text.split())
    return " ".join(out)


# ---- entities --------------------------------------------------------------------------

NOT_PLACE_BEFORE = re.compile(r"\b(shares?|stakes?|investors?|investment|interest|role|seat|part|stock|"
                              r"confidence|trust|faith|career|job|position|lead)\s*$", re.I)
DEMONYM = re.compile(r"^[A-Z][a-z]+(?:ese|ian|ians|ean|eans|ish)$")
DEMONYMS_I = {"Israeli", "Israelis", "Iraqi", "Iraqis", "Pakistani", "Pakistanis", "Saudi", "Saudis", "Qatari",
              "Emirati", "Kuwaiti", "Yemeni", "Somali", "Bangladeshi", "Nepali", "Afghan", "Afghans", "Thai",
              "Omani", "Bahraini", "Azerbaijani", "Uzbek", "Kazakh", "Iranians", "Iranian", "Chinese", "French",
              "Dutch", "Swiss", "Greek", "Greeks", "Turkish", "Polish", "Danish", "Irish", "Welsh", "Scottish"}


def _is_demonym(w: str) -> bool:
    return " " not in w and (w in DEMONYMS_I or bool(DEMONYM.match(w)))


def _entities(sents: list[Sent], titles: list[Sent], publisher_names: set[str]) -> tuple[list[str], list[str]]:
    """(names, places) ranked by how many publishers mention them."""
    name_pubs: dict[str, set] = defaultdict(set)
    place_pubs: dict[str, set] = defaultdict(set)
    loc_hits: Counter = Counter()
    mentions: Counter = Counter()
    for s in sents:
        text = s.text
        for m in LOCATIVE.finditer(text):
            if NOT_PLACE_BEFORE.search(text[:m.start()]):     # "shares in Acme", "a seat at the table"
                continue
            p = re.sub(r"^the\s+", "", m.group(1)).strip(" .,’'")
            if "'" in p or "’" in p or _is_demonym(p):
                continue
            if p.split()[0] not in NOT_NAMES and p not in publisher_names:
                place_pubs[p].add(s.publisher)
                loc_hits[p] += 1
        for m in CAPSEQ.finditer(text):
            words = []
            for w in m.group(0).split():
                if "-" in w:            # "Hamas-controlled", "Russia-Ukraine": not a name
                    break
                words.append(re.sub(r"['’]s$", "", w).strip(".,’'"))
            while words and (words[0] in NOT_NAMES or words[0].islower()):
                words = words[1:]
            while words and (words[-1] in NOT_NAMES or words[-1].islower()):
                words = words[:-1]
            if not words or (len(words) == 1 and len(words[0]) < 3):
                continue
            phrase = " ".join(words)
            if (phrase in publisher_names or phrase.lower() in STOP or phrase.isupper() and len(phrase) > 6
                    or _is_demonym(phrase)):
                continue
            # a sentence's first word is only a name if it is part of a longer capitalised run
            if m.start() == 0 and len(words) == 1:
                continue
            name_pubs[phrase].add(s.publisher)
            mentions[phrase] += 1
    # a place is mostly mentioned as "in X" / "from X"; "Nvidia" is mostly a subject
    places = [p for p, pubs in sorted(place_pubs.items(), key=lambda kv: -len(kv[1]))
              if loc_hits[p] >= 0.4 * max(mentions[p], loc_hits[p])]
    place_set = set(places)
    ranked = sorted(name_pubs, key=lambda n: (-len(name_pubs[n]), -len(n)))
    # prefer the full name: "Putin" folds into "Vladimir Putin" when that is reasonably common
    def inside(a: str, b: str) -> bool:
        return a != b and f" {a} " in f" {b} "

    kept: list[str] = []
    for n in ranked:
        if n in place_set or n.split()[0] in place_set and len(n.split()) > 1:   # "Gaza Nasser Hospital"
            continue
        longer = [k for k in ranked if inside(n, k) and len(name_pubs[k]) >= 0.4 * len(name_pubs[n])]
        full = max(longer, key=lambda k: len(name_pubs[k])) if longer else n
        if full not in kept and not any(inside(full, k) or inside(k, full) for k in kept):
            kept.append(full)
    return kept, places


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _fmt_day(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B')}"


def _block(sents: list[Sent], label: str | None = None) -> dict:
    return {"text": " ".join(s.text for s in sents), "sources": list(dict.fromkeys(s.publisher for s in sents)),
            **({"label": label} if label else {})}


def _note(text: str) -> dict:
    return {"text": text, "sources": [], "generated": True}


# ---- article ---------------------------------------------------------------------------

def article(rows, headline: str = "") -> dict:
    cfg = scoring().get("writeup", {})
    max_words = cfg.get("article_max_words", 1000)
    sents, titles = build_sentences(rows)
    pubs_all = set(publishers()) | {r["publisher"] for r in rows}
    names, places = _entities(sents, titles, pubs_all)
    picker = Picker(sents, [content_words(headline)] if headline else [])
    sections: list[dict] = []

    def add(key: str, blocks: list[dict]):
        blocks = [b for b in blocks if b["text"]]
        if blocks:
            sections.append({"key": key, "title": TITLES[key], "blocks": blocks})

    # What: the most central sentences
    lead = picker.take(n=3 if len(sents) >= 15 else 2 if len(sents) >= 6 else 1)
    add("what", [_block(lead)] if lead else [_note(headline)] if headline else [])

    # Why
    why = picker.take(lambda s: bool(CUES["why"].search(s.text)), n=3)
    if why:
        add("why", [_block(why)])
    elif not any(CUES["why"].search(s.text) for s in lead):   # the lead may already give the reason
        add("why", [_note("None of the reports so far set out why this happened.")])

    # Where
    where_blocks = []
    if places:
        where_blocks.append(_note(f"The reporting places this in {_join(places[:4])}."))
        near = picker.take(lambda s: any(p in s.text for p in places[:3]), n=2)
        if near:
            where_blocks.append(_block(near))
    add("where", where_blocks or [_note("The reports do not name a specific place.")])

    # Who
    who_blocks = []
    if names:
        who_blocks.append(_note(f"The names that recur across the coverage are {_join(names[:5])}."))
        for n in names[:3]:
            got = picker.take(lambda s, n=n: n in s.text, n=1)
            if got:
                who_blocks.append(_block(got, label=n))
    add("who", who_blocks)

    # When: built from timestamps, then any dated sentences
    first, last = rows[0], rows[-1]
    n_pubs = len({r["publisher"] for r in rows})
    hours = (datetime.fromisoformat(last["published_at"]) - datetime.fromisoformat(first["published_at"])
             ).total_seconds() / 3600
    when = f"{first['publisher']} was first to report it, on {_fmt_day(first['published_at'])}."
    if n_pubs > 1:
        span = f"{hours:.0f} hours" if hours >= 1.5 else "the next hour"
        when += f" Over {span}, {n_pubs - 1} more {'publisher' if n_pubs == 2 else 'publishers'} followed"
        when += f", the latest being {last['publisher']} on {_fmt_day(last['published_at'])}." \
            if hours >= 1.5 else "."
    dated = picker.take(lambda s: bool(CUES["when"].search(s.text)), n=2)
    add("when", [_note(when)] + ([_block(dated)] if dated else []))


    # Impact, per stakeholder group (named ones first)
    impact_blocks = []
    for n in names[:2]:
        got = picker.take(lambda s, n=n: n in s.text and bool(CUES["impact"].search(s.text)), n=1)
        if got:
            impact_blocks.append(_block(got, label=n))
    for label, rx in STAKEHOLDERS:
        if len(impact_blocks) >= 6:
            break
        got = picker.take(lambda s, rx=rx: bool(rx.search(s.text)) and bool(CUES["impact"].search(s.text)),
                          n=2 if len(sents) > 40 else 1)
        if got:
            impact_blocks.append(_block(got, label=label))
    add("impact", impact_blocks)

    # How: the rest of the story in the order it was reported (picked after impact so
    # stakeholder sentences are not used up here)
    how = picker.take(lambda s: bool(CUES["how"].search(s.text)), n=6)

    # Top up "How it unfolded" to the word budget with the remaining central sentences,
    # then tell it in the order it was reported, two sentences to a paragraph
    def words() -> int:
        return sum(len(b["text"].split()) for sec in sections for b in sec["blocks"])
    budget = max_words - 40 - words() - sum(len(s.text.split()) for s in how)
    while budget > 0:
        got = picker.take(n=1)
        if not got:
            break
        how.append(got[0])
        budget -= len(got[0].text.split())
    how.sort(key=lambda s: s.published_at)
    add("how", [_block(how[i:i + 2]) for i in range(0, len(how), 2)])

    # Sources, most used first
    used = Counter(s.publisher for s in picker.used)
    first_url = {}
    for r in rows:
        first_url.setdefault(r["publisher"], (r["url"], r["title"], r["published_at"]))
    tiers = {n: p["tier"] for n, p in publishers().items()}
    known = {r["publisher"] for r in rows if r["known"]}
    sources = sorted(
        ({"publisher": p, "passages": used.get(p, 0), "tier": tiers.get(p) if p in known else None,
          "url": u, "title": t, "published_at": ts} for p, (u, t, ts) in first_url.items()),
        key=lambda x: (-x["passages"], x["tier"] or 9, x["published_at"]))
    order = {k: i for i, k in enumerate(["what", "why", "where", "who", "when", "how", "impact"])}
    sections.sort(key=lambda s: order[s["key"]])
    return {"engine": "extractive", "word_count": words(), "sections": sections, "sources": sources}


# ---- cached entry points ----------------------------------------------------------------

_cache: dict = {}


def _key(conn, kind, item_id, what):
    n, mx = conn.execute(
        "SELECT COUNT(*), MAX(id) FROM articles WHERE " +
        ("event_id = ?" if kind == "event" else "event_id IN (SELECT id FROM events WHERE story_id = ?)"),
        (item_id,)).fetchone()
    return (what, kind, item_id, n, mx)


def summary_for(conn: sqlite3.Connection, kind: str, item_id: int, headline: str = "") -> str:
    k = _key(conn, kind, item_id, ("summary", headline))
    if k not in _cache:
        _cache[k] = card_summary(_articles(conn, kind, item_id), headline)
    return _cache[k]


def article_for(conn: sqlite3.Connection, kind: str, item_id: int, headline: str = "") -> dict | None:
    k = _key(conn, kind, item_id, ("article", headline))
    if k not in _cache:
        rows = _articles(conn, kind, item_id)
        _cache[k] = article(rows, headline) if rows else None
    return _cache[k]
