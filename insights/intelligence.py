"""Intelligence layer: turns computed stats into content recommendations.

- With Claude available: Claude reasons over the computed stats (never raw posts)
  and returns schema-validated JSON in which every recommendation cites evidence
  and the post IDs it builds on.
- Without it, or on any API failure: a deterministic rule-based engine produces
  recommendations from the same stats, so the system always works.
- Either way, `grounding.check_all` then verifies the cited numbers against the data.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Dict, List

from .analytics import rule_based_insights
from .grounding import check_all
from .llm import MODEL, LLMError, claude_json, llm_available

log = logging.getLogger(__name__)

RECOMMENDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"insight": {"type": "string"}, "evidence": {"type": "string"}},
                "required": ["insight", "evidence"],
                "additionalProperties": False,
            },
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "format": {"type": "string", "enum": ["REEL", "CAROUSEL", "IMAGE"]},
                    "topic": {"type": "string"},
                    "style": {"type": "string"},
                    "best_day": {"type": "string"},
                    "best_time": {"type": "string"},
                    "caption_draft": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "why": {"type": "string"},
                    "evidence": {"type": "string"},
                    "based_on_posts": {"type": "array", "items": {"type": "string"}},
                    "goal": {"type": "string", "enum": ["engagement", "reach", "both"]},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["title", "format", "topic", "style", "best_day", "best_time", "caption_draft",
                             "hashtags", "why", "evidence", "based_on_posts", "goal", "priority"],
                "additionalProperties": False,
            },
        },
        "underperforming": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"area": {"type": "string"}, "evidence": {"type": "string"}, "suggestion": {"type": "string"}},
                "required": ["area", "evidence", "suggestion"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "key_insights", "recommendations", "underperforming"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a social media strategist analysing one Instagram account's performance data.

You receive pre-computed statistics, not raw posts. Group stats include `lift` (engagement rate vs the
account average, 1.0 = average) and `reach_lift` (reach vs average). Groups with `reliable: false` have
fewer than 3 measurable posts; do not base recommendations on them. `trend` compares the earlier half of
posts with the recent half. `top_posts` and `bottom_posts` are the best and worst posts by engagement rate.

Rules:
- Ground every insight, recommendation and improvement in specific numbers from the data and state them in
  `evidence` exactly as they appear (e.g. "Tutorials: 1.33x avg engagement across 22 posts"). Never invent
  or estimate a number. Every number you cite is automatically checked against the data.
- Write every number the way a person reads it: lifts as "1.33x", rates and changes as percentages
  ("11.82%", "down 6%"), reach and counts as whole numbers. Never put internal field names (reach_lift,
  avg_saves, bottom_posts) or raw fractions (0.1182) in any text the user reads.
- Refer to posts by a few words of their caption, never by ID. IDs go only in `based_on_posts`, which lists
  the top/bottom posts a recommendation builds on (copy them exactly).
- Combine signals: pick the format, topic, style, day and time window the data supports together.
- Say in `goal` whether a recommendation is meant to grow engagement, reach, or both.
- Post ideas must be specific (a concrete subject for the next post, not a category), and caption drafts
  should match the account's voice as shown in its top posts.
- `underperforming`: the weakest areas, each with a concrete, data-backed suggestion to improve them.
- Be concrete and brief. No generic social media advice that the data doesn't support.
- Give 5 recommendations, ordered by expected impact, and 2-4 underperforming areas.
- If `overview.enough_data` is false, the account has too few posts for reliable patterns. Say so plainly
  in the summary, do not present any pattern as proven, and make the recommendations a 4-week testing plan
  (which formats, topics and times to try, and how many posts each) so the account builds the data it needs."""


def build_llm_payload(stats: Dict, account_context: str = "") -> Dict:
    """Exactly what the LLM receives. Exposed in the API/dashboard for transparency."""
    return {
        "account_context": account_context or "not provided",
        "stats": stats,
        "rule_based_insights": rule_based_insights(stats),
    }


def recommend(stats: Dict, account_context: str = "", use_llm: bool = True) -> Dict:
    payload = build_llm_payload(stats, account_context)
    result = None
    if use_llm and llm_available():
        try:
            result = claude_json(
                SYSTEM_PROMPT,
                "Here is the account's performance data. Produce the content strategy.\n\n"
                + json.dumps(payload, indent=1, default=str),
                RECOMMENDATION_SCHEMA,
            )
            result["engine"] = f"claude ({MODEL})"
        except LLMError as e:  # never let the LLM take the whole pipeline down
            log.warning("LLM recommendations failed, falling back to rules: %s", e)
    if result is None:
        result = _recommend_with_rules(stats, payload["rule_based_insights"])
        result["engine"] = "rule-based"
    result["mode"] = "data-driven" if stats["overview"]["enough_data"] else "testing plan"
    return check_all(result, stats)


