"""One test group per re-ranking rule (spec step 8), plus representative selection (step 7)."""
from app.config import scoring
from app.rank import (Candidate, Rep, breaking_boost, cap_and_select, dedupe, load_candidates, mark_breaking,
                      order_reps, rank_home, rank_topic)

CFG = scoring()


def rep(pub, tier=1, clickbait=False, t="2026-11-13T10:00:00+00:00", aid=0):
    return Rep(aid, pub, tier, clickbait, t)


def cand(eid, s, topic="Technology", v=0.0, age=10.0, pubs=("Wired",), kind="event", subtopics=()):
    return Candidate(eid, topic, s, v, age, tuple(rep(p) for p in pubs), tuple(subtopics), kind=kind,
                     extra={"p": len(pubs)})


def ids(cs):
    return [c.event_id for c in cs]


# ---- step 7: representative article ------------------------------------------------------------

def test_representative_prefers_highest_tier():
    r = order_reps([rep("ZDNet", 3), rep("Wired", 1), rep("Engadget", 2)])
    assert r[0].publisher == "Wired"


def test_representative_skips_clickbait_headline():
    r = order_reps([rep("Wired", 1, clickbait=True), rep("Engadget", 2)])
    assert r[0].publisher == "Engadget"


def test_representative_falls_back_when_all_clickbait():
    r = order_reps([rep("Engadget", 2, True), rep("Wired", 1, True)])
    assert r[0].publisher == "Wired"


def test_representative_one_entry_per_publisher_earliest_first():
    r = order_reps([rep("Wired", t="2026-11-13T11:00:00+00:00", aid=2),
                    rep("Wired", t="2026-11-13T09:00:00+00:00", aid=1)])
    assert [x.article_id for x in r] == [1]


# ---- rule: one entry per event ---------------------------------------------------------------------

def test_one_entry_per_event_keeps_best_row():
    out = dedupe([cand(1, 0.2), cand(1, 0.5, topic="Economics"), cand(2, 0.3)])
    assert ids(out) == [1, 2]
    assert out[0].s == 0.5


def test_event_and_story_with_same_id_are_distinct():
    assert len(dedupe([cand(1, 0.2), cand(1, 0.3, kind="story")])) == 2


# ---- rule: max 2 representative articles per publisher in a top 10 ------------------------------------

def test_publisher_cap_switches_to_next_representative():
    cs = [cand(i, 1 - i / 10, pubs=("Wired", "The Verge")) for i in range(3)]
    out = cap_and_select(cs, 10, 2)
    assert [c.rep.publisher for c in out] == ["Wired", "Wired", "The Verge"]


def test_publisher_cap_skips_event_with_no_alternative():
    cs = [cand(1, 0.9), cand(2, 0.8), cand(3, 0.7), cand(4, 0.6, pubs=("TechCrunch",))]
    out = cap_and_select(cs, 10, 2)
    assert ids(out) == [1, 2, 4]


def test_publisher_cap_holds_in_ranked_topic_list():
    cs = [cand(i, 1 - i / 100, pubs=("Wired", "The Verge", "TechCrunch")) for i in range(12)]
    out = rank_topic(cs, CFG)
    counts = {}
    for c in out:
        counts[c.rep.publisher] = counts.get(c.rep.publisher, 0) + 1
    assert max(counts.values()) <= 2


def test_top_n_is_ten():
    cs = [cand(i, 1 - i / 100, pubs=(f"P{i}",)) for i in range(15)]
    assert len(rank_topic(cs, CFG)) == 10


# ---- rule: breaking boost ----------------------------------------------------------------------------

def _pool_with(young_fast_rank=8):
    cs = [cand(i, 1 - i / 20, v=0.0, pubs=(f"P{i}",)) for i in range(20)]
    cs[young_fast_rank] = cand(young_fast_rank, cs[young_fast_rank].s, v=0.8, age=1.0,
                               pubs=(f"P{young_fast_rank}",))
    return cs


def test_breaking_event_moves_into_top_three_with_tag():
    out = rank_topic(_pool_with(8), CFG)
    top3 = out[:3]
    assert 8 in ids(top3)
    assert next(c for c in out if c.event_id == 8).breaking
    assert sum(c.breaking for c in out) == 1


def test_breaking_requires_under_two_hours():
    cs = _pool_with(8)
    cs[8] = cand(8, cs[8].s, v=0.8, age=2.5, pubs=("P8",))
    out = rank_topic(cs, CFG)
    assert not any(c.breaking for c in out)
    assert ids(out).index(8) == 8


