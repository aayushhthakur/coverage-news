import math

import pytest

from app.config import publishers, scoring, tier1_list
from app.scoring import coverage, decay, score, tier_score, velocity

W = {"coverage": 0.4, "velocity": 0.3, "tier": 0.3}


# ---- formula ------------------------------------------------------------------------------

def test_coverage_is_log_ratio():
    assert coverage(10, 39) == pytest.approx(math.log(11) / math.log(40))
    assert coverage(0, 39) == 0
    assert coverage(39, 39) == pytest.approx(1.0)


def test_velocity_is_share_added_in_last_hour():
    assert velocity(2, 4) == pytest.approx(0.5)
    assert velocity(4, 4) == 1.0


def test_velocity_is_zero_below_three_publishers():
    assert velocity(2, 2) == 0
    assert velocity(1, 1) == 0
    assert velocity(3, 3) == 1.0


def test_velocity_is_clamped():
    assert velocity(9, 4) == 1.0
    assert velocity(-1, 4) == 0


def test_tier_score():
    assert tier_score(2, 5) == pytest.approx(0.4)
    assert tier_score(0, 0) == 0


def test_decay_halves_every_half_life():
    assert decay(0, 6) == 1
    assert decay(6, 6) == pytest.approx(0.5)
    assert decay(12, 6) == pytest.approx(0.25)


def test_score_combines_weights_and_decay():
    s = score(0.5, 0.2, 0.4, 18, 18, W)
    assert s == pytest.approx((0.4 * 0.5 + 0.3 * 0.2 + 0.3 * 0.4) * 0.5)


def test_all_clickbait_halves_score():
    base = score(0.5, 0.2, 0.4, 0, 18, W)
    assert score(0.5, 0.2, 0.4, 0, 18, W, all_clickbait=True) == pytest.approx(base * 0.5)


def test_config_values_match_spec():
    cfg = scoring()
    assert cfg["weights"] == W
    assert cfg["half_life_hours"] == {"Sports": 6, "Technology": 18, "Geopolitics": 24, "Economics": 36}


# ---- database stage -------------------------------------------------------------------------

def _row(conn, eid, kind="event"):
    return conn.execute("SELECT * FROM scores WHERE kind=? AND event_id=? AND is_primary=1", (kind, eid)).fetchone()


def test_counts_distinct_publishers_not_articles(seed, conn):
    eid = seed.event(["Technology"], [("Wired", "a", 5), ("Wired", "b", 4), ("Wired", "c", 3),
                                      ("The Verge", "d", 2), ("The Verge", "e", 1)])
    seed.score()
    r = _row(conn, eid)
    assert r["p"] == 2
    assert r["c"] == pytest.approx(coverage(2, len(publishers())))
    assert r["v"] == 0                      # P < 3


def test_publishers_outside_feeds_are_not_counted(seed, conn):
    eid = seed.event(["Technology"], [("Wired", "a", 3), ("random.com", "b", 2, False)])
    seed.score()
    assert _row(conn, eid)["p"] == 1


def test_velocity_from_snapshot_an_hour_ago(seed, conn):
    eid = seed.event(["Geopolitics"], [("BBC News", "a", 5), ("NPR", "b", 4), ("Al Jazeera", "c", 3),
                                       ("France 24", "d", 0.5), ("Sky News", "e", 0.2)])
    seed.snapshot(eid, 1.25, 3)
    seed.score()
    r = _row(conn, eid)
    assert (r["p"], r["added_1h"]) == (5, 2)
    assert r["v"] == pytest.approx(0.4)


def test_velocity_falls_back_to_article_times_without_snapshot(seed, conn):
    eid = seed.event(["Geopolitics"], [("BBC News", "a", 5), ("NPR", "b", 4), ("Al Jazeera", "c", 0.5),
                                       ("France 24", "d", 0.2)])
    seed.score()
    assert _row(conn, eid)["v"] == pytest.approx(2 / 4)


def test_tier1_fraction_uses_topic_list(seed, conn):
    eid = seed.event(["Sports"], [("BBC Sport", "a", 2), ("ESPN", "b", 1), ("CBS Sports", "c", 1)])
    seed.score()
    r = _row(conn, eid)
    assert r["tier1"] == 2 and r["tier1_size"] == len(tier1_list("Sports"))
    assert r["t"] == pytest.approx(2 / len(tier1_list("Sports")))


def test_age_uses_latest_article_and_topic_half_life(seed, conn):
    eid = seed.event(["Sports"], [("BBC Sport", "a", 20), ("ESPN", "b", 6)])
    seed.score()
    r = _row(conn, eid)
    assert r["age_hours"] == pytest.approx(6)
    assert r["decay"] == pytest.approx(0.5)


def test_event_where_every_headline_is_clickbait_is_halved(seed, conn):
    bait = seed.event(["Technology"], [("Wired", "You won't believe what Apple did", 1),
                                       ("The Verge", "This one trick changes phones forever", 1)])
    fair = seed.event(["Technology"], [("Wired", "Apple releases new iPhone", 1),
                                       ("The Verge", "This one trick changes phones forever", 1)])
    seed.score()
    b, f = _row(conn, bait), _row(conn, fair)
    assert b["all_clickbait"] == 1 and f["all_clickbait"] == 0
    assert b["s"] == pytest.approx(f["s"] * 0.5)


def test_multi_topic_event_scored_per_topic(seed, conn):
    eid = seed.event(["Technology", "Economics"], [("BBC News", "a", 9)])
    seed.score()
    rows = {r["topic"]: r for r in conn.execute("SELECT * FROM scores WHERE event_id=?", (eid,))}
    assert set(rows) == {"Technology", "Economics"}
    assert rows["Technology"]["is_primary"] == 1
    assert rows["Technology"]["decay"] == pytest.approx(decay(9, 18))
    assert rows["Economics"]["decay"] == pytest.approx(decay(9, 36))


def test_story_scored_over_union_of_member_publishers(seed, conn):
    sid = seed.story("Nvidia")
    seed.event(["Technology"], [("Wired", "a", 3), ("The Verge", "b", 2)], story_id=sid)
    seed.event(["Technology"], [("Wired", "c", 3), ("TechCrunch", "d", 1), ("Engadget", "e", 1)], story_id=sid)
    seed.score()
    assert _row(conn, sid, "story")["p"] == 4
