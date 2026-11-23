"""Intelligence layer: turns computed stats into content recommendations.

- With ANTHROPIC_API_KEY set: Claude reasons over the stats (never raw data)
  and returns schema-validated JSON where every recommendation cites evidence.
- Without it (or on any API failure): a deterministic rule-based engine
  produces recommendations from the same stats, so the system always works.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Dict, List

from .analytics import rule_based_insights

log = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")

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
                    "best_day": {"type": "string"},
                    "best_time": {"type": "string"},
                    "caption_draft": {"type": "string"},
                    "hashtags": {"type": "array", "items": {"type": "string"}},
                    "why": {"type": "string"},
                    "evidence": {"type": "string"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["title", "format", "topic", "best_day", "best_time", "caption_draft",
                             "hashtags", "why", "evidence", "priority"],
                "additionalProperties": False,
            },
        },
        "stop_doing": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "key_insights", "recommendations", "stop_doing"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are a social media strategist analysing one Instagram account's performance data.

You receive pre-computed statistics, not raw posts. Segment stats include `lift` (engagement rate
vs the account average, 1.0 = average) and `reach_lift` (reach vs average). Segments with
`reliable: false` have fewer than 3 posts; do not base recommendations on them.

Rules:
- Ground every insight and recommendation in a specific number from the data, and state it in `evidence`
  (e.g. "Tutorials: 1.33x avg engagement across 22 posts").
- Combine signals: a recommendation should pick the format, topic, day and time window that the data
  supports together, not just one dimension.
- Distinguish engagement (people who saw it interacted) from reach (how many saw it); say which one a
  recommendation is meant to grow.
- Caption drafts should match the account's voice, shown in its top posts, and include a call to action
  where the data supports one.
- Be concrete and brief. No generic social media advice that the data doesn't support.
- Give 5 recommendations, ordered by expected impact, and up to 3 things to stop doing."""


def _has_credentials() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def recommend(stats: Dict, account_context: str = "", use_llm: bool = True) -> Dict:
    insights = rule_based_insights(stats)
    if use_llm and _has_credentials():
        try:
            result = _recommend_with_claude(stats, insights, account_context)
            result["engine"] = f"claude ({MODEL})"
            return result
        except Exception as e:  # never let the LLM take the whole pipeline down
            log.warning("LLM recommendations failed, falling back to rules: %s", e)
    result = _recommend_with_rules(stats, insights)
    result["engine"] = "rule-based"
    return result


def _recommend_with_claude(stats: Dict, insights: List[Dict], account_context: str) -> Dict:
    import anthropic

    client = anthropic.Anthropic()
    payload = {"account_context": account_context or "not provided", "stats": stats, "rule_based_insights": insights}
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": "Here is the account's performance data. Produce the content strategy.\n\n"
                       + json.dumps(payload, indent=1, default=str),
        }],
        thinking={"type": "adaptive"},
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": RECOMMENDATION_SCHEMA}},
        # If a safety classifier declines, the API retries on a suitable model server-side.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"model declined: {getattr(response, 'stop_details', None)}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("response hit max_tokens before finishing")
    text = "".join(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def _best(stats: Dict, key: str, lift: str = "lift") -> Dict:
    segs = [s for s in stats[key] if s["reliable"]] or stats[key]
    return max(segs, key=lambda s: s[lift])


def _worst(stats: Dict, key: str) -> Dict:
    segs = [s for s in stats[key] if s["reliable"]] or stats[key]
    return min(segs, key=lambda s: s["lift"])


def _recommend_with_rules(stats: Dict, insights: List[Dict]) -> Dict:
    topics = sorted((s for s in stats["by_topic"] if s["reliable"]), key=lambda s: s["lift"], reverse=True)
    eng_fmt, reach_fmt = _best(stats, "by_format"), _best(stats, "by_format", "reach_lift")
    day = _best(stats, "by_weekday", "reach_lift")
    window = _best(stats, "by_time_window", "reach_lift")
    tags = _best(stats, "by_hashtag_count", "reach_lift")
    cta = next((s for s in stats["by_cta"] if s["segment"] == "with CTA"), None)
    when = f"{day['segment']}, {window['segment']}"

    recs = []
    for i, topic in enumerate(topics[:3]):
        fmt = eng_fmt if i % 2 == 0 else reach_fmt
        goal = "engagement" if fmt is eng_fmt else "reach"
        recs.append({
            "title": f"{topic['segment'].replace('_', ' ').title()} {fmt['segment'].lower()}",
            "format": fmt["segment"],
            "topic": topic["segment"],
            "best_day": day["segment"],
            "best_time": window["segment"],
            "caption_draft": "",
            "hashtags": [],
            "why": f"Pairs your strongest topic with the format that best drives {goal}.",
            "evidence": f"{topic['segment']}: {topic['lift']:.2f}x avg engagement ({topic['posts']} posts); "
                        f"{fmt['segment']}: {fmt['lift']:.2f}x engagement, {fmt['reach_lift']:.2f}x reach; "
                        f"{when}: best reach slot.",
            "priority": "high" if i == 0 else "medium",
        })
    recs.append({
        "title": f"Use {tags['segment']} hashtags per post",
        "format": eng_fmt["segment"], "topic": "any", "best_day": day["segment"], "best_time": window["segment"],
        "caption_draft": "", "hashtags": [],
        "why": "Hashtag count is linked to how many people a post reaches.",
        "evidence": f"Posts with {tags['segment']} hashtags: {tags['reach_lift']:.2f}x average reach ({tags['posts']} posts).",
        "priority": "medium",
    })
    if cta:
        recs.append({
            "title": "End captions with a clear call to action",
            "format": eng_fmt["segment"], "topic": "any", "best_day": day["segment"], "best_time": window["segment"],
            "caption_draft": "", "hashtags": [],
            "why": "Direct asks (save, comment, tag) drive the interactions Instagram ranks on.",
            "evidence": f"With CTA: {cta['avg_comments']:.1f} avg comments, {cta['lift']:.2f}x engagement ({cta['posts']} posts).",
            "priority": "low",
        })

    worst_topic, worst_fmt = _worst(stats, "by_topic"), _worst(stats, "by_format")
    return {
        "summary": f"{stats['overview']['posts_analysed']} posts analysed, average engagement rate "
                   f"{stats['overview']['avg_engagement_rate']:.1%}. The biggest levers are content topic and format.",
        "key_insights": [{"insight": i["insight"], "evidence": f"{i['dimension']} ({i['metric']})"} for i in insights[:6]],
        "recommendations": recs,
        "stop_doing": [
            f"Cut back on {worst_topic['segment']} posts ({worst_topic['lift']:.2f}x avg engagement).",
            f"Use fewer {worst_fmt['segment'].lower()} posts ({worst_fmt['lift']:.2f}x avg engagement).",
        ],
    }