def test_breaking_requires_top_five_percent_velocity():
    # 20 young events with rising V: only the top 5% (the single fastest) is breaking
    cs = [cand(i, 1 - i / 20, v=i / 20, age=1.0, pubs=(f"P{i}",)) for i in range(20)]
    marked = mark_breaking(cs, 2, 95)
    assert [c.event_id for c in marked if c.breaking] == [19]


def test_breaking_requires_positive_velocity():
    cs = [cand(i, 1 - i / 20, v=0.0, age=0.5, pubs=(f"P{i}",)) for i in range(20)]
    assert not any(c.breaking for c in mark_breaking(cs, 2, 95))


def test_breaking_already_in_top_three_keeps_score_order():
    cs = [cand(0, 0.9, pubs=("A",)), cand(1, 0.8, v=0.9, age=0.5, pubs=("B",)), cand(2, 0.7, pubs=("C",))]
    cs = mark_breaking(cs, 2, 95)
    assert ids(breaking_boost(cs, 3)) == [0, 1, 2]


# ---- rule: clickbait demotion is in the score (see test_scoring); here: ranks drop accordingly ----

def test_clickbait_demoted_event_ranks_below_equal_event():
    from app.scoring import score
    w = CFG["weights"]
    bait = cand(1, score(0.5, 0, 0.5, 1, 18, w, all_clickbait=True), pubs=("A",))
    fair = cand(2, score(0.5, 0, 0.5, 1, 18, w), pubs=("B",))
    assert ids(rank_topic([bait, fair], CFG)) == [2, 1]


# ---- rule: home interleaves topics, max 3 per topic in top 10 -----------------------------------------

def _home_pool():
    by_topic = {
        "Technology": [cand(i, 0.9 - i / 100, "Technology", pubs=(f"T{i}",)) for i in range(10)],
        "Sports": [cand(100 + i, 0.5 - i / 100, "Sports", pubs=(f"S{i}",)) for i in range(5)],
        "Economics": [cand(200 + i, 0.4 - i / 100, "Economics", pubs=(f"E{i}",)) for i in range(5)],
        "Geopolitics": [cand(300, 0.3, "Geopolitics", pubs=("G0",))],
    }
    primary = {(c.kind, c.event_id, t) for t, cs in by_topic.items() for c in cs}
    return by_topic, primary


def test_home_max_three_per_topic():
    by_topic, primary = _home_pool()
    out = rank_home(by_topic, primary, CFG)
    assert len(out) == 10
    for t in by_topic:
        assert sum(c.topic == t for c in out) <= 3
    assert ids(out)[:3] == [0, 1, 2]           # best tech first, then other topics fill in


def test_home_shows_event_once_under_primary_topic():
    by_topic, primary = _home_pool()
    dup = cand(0, 0.95, "Economics", pubs=("T0",))
    by_topic["Economics"].append(dup)          # event 0 also carries Economics, not primary
    out = rank_home(by_topic, primary, CFG)
    assert ids(out).count(0) == 1
    assert next(c for c in out if c.event_id == 0).topic == "Technology"


def test_home_applies_publisher_cap_too():
    by_topic, primary = _home_pool()
    by_topic = {t: [cand(c.event_id, c.s, t, pubs=("Wired",)) for c in cs] for t, cs in by_topic.items()}
    out = rank_home(by_topic, primary, CFG)
    assert len(out) == 2


# ---- subtopics and stories -------------------------------------------------------------------------

def test_subtopic_filter():
    cs = [cand(1, 0.9, "Sports", subtopics=("Cricket",), pubs=("A",)),
          cand(2, 0.8, "Sports", subtopics=("Football",), pubs=("B",))]
    assert ids(rank_topic(cs, CFG, "Cricket")) == [1]


def test_story_replaces_its_member_events(seed, conn):
    sid = seed.story("Nvidia")
    members = [seed.event(["Technology"], [("Wired", f"n{i}", 1), ("The Verge", f"m{i}", 1)], story_id=sid)
               for i in range(6)]
    solo = seed.event(["Technology"], [("TechCrunch", "solo", 1)])
    seed.score()
    by_topic, _ = load_candidates(conn)
    keys = {(c.kind, c.event_id) for c in by_topic["Technology"]}
    assert ("story", sid) in keys and ("event", solo) in keys
    assert not any(("event", m) in keys for m in members)
