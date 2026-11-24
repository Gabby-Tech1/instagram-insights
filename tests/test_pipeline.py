from datetime import datetime

from insights.analytics import analyse, classify_topic, rule_based_insights
from insights.intelligence import recommend
from insights.models import Post
from insights.sources import MockSource
from insights.store import Store


def test_post_metrics():
    p = Post(id="1", media_type="REEL", caption="Hello #coffee #v60", timestamp=datetime(2026, 1, 1),
             likes=80, comments=10, saves=5, shares=5, reach=1000)
    assert p.interactions == 100
    assert p.engagement_rate == 0.1
    assert p.hashtags == ["coffee", "v60"]


def test_zero_reach_has_no_engagement_rate():
    assert Post(id="1", media_type="IMAGE", caption="", timestamp=datetime(2026, 1, 1)).engagement_rate is None


def test_topic_ignores_filler_and_hashtags():
    assert classify_topic("How to brew a V60") == "tutorial"
    assert classify_topic("20% off this weekend") == "promo"
    assert classify_topic("Everything we've learned") == "other"


def test_store_upsert_is_idempotent(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    posts = MockSource().fetch_posts(10)
    store.upsert(posts)
    store.upsert(posts)
    assert len(store.all_posts()) == 10


def test_analysis_finds_planted_patterns():
    stats = analyse(MockSource().fetch_posts(500))
    best_topic = max((s for s in stats["by_topic"] if s["reliable"]), key=lambda s: s["lift"])
    worst_topic = min((s for s in stats["by_topic"] if s["reliable"]), key=lambda s: s["lift"])
    best_reach_fmt = max(stats["by_format"], key=lambda s: s["reach_lift"])
    assert best_topic["segment"] == "tutorial"
    assert worst_topic["segment"] == "promo"
    assert best_reach_fmt["segment"] == "REEL"
    assert rule_based_insights(stats)


def test_tiny_reach_gives_no_engagement_rate():
    # Meta reports reach 0-1 on some older posts; that must not become a 1500% ER
    p = Post(id="1", media_type="REEL", caption="", timestamp=datetime(2026, 1, 1), likes=13, saves=2, reach=1)
    assert p.engagement_rate is None


def test_small_account_gets_testing_plan_not_fake_patterns():
    posts = [
        Post(id="1", media_type="REEL", caption="", timestamp="2023-06-25T07:57:35+0000", likes=13, saves=2, reach=1),
        Post(id="2", media_type="IMAGE", caption="", timestamp="2023-06-24T22:56:32+0000", likes=5, reach=0),
    ]
    posts = [Post.from_dict(p.__dict__) for p in posts]  # exercises timestamp parsing
    stats = analyse(posts)
    assert stats["overview"]["enough_data"] is False
    assert stats["overview"]["save_rate"] is None  # reach of 1 must not produce a 200% save rate
    assert rule_based_insights(stats) == []
    recs = recommend(stats, use_llm=False)
    assert "testing plan" in recs["summary"]


def test_rule_based_recommendations_without_llm():
    recs = recommend(analyse(MockSource().fetch_posts(500)), use_llm=False)
    assert recs["engine"] == "rule-based"
    assert len(recs["recommendations"]) >= 3
    assert all(r["evidence"] for r in recs["recommendations"])