# ---------------------------------------------------------------- rule-based engine

def _usable(stats: Dict, key: str, lift: str) -> List[Dict]:
    with_value = [s for s in stats[key] if s[lift] is not None]
    return [s for s in with_value if s["reliable"]] or with_value


def _best(stats: Dict, key: str, lift: str = "lift") -> Dict:
    return max(_usable(stats, key, lift), key=lambda s: s[lift])


def _worst(stats: Dict, key: str, lift: str = "lift") -> Dict:
    return min(_usable(stats, key, lift), key=lambda s: s[lift])


def _label(s: str) -> str:
    return str(s).replace("_", " ")


def _top_hashtags(stats: Dict, n: int) -> List[str]:
    counts = Counter(h.lower() for p in stats["top_posts"] for h in p.get("hashtags", []))
    return [h for h, _ in counts.most_common(n)]


def _testing_plan(stats: Dict) -> Dict:
    """For new or small accounts: no fake patterns, just a plan to collect real data."""
    o = stats["overview"]
    have = o["posts_with_engagement_data"]
    seen = ", ".join(f"{p['media_type'].lower()} ({p['likes']} likes, reach {p['reach']})" for p in stats["top_posts"][:3])
    note = f"Only {have} post(s) with usable reach data (10+ needed). So far: {seen or 'no posts'}."

    def step(title, fmt, topic, when, why, priority):
        return {"title": title, "format": fmt, "topic": topic, "style": "mixed", "best_day": when[0], "best_time": when[1],
                "caption_draft": "", "hashtags": [], "why": why, "evidence": note, "based_on_posts": [],
                "goal": "both", "priority": priority}

    return {
        "summary": f"{o['posts_analysed']} posts found, but only {have} have enough reach data to measure. "
                   f"That's too few to find reliable patterns, so this is a 4-week testing plan to build that data. "
                   f"Run the analysis again after about 12 posts.",
        "key_insights": [{"insight": "Not enough posts yet for reliable patterns.", "evidence": note}],
        "recommendations": [
            step("Post 3 times a week for 4 weeks", "REEL", "mixed", ("Tue / Thu / Sat", "vary times"),
                 "Consistent posting creates the sample size the analysis needs.", "high"),
            step("Split formats evenly: Reels vs carousels", "REEL", "mixed", ("any", "any"),
                 "Comparing formats on your own audience shows which drives reach and which drives engagement.", "high"),
            step("Rotate 3 content themes", "CAROUSEL", "your niche: tips, behind the scenes, results", ("any", "any"),
                 "Rotating themes lets topic performance be compared fairly.", "medium"),
            step("Alternate morning and evening posting", "REEL", "mixed", ("any", "morning vs 18-22"),
                 "Shows when your audience is actually active.", "medium"),
            step("End every caption with a clear ask", "CAROUSEL", "any", ("any", "any"),
                 "Save / comment / share prompts give comparable engagement signals.", "low"),
        ],
        "underperforming": [],
    }


