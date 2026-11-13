"""Rule-based clickbait flag for headlines.

Rules: question bait, withheld subject, excessive punctuation, excessive capitals.
Kept deliberately conservative: a false positive demotes real news.
"""
from __future__ import annotations

import re

# "Is this the end of X?" style questions aimed at the reader, not reporting a question.
QUESTION_BAIT = re.compile(
    r"\?\s*$", re.I
)
QUESTION_HOOKS = re.compile(
    r"^(can you|do you|did you|would you|are you|have you|guess|is this|could this|what if|"
    r"is it time|should you|will you)\b|\b(you|your)\b.*\?\s*$",
    re.I,
)
WITHHELD = re.compile(
    r"\b(you won'?t believe|what happens next|what happened next|the reason (why )?will|"
    r"this (one|simple|is why|is what|is how|trick)|here'?s (why|what|how|the)|"
    r"these \d+|the truth about|nobody (is talking|expected)|will (shock|surprise|blow)|"
    r"you need to (know|see)|everyone is talking|jaw-?dropping|mind-?blowing|"
    r"(goes|went) viral|can'?t stop)\b",
    re.I,
)
STARTS_WITH_DEICTIC = re.compile(r"^(this|these|that|they|he|she|it)\s+(is|are|was|were|will|just|could)\b", re.I)
PUNCT = re.compile(r"(!{2,}|\?{2,}|[?!]{2,}|\.{4,})")
ALLCAPS_OK = {"US", "UK", "EU", "UN", "NATO", "CEO", "AI", "NFL", "NBA", "IPL", "ODI", "T20", "FIFA", "UEFA",
              "GDP", "IMF", "ECB", "RBI", "FBI", "CIA", "LIVE", "WHO", "MLB", "NHL", "ATP", "WTA", "BBC",
              "USMNT", "NVIDIA", "OK", "UAE", "USA", "IPO", "EV", "VAR", "PM", "MP", "FC", "NYC", "LA"}


def reasons(title: str) -> list[str]:
    t = title.strip()
    out = []
    if QUESTION_BAIT.search(t) and QUESTION_HOOKS.search(t):
        out.append("question bait")
    if WITHHELD.search(t) or STARTS_WITH_DEICTIC.search(t):
        out.append("withheld subject")
    if PUNCT.search(t) or t.count("!") >= 2:
        out.append("excessive punctuation")
    words = [w.strip(".,:;'\"‘’“”()") for w in t.split()]
    caps = [w for w in words if len(w) >= 3 and w.isupper() and w.isalpha() and w not in ALLCAPS_OK]
    if len(caps) >= 2 and len(caps) / max(len(words), 1) >= 0.25:
        out.append("excessive capitals")
    return out


def is_clickbait(title: str) -> bool:
    return bool(reasons(title))
