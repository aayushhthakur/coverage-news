from datetime import timedelta

import httpx
import pytest

from app import images as img
from app.images import Unsplash, assign_images, image_for, query_for

from .conftest import NOW


def photo(pid):
    return {"id": pid, "urls": {"raw": f"https://images.unsplash.com/{pid}?ixid=x"}, "color": "#334455",
            "blur_hash": "LKO2", "alt_description": f"alt {pid}",
            "user": {"name": f"Ann {pid}", "links": {"html": f"https://unsplash.com/@{pid}"}},
            "links": {"html": f"https://unsplash.com/photos/{pid}", "download_location": f"/photos/{pid}/download"}}


class FakeUnsplash:
    def __init__(self, per_query=5, remaining=None, fail=False):
        self.searches, self.pings = [], []
        self.per_query, self.remaining, self.fail = per_query, remaining, fail

    def search(self, query, per_page):
        if self.fail:
            raise httpx.ConnectError("down")
        self.searches.append(query)
        return [photo(f"{query.replace(' ', '-')}-{i}") for i in range(self.per_query)]

    def ping_download(self, loc):
        self.pings.append(loc)


@pytest.fixture
def ranked_world(seed):
    """Two Sports/Cricket events, one Sports event with no subtopic, one Tech/AI event."""
    ids = {
        "cricket1": seed.event(["Sports"], [("ESPNcricinfo", "c1", 1), ("BBC Sport", "c1b", 1)], subtopics=["Cricket"]),
        "cricket2": seed.event(["Sports"], [("Sky Sports", "c2", 2)], subtopics=["Cricket"]),
        "sport": seed.event(["Sports"], [("ESPN", "s", 1)]),
        "ai": seed.event(["Technology"], [("Wired", "a", 1), ("The Verge", "b", 1)], subtopics=["AI"]),
    }
    seed.score()
    return ids


def test_disabled_without_key(conn, ranked_world, monkeypatch):
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", "")
    assert "disabled" in assign_images(conn, now=NOW)["images"]


def test_query_uses_subtopic_then_topic():
    assert query_for("Sports", ["Cricket"]) == "cricket match"
    assert query_for("Sports", []) == "stadium lights"


def test_assigns_every_ranked_item_one_search_per_query(conn, ranked_world):
    fake = FakeUnsplash()
    stats = assign_images(conn, fake, now=NOW)
    assert stats["images_assigned"] == 4
    assert sorted(fake.searches) == ["cricket match", "neural network abstract", "stadium lights"]
    assert image_for(conn, "event", ranked_world["cricket1"])["raw"].startswith("https://images.unsplash.com/cricket-match")


def test_photos_on_screen_are_not_repeated(conn, ranked_world):
    assign_images(conn, FakeUnsplash(per_query=5), now=NOW)
    a = image_for(conn, "event", ranked_world["cricket1"])["raw"]
    b = image_for(conn, "event", ranked_world["cricket2"])["raw"]
    assert a != b


def test_pool_is_cached_between_runs(conn, ranked_world, seed):
    assign_images(conn, FakeUnsplash(), now=NOW)
    seed.event(["Sports"], [("CBS Sports", "c3", 1)], subtopics=["Cricket"])
    seed.score()
    fake = FakeUnsplash()
    stats = assign_images(conn, fake, now=NOW + timedelta(minutes=15))
    assert fake.searches == [] and stats["images_assigned"] == 1


def test_existing_assignment_is_kept(conn, ranked_world):
    assign_images(conn, FakeUnsplash(), now=NOW)
    before = image_for(conn, "event", ranked_world["ai"])["raw"]
    assign_images(conn, FakeUnsplash(), now=NOW + timedelta(hours=1))
    assert image_for(conn, "event", ranked_world["ai"])["raw"] == before


def test_stale_pool_is_refreshed(conn, ranked_world, seed):
    assign_images(conn, FakeUnsplash(), now=NOW)
    seed.event(["Technology"], [("Engadget", "new ai", 0.5)], subtopics=["AI"])
    seed.score()
    fake = FakeUnsplash()
    assign_images(conn, fake, now=NOW + timedelta(hours=25))
    assert fake.searches == ["neural network abstract"]


def test_download_pinged_once_per_photo(conn, ranked_world):
    fake = FakeUnsplash()
    stats = assign_images(conn, fake, now=NOW)
    assert stats["pings"] == 4 and len(set(fake.pings)) == 4
    fake2 = FakeUnsplash()
    assign_images(conn, fake2, now=NOW)
    assert fake2.pings == []


def test_request_budget_per_run(conn, ranked_world, monkeypatch):
    original = img.images()
    patched = {**original, "unsplash": {**original["unsplash"], "max_requests_per_run": 2}}
    monkeypatch.setattr(img, "images", lambda: patched)
    fake = FakeUnsplash()
    assign_images(conn, fake, now=NOW)
    assert len(fake.searches) + len(fake.pings) == 2


def test_stops_when_rate_limit_nearly_used(conn, ranked_world):
    fake = FakeUnsplash(remaining=3)          # below min_remaining (5)
    stats = assign_images(conn, fake, now=NOW)
    assert fake.searches == [] and stats["images_assigned"] == 0


def test_search_failure_does_not_raise(conn, ranked_world):
    stats = assign_images(conn, FakeUnsplash(fail=True), now=NOW)
    assert stats["image_errors"] >= 1 and stats["images_assigned"] == 0


def test_image_payload_has_credit_with_utm(conn, ranked_world):
    assign_images(conn, FakeUnsplash(), now=NOW)
    im = image_for(conn, "event", ranked_world["ai"])
    assert im["illustrative"] is True
    assert im["credit"]["name"].startswith("Ann ")
    for k in ("profile_url", "photo_url", "unsplash_url"):
        assert "utm_source=coverage_prototype&utm_medium=referral" in im["credit"][k]


def test_client_sends_key_and_reads_rate_limit():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"results": [photo("p1")]}, headers={"X-Ratelimit-Remaining": "41"})

    http = httpx.Client(base_url="https://api.unsplash.com", transport=httpx.MockTransport(handler),
                        headers={"Authorization": "Client-ID k123"})
    client = Unsplash("k123", http=http)
    assert client.search("rocket launch", 20)[0]["id"] == "p1"
    assert seen["auth"] == "Client-ID k123" and client.remaining == 41
    assert seen["params"]["orientation"] == "landscape" and seen["params"]["content_filter"] == "high"