def _recommend_with_rules(stats: Dict, insights: List[Dict]) -> Dict:
    if not stats["overview"]["enough_data"]:
        return _testing_plan(stats)

    topics = sorted((s for s in stats["by_topic"] if s["reliable"] and s["lift"] is not None),
                    key=lambda s: s["lift"], reverse=True)
    eng_fmt, reach_fmt = _best(stats, "by_format"), _best(stats, "by_format", "reach_lift")
    style = _best(stats, "by_style")
    day, window = _best(stats, "by_weekday", "reach_lift"), _best(stats, "by_time_window", "reach_lift")
    tag_bucket = _best(stats, "by_hashtag_count", "reach_lift")
    n_tags = {"none": 0, "1-2": 2, "3-6": 5, "7-15": 8, "16+": 10}.get(tag_bucket["segment"], 5)
    hashtags = _top_hashtags(stats, n_tags)
    when = (day["segment"], window["segment"])
    timing = f"{day['segment']} {day['reach_lift']:.2f}x reach, {window['segment']} {window['reach_lift']:.2f}x reach"

    recs = []
    for i, topic in enumerate(topics[:3]):
        fmt, goal = (eng_fmt, "engagement") if i % 2 == 0 else (reach_fmt, "reach")
        example = next((p for p in stats["top_posts"] if p["topic"] == topic["segment"]), None)
        idea = f"Follow up on your top {_label(topic['segment'])} post \"{example['caption'][:70]}\" " \
               f"({example['engagement_rate']:.2%} engagement) with a new angle on the same subject. " if example else ""
        recs.append({
            "title": f"More {_label(topic['segment'])} as {fmt['segment'].lower()}s",
            # style of the proven post this builds on; account-wide best style otherwise
            "format": fmt["segment"], "topic": topic["segment"], "style": example["style"] if example else style["segment"],
            "best_day": when[0], "best_time": when[1], "caption_draft": "", "hashtags": hashtags,
            "why": idea + f"Pairs your strongest topic with the format that best drives {goal}.",
            "evidence": f"{_label(topic['segment'])}: {topic['lift']:.2f}x engagement ({topic['posts']} posts); "
                        f"{fmt['segment']}: {fmt['lift']:.2f}x engagement, {fmt['reach_lift']:.2f}x reach; {timing}.",
            "based_on_posts": [example["id"]] if example else [],
            "goal": goal, "priority": "high" if i == 0 else "medium",
        })

    q = {s["segment"]: s for s in stats["by_question"]}
    if "asks a question" in q and "no question" in q and q["asks a question"]["reliable"] \
            and (q["asks a question"]["lift"] or 0) > (q["no question"]["lift"] or 0) + 0.05:
        a, b = q["asks a question"], q["no question"]
        recs.append({
            "title": "End captions with a question", "format": eng_fmt["segment"], "topic": "any",
            "style": "question / conversation", "best_day": when[0], "best_time": when[1], "caption_draft": "",
            "hashtags": [], "why": "Questions invite comments, which drive engagement.",
            "evidence": f"Posts that ask a question: {a['lift']:.2f}x engagement, {a['avg_comments']:.1f} avg comments "
                        f"vs {b['avg_comments']:.1f} without ({a['posts']} posts).",
            "based_on_posts": [], "goal": "engagement", "priority": "medium",
        })
    recs.append({
        "title": f"Use {tag_bucket['segment']} hashtags per post", "format": reach_fmt["segment"], "topic": "any",
        "style": "any", "best_day": when[0], "best_time": when[1], "caption_draft": "", "hashtags": hashtags,
        "why": "Hashtag count is linked to how many people a post reaches. Suggested tags are the most used in your top posts.",
        "evidence": f"Posts with {tag_bucket['segment']} hashtags: {tag_bucket['reach_lift']:.2f}x average reach "
                    f"({tag_bucket['posts']} posts).",
        "based_on_posts": [p["id"] for p in stats["top_posts"][:3]], "goal": "reach", "priority": "low",
    })

    return {
        "summary": f"{stats['overview']['posts_analysed']} posts analysed, average engagement rate "
                   f"{stats['overview']['avg_engagement_rate']:.2%}. The biggest levers are content topic and format.",
        "key_insights": [{"insight": i["insight"], "evidence": f"{i['dimension']} ({i['metric']})"} for i in insights[:6]],
        "recommendations": recs[:5],
        "underperforming": _underperforming(stats),
    }


IMPROVE = {
    "by_topic": "Post fewer {w} pieces, or blend them into {b} content (e.g. teach something, then mention the offer).",
    "by_format": "Move some {w} posts to {b}; reuse the same ideas in the stronger format.",
    "by_style": "Rework {w} posts in the {b} style.",
    "by_time_window": "Shift posts from {w} to {b}.",
    "by_weekday": "Move {w} posts to {b}.",
}


def _underperforming(stats: Dict) -> List[Dict]:
    out = []
    for key, lift in [("by_topic", "lift"), ("by_format", "lift"), ("by_style", "lift"),
                      ("by_time_window", "reach_lift"), ("by_weekday", "reach_lift")]:
        segs = _usable(stats, key, lift)
        if len(segs) < 2:
            continue
        best, worst = max(segs, key=lambda s: s[lift]), min(segs, key=lambda s: s[lift])
        if best[lift] - worst[lift] < 0.15 or worst[lift] >= 0.95:
            continue
        word = "engagement" if lift == "lift" else "reach"
        out.append({
            "area": f"{_label(worst['segment'])} ({key.replace('by_', '').replace('_', ' ')})",
            "evidence": f"{_label(worst['segment'])}: {worst[lift]:.2f}x {word} ({worst['posts']} posts) "
                        f"vs {_label(best['segment'])}: {best[lift]:.2f}x.",
            "suggestion": IMPROVE[key].format(w=_label(worst["segment"]), b=_label(best["segment"])),
        })
    return out[:4]
