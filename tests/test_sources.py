"""Instagram and CSV sources, tested against fake API responses (no network)."""
import json

import pytest

from insights import sources
from insights.sources import CSVSource, InstagramSource, get_source


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    """Routes GET requests to a handler(url, params) -> (status, body) and logs them."""

    def __init__(self, handler):
        self.handler, self.log = handler, []

    def get(self, url, params=None, timeout=None):
        self.log.append((url, dict(params or {})))
        return FakeResponse(*self.handler(url, params or {}))


MEDIA = {"id": "m1", "caption": "How to brew #coffee", "media_type": "VIDEO", "media_product_type": "REELS",
         "timestamp": "2026-01-05T18:30:00+0000", "permalink": "https://instagram.com/p/m1", "like_count": 40,
         "comments_count": 4}
INSIGHTS = [{"name": n, "values": [{"value": v}]} for n, v in [("reach", 900), ("saved", 12), ("shares", 3), ("views", 2000)]]


def test_instagram_login_token_uses_graph_instagram_and_paginates():
    page2 = dict(MEDIA, id="m2", media_type="CAROUSEL_ALBUM", media_product_type="FEED")

    def handler(url, params):
        if url.endswith("/me/media"):
            return 200, {"data": [MEDIA], "paging": {"next": "https://graph.instagram.com/next-page"}}
        if url == "https://graph.instagram.com/next-page":
            return 200, {"data": [page2]}
        if url.endswith("/insights"):
            return 200, {"data": INSIGHTS}
        return 404, {}

    src = InstagramSource(access_token="IGAAtest")
    src.session = FakeSession(handler)
    posts = src.fetch_posts(limit=10)

    assert [p.id for p in posts] == ["m1", "m2"]
    assert posts[0].media_type == "REEL" and posts[1].media_type == "CAROUSEL"
    assert (posts[0].reach, posts[0].saves, posts[0].shares, posts[0].views) == (900, 12, 3, 2000)
    assert posts[0].timestamp.hour == 18  # stored as UTC
    assert all(u.startswith("https://graph.instagram.com") for u, _ in src.session.log)
    # paging URL already carries the token - it must not be added again
    assert ("https://graph.instagram.com/next-page", {}) in src.session.log


def test_facebook_token_requires_instagram_user_id():
    with pytest.raises(ValueError, match="IG_USER_ID"):
        InstagramSource(access_token="EAAtest")


def test_facebook_token_falls_back_to_per_metric_insights():
    def handler(url, params):
        if url.endswith("/17841/media"):
            return 200, {"data": [MEDIA]}
        if url.endswith("/insights"):
            metric = params["metric"]
            if "," in metric or metric == "shares":  # batch rejected; 'shares' unsupported
                return 400, {"error": {"message": "invalid metric"}}
            return 200, {"data": [m for m in INSIGHTS if m["name"] == metric]}
        return 404, {}

    src = InstagramSource(access_token="EAAtest", user_id="17841")
    src.session = FakeSession(handler)
    [post] = src.fetch_posts()
    assert src.session.log[0][0].startswith("https://graph.facebook.com/")
    assert (post.reach, post.saves, post.views) == (900, 12, 2000)
    assert post.shares == 0  # missing metric becomes 0 instead of failing the sync


def test_rate_limit_is_retried(monkeypatch):
    monkeypatch.setattr(sources.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def handler(url, params):
        if url.endswith("/me/media"):
            calls["n"] += 1
            return (429, {"error": "slow down"}) if calls["n"] == 1 else (200, {"data": []})
        return 404, {}

    src = InstagramSource(access_token="IGAAtest")
    src.session = FakeSession(handler)
    assert src.fetch_posts() == [] and calls["n"] == 2


def test_api_errors_never_leak_the_token():
    src = InstagramSource(access_token="IGAAsecret123")
    src.session = FakeSession(lambda url, params: (400, {"error": "bad token IGAAsecret123"}))
    with pytest.raises(RuntimeError) as e:
        src.fetch_posts()
    assert "IGAAsecret123" not in str(e.value)


def test_csv_source(tmp_path):
    f = tmp_path / "posts.csv"
    f.write_text("id,media_type,caption,timestamp,likes,comments,reach\n"
                 "a,reel,Hello,2026-01-01T10:00:00,10,2,100\n"
                 "b,Carousel,,2026-01-02T10:00:00,5,0,\n")
    posts = get_source("csv", path=str(f)).fetch_posts()
    assert [(p.id, p.media_type, p.likes, p.reach) for p in posts] == [("a", "REEL", 10, 100), ("b", "CAROUSEL", 5, 0)]


def test_csv_source_reports_missing_columns(tmp_path):
    f = tmp_path / "bad.csv"
    f.write_text("id,media_type,timestamp\nx,REEL,\n")
    with pytest.raises(ValueError, match="line 2: missing timestamp"):
        CSVSource(str(f)).fetch_posts()


def test_unknown_source():
    with pytest.raises(ValueError, match="Unknown source"):
        get_source("tiktok")
