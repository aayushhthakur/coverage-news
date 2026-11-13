from app.writeup import article, card_summary, split_sentences

ROWS = [
    # (publisher, title, summary, published_at)
    ("Reuters", "Acme recalls cars", "Acme Motors recalled 40,000 electric cars in Germany on Monday after a battery "
     "fault caused fires. The recall covers models built since 2024, the company said in a statement.",
     "2026-11-10T08:00:00+00:00"),
    ("BBC News", "Acme car recall", "Acme Motors is recalling 40,000 electric cars in Germany because of a battery "
     "fault linked to fires. Owners have been told not to charge the cars overnight.",
     "2026-11-10T09:00:00+00:00"),
    ("The Guardian", "Acme shares slide", "Shares in Acme Motors fell 8% as investors worried the battery recall "
     "could cost the company more than $500m. Analysts warned that the fault may hit sales across Europe.",
     "2026-11-10T12:00:00+00:00"),
    ("CNBC", "Acme recall widens", "Regulators in Berlin ordered Acme Motors to widen the recall to vans built in "
     "Poland. He said nothing more. Can Acme recover from this? Listen to our podcast episode on the recall now.",
     "2026-11-11T07:00:00+00:00"),
]


def rows(data=ROWS):
    return [{"id": i, "publisher": p, "title": t, "summary": s, "url": f"https://x/{i}", "known": 1,
             "published_at": ts} for i, (p, t, s, ts) in enumerate(data)]


def test_split_drops_fragments_questions_and_context_free_sentences():
    out = split_sentences("Acme Motors recalled cars in Germany on Monday. He said nothing more today. "
                          "Can Acme recover from this crisis? Shares in Acme fell sharply in early trad…")
    assert out == ["Acme Motors recalled cars in Germany on Monday."]


def test_split_separates_glued_standfirst_and_keeps_abbreviations():
    out = split_sentences("Hospital director says 28 wounded in attack on one of few facilities An Israeli "
                          "strike on the hospital killed six people, the U.S. embassy said.")
    assert out == ["An Israeli strike on the hospital killed six people, the U.S. embassy said."]


def test_card_summary_is_bounded_and_skips_headline_repeat():
    s = card_summary(rows(), headline="Acme Motors recalled 40,000 electric cars in Germany on Monday")
    assert 20 <= len(s.split()) <= 90
    assert "Monday after a battery fault caused fires" not in s
    # near-duplicate of the BBC sentence is not included twice
    assert s.count("40,000") <= 1


def test_article_sections_sources_and_no_repeats():
    a = article(rows())
    keys = [sec["key"] for sec in a["sections"]]
    assert keys[0] == "what"
    assert keys == sorted(keys, key=["what", "why", "where", "who", "when", "how", "impact"].index)
    texts = [b["text"] for sec in a["sections"] for b in sec["blocks"] if not b.get("generated")]
    sentences = [x for t in texts for x in split_sentences(t)]
    assert len(sentences) == len(set(sentences))
    assert not any("podcast" in t or t.endswith("?") for t in texts)
    # sources ranked by passages used, all publishers listed
    passages = [s["passages"] for s in a["sources"]]
    assert passages == sorted(passages, reverse=True)
    assert {s["publisher"] for s in a["sources"]} == {r[0] for r in ROWS}
    assert a["word_count"] == sum(len(b["text"].split()) for sec in a["sections"] for b in sec["blocks"])


def test_article_when_and_where_and_impact():
    a = article(rows())
    sec = {s["key"]: s for s in a["sections"]}
    assert sec["when"]["blocks"][0]["text"].startswith("Reuters was first to report it, on Tuesday 10 November.")
    assert "3 more publishers followed" in sec["when"]["blocks"][0]["text"]
    assert "Germany" in sec["where"]["blocks"][0]["text"]
    # the reason sits in the lead ("because of a battery fault"), so no "none of the reports" note
    assert "because of a battery fault" in sec["what"]["blocks"][0]["text"]
    assert "why" not in sec
    every = " ".join(b["text"] for s in a["sections"] for b in s["blocks"])
    assert "investors worried" in every and "Owners have been told" in every


def test_article_groups_impact_by_stakeholder():
    extra = ROWS + [("Financial Times", "Acme fallout", "Investors in Acme Motors could lose billions if the "
                     "recall spreads to America, analysts warned on Tuesday. Workers at the Leipzig plant fear "
                     "job cuts could follow the recall.", "2026-11-11T09:00:00+00:00")] * 1
    sec = {s["key"]: s for s in article(rows(extra))["sections"]}
    labels = [b.get("label") for b in sec["impact"]["blocks"]]
    assert "Investors and markets" in labels or "Workers" in labels


def test_article_respects_word_budget(monkeypatch):
    many = [(f"Pub{i}", f"Title {i}", f"Acme Motors recalled cars number {i} in Germany after fault {i} was "
             f"found by engineers in plant {i}. Investors in Acme sold shares worth {i} million on news {i}.",
             f"2026-11-10T{i % 24:02d}:00:00+00:00") for i in range(80)]
    from app import writeup
    monkeypatch.setattr(writeup, "scoring", lambda: {"writeup": {"card_words": [60, 90], "article_max_words": 300}})
    a = article(rows(many))
    assert a["word_count"] <= 360
