import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(seed, conn):
    seed.event(["Technology"], [("Wired", "Apple ships new chip", 3), ("The Verge", "Apple's new chip", 2),
                                ("ZDNet", "Apple chip review", 1), ("random.com", "Apple chip", 0.5, False)],
               subtopics=["Big Tech"])
    seed.event(["Sports"], [("ESPNcricinfo", "India beat Australia", 2), ("BBC Sport", "India win", 1)],
               subtopics=["Cricket"])
    sid = seed.story("Nvidia")
    for i in range(6):
        extra = [("Wired", "Nvidia CEO resigns", 1)] if i == 3 else []   # sub-event 3 scores highest
        seed.event(["Technology"], [("TechCrunch", f"Nvidia angle {i}", 1 + i), ("Ars Technica", f"Nv {i}", 1)]
                   + extra, story_id=sid)
    seed.score()
    conn.execute("INSERT INTO runs (started_at, finished_at, new_articles, failed_feeds) "
                 "VALUES ('2026-11-13T11:59:00+00:00','2026-11-13T12:00:00+00:00',5,'[\"GDELT\"]')")
    conn.commit()
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_home(client):
    items = client.get("/home").json()["items"]
    assert 1 <= len(items) <= 10
    first = items[0]
    for key in ("kind", "id", "rank", "headline", "summary", "publisher", "url", "first_reported_at",
                "sources", "breaking", "topic", "score"):
        assert key in first
    for key in ("publishers", "added_last_hour", "tier1_publishers", "tier1_list_size", "c", "v", "t",
                "age_hours", "s"):
        assert key in first["score"]
    assert [i["rank"] for i in items] == list(range(1, len(items) + 1))


def test_card_image_is_null_without_unsplash(client):
    assert all(i["image"] is None for i in client.get("/home").json()["items"])


def test_home_story_card(client):
    story = next(i for i in client.get("/home").json()["items"] if i["kind"] == "story")
    assert story["label"] == "Nvidia" and story["sub_event_count"] == 6 and story["sources"] == 3


def test_topic_alias_and_case(client):
    a = client.get("/topics/tech").json()
    b = client.get("/topics/TECHNOLOGY").json()
    assert a["topic"] == b["topic"] == "Technology"
    assert "Big Tech" in a["subtopics"]


def test_topic_subtopic_filter(client):
    r = client.get("/topics/sports", params={"subtopic": "cricket"}).json()
    assert r["subtopic"] == "Cricket"
    assert [i["headline"] for i in r["items"]][0].startswith("India")


def test_unknown_topic_and_subtopic_404(client):
    assert client.get("/topics/weather").status_code == 404
    assert client.get("/topics/sports", params={"subtopic": "golf"}).status_code == 404


def test_event_detail(client):
    eid = client.get("/topics/tech", params={"subtopic": "Big Tech"}).json()["items"][0]["id"]
    d = client.get(f"/events/{eid}").json()
    tiers = d["publishers_by_tier"]
    assert [p["publisher"] for p in tiers["1"]] == ["Wired", "The Verge"]
    assert [p["publisher"] for p in tiers["3"]] == ["ZDNet"]
    assert [p["publisher"] for p in tiers["other"]] == ["random.com"]
    times = [t["published_at"] for t in d["timeline"]]
    assert times == sorted(times) and len(times) == 4
    assert d["score"]["publishers"] == 3          # random.com is not counted
    assert set(d["score"]) >= {"c", "v", "t", "age_hours", "s"}


def test_story_detail(client):
    sid = next(i for i in client.get("/home").json()["items"] if i["kind"] == "story")["id"]
    d = client.get(f"/stories/{sid}").json()
    assert d["label"] == "Nvidia" and len(d["sub_events"]) == 6
    assert len(d["timeline"]) == 13


def test_story_detail_headline_matches_card(client):
    card = next(i for i in client.get("/home").json()["items"] if i["kind"] == "story")
    assert card["headline"] == "Nvidia angle 3"          # earliest Tier 1 report in the top sub-event
    assert client.get(f"/stories/{card['id']}").json()["headline"] == card["headline"]


def test_missing_event_404(client):
    assert client.get("/events/99999").status_code == 404


def test_health(client):
    h = client.get("/health").json()
    assert h["last_run_at"] == "2026-11-13T12:00:00+00:00"
    assert h["failed_feeds"] == ["GDELT"]
    assert h["article_count"] == 19 and h["event_count"] == 8


def test_detail_has_writeup_and_topic(client):
    story = next(i for i in client.get("/home").json()["items"] if i["kind"] == "story")
    d = client.get(f"/stories/{story['id']}").json()
    assert d["topic"] == "Technology"
    w = d["writeup"]
    assert w["engine"] == "extractive" and w["sections"][0]["key"] == "what"
    assert [s["publisher"] for s in w["sources"]][:1] and all("passages" in s for s in w["sources"])
