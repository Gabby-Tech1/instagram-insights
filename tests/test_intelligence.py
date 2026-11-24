"""Intelligence layer: the Claude path (with a fake client), fallbacks, tagging and grounding."""
import json

from insights.analytics import analyse
from insights.grounding import check_recommendation
from insights.intelligence import build_llm_payload, recommend
from insights.sources import MockSource
from insights.store import Store
from insights.tagging import tag_posts

from .conftest import as_json


def _stats():
    return analyse(MockSource().fetch_posts(500))


def _llm_recs(stats, evidence_list):
    top = stats["top_posts"][0]["id"]
    return {
        "summary": "s", "key_insights": [{"insight": "i", "evidence": "e"}], "underperforming": [],
        "recommendations": [
            {"title": f"r{i}", "format": "CAROUSEL", "topic": "tutorial", "style": "how-to / tutorial",
             "best_day": "Tuesday", "best_time": "evening", "caption_draft": "c", "hashtags": ["coffee"],
             "why": "w", "evidence": ev, "based_on_posts": [top], "goal": "engagement", "priority": "high"}
            for i, ev in enumerate(evidence_list)
        ],
    }


def test_claude_path_uses_stats_and_grounding_flags_invented_numbers(fake_claude):
    stats = _stats()
    tut = next(s for s in stats["by_topic"] if s["segment"] == "tutorial")
    real = f"Tutorials: {tut['lift']:.2f}x engagement ({tut['posts']} posts)"
    fake = "Tutorials: 3.47x engagement"
    calls = fake_claude(lambda kw: ("end_turn", as_json(_llm_recs(stats, [real, fake]))))

    recs = recommend(stats, account_context="coffee brand")

    assert recs["engine"].startswith("claude")
    assert [r["grounding"]["grounded"] for r in recs["recommendations"]] == [True, False]
    assert recs["recommendations"][1]["grounding"]["unmatched_numbers"] == ["3.47x"]
    assert (recs["grounding_summary"]["verified"], recs["grounding_summary"]["total"]) == (1, 2)
    # what was sent: computed stats + structured output schema, not raw posts
    sent = calls[0]
    payload = json.loads(sent["messages"][0]["content"].split("\n\n", 1)[1])
    assert payload["account_context"] == "coffee brand"
    assert set(payload) == {"account_context", "stats", "rule_based_insights"}
    assert sent["output_config"]["format"]["type"] == "json_schema"


def test_summary_and_improvement_numbers_are_checked_too(fake_claude):
    stats = _stats()
    body = _llm_recs(stats, ["1.00x"])
    body["summary"] = "Tutorials earn 9.99x more than average."
    body["underperforming"] = [{"area": "promo", "evidence": "promo is 0.12x", "suggestion": "s"}]
    fake_claude(lambda kw: ("end_turn", as_json(body)))
    g = recommend(stats)["grounding_summary"]
    assert g["other_numbers_cited"] == 2 and g["other_numbers_unmatched"] == ["9.99x", "0.12x"]


def test_refusal_falls_back_to_rules(fake_claude):
    fake_claude(lambda kw: ("refusal", ""))
    recs = recommend(_stats())
    assert recs["engine"] == "rule-based" and recs["recommendations"]


def test_invalid_json_falls_back_to_rules(fake_claude):
    fake_claude(lambda kw: ("end_turn", "not json"))
    assert recommend(_stats())["engine"] == "rule-based"


def test_rule_based_recommendations_are_grounded_and_actionable():
    recs = recommend(_stats(), use_llm=False)
    assert recs["mode"] == "data-driven"
    assert recs["grounding_summary"]["verified"] == len(recs["recommendations"])
    assert recs["underperforming"] and all(u["suggestion"] for u in recs["underperforming"])
    assert any(r["based_on_posts"] for r in recs["recommendations"])


def test_grounding_rejects_unknown_posts_and_formats():
    stats = _stats()
    rec = {"evidence": "1.00x", "based_on_posts": ["made-up-id"], "format": "STORY"}
    g = check_recommendation(rec, stats)
    assert g["unknown_posts"] == ["made-up-id"] and not g["format_in_data"] and not g["grounded"]


def test_llm_payload_is_what_the_api_exposes():
    payload = build_llm_payload(_stats(), "ctx")
    assert payload["rule_based_insights"] and payload["stats"]["overview"]["posts_analysed"] == 96


def test_llm_tagging_is_cached_by_caption(fake_claude, tmp_path):
    posts = MockSource().fetch_posts(5)

    def handler(kw):
        ids = [c["id"] for c in json.loads(kw["messages"][0]["content"])["captions"]]
        return "end_turn", as_json({"tags": [{"id": i, "topic": "Coffee Craft", "style": "showcase / aesthetic"} for i in ids]})

    calls = fake_claude(handler)
    store = Store(str(tmp_path / "t.db"))
    tags, tagger = tag_posts(posts, store=store)
    assert tagger == "claude" and tags[posts[0].id] == {"topic": "coffee craft", "style": "showcase / aesthetic"}
    tags2, _ = tag_posts(posts, store=store)
    assert len(calls) == 1 and tags2 == tags  # second run served from cache


def test_tagging_falls_back_to_keywords_on_llm_failure(fake_claude):
    fake_claude(lambda kw: ("refusal", ""))
    tags, tagger = tag_posts(MockSource().fetch_posts(3))
    assert tagger == "keywords" and all(t["topic"] for t in tags.values())
