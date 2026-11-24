"""Renders stats + recommendations as a readable Markdown report."""
from __future__ import annotations

from typing import Dict, List

BREAKDOWNS = [
    ("by_format", "Format"), ("by_topic", "Topic"), ("by_style", "Content style"), ("by_weekday", "Day"),
    ("by_time_window", "Time of day"), ("by_hashtag_count", "Hashtags"), ("by_caption_length", "Caption length"),
    ("by_cta", "Call to action"), ("by_question", "Questions"), ("by_emoji", "Emoji"),
]


def _f(v, spec: str, suffix: str = "") -> str:
    return "-" if v is None else f"{v:{spec}}{suffix}"


def _table(segs: List[Dict]) -> str:
    lines = ["| Group | Posts | Avg ER | ER lift | Avg reach | Reach lift |", "|---|---|---|---|---|---|"]
    for s in segs:
        flag = "" if s["reliable"] else " *"
        lines.append(f"| {str(s['segment']).replace('_', ' ')}{flag} | {s['posts']} | {_f(s['avg_engagement_rate'], '.2%')} | "
                     f"{_f(s['lift'], '.2f', 'x')} | {_f(s['avg_reach'], ',.0f')} | {_f(s['reach_lift'], '.2f', 'x')} |")
    return "\n".join(lines)


def _posts(posts: List[Dict]) -> List[str]:
    out = ["| Post | Format | Topic | Style | Posted | ER | Reach | Saves |", "|---|---|---|---|---|---|---|---|"]
    for p in posts:
        out.append(f"| [{p['caption'][:50] or '(no caption)'}]({p['permalink']}) | {p['media_type']} | {p['topic']} | "
                   f"{p['style']} | {p['posted']} | {_f(p['engagement_rate'], '.2%')} | {p['reach']:,} | {p['saves']:,} |")
    return out


def render_markdown(stats: Dict, recs: Dict) -> str:
    o, t, g = stats["overview"], stats.get("trend", {}), recs.get("grounding_summary", {})
    out = [
        "# Instagram Content Report",
        "",
        f"**Period:** {o['date_range']} ({o.get('timezone', 'UTC')})  ·  **Posts:** {o['posts_analysed']}  ·  "
        f"**Posting rate:** {_f(o['posts_per_week'], '.1f', '/week')}",
        "",
        f"**Avg engagement rate:** {_f(o['avg_engagement_rate'], '.2%')}  ·  **Avg reach:** {_f(o['avg_reach'], ',.0f')}  ·  "
        f"**Save rate:** {_f(o.get('save_rate'), '.2%')}  ·  **Share rate:** {_f(o.get('share_rate'), '.2%')}  ·  "
        f"**Total interactions:** {o['total_interactions']:,}",
        "",
        f"_Caption tagging: {o.get('tagger', 'keywords')} · Recommendations: {recs.get('engine', '-')} "
        f"({recs.get('mode', '')}) · Verified against data: {g.get('verified', 0)}/{g.get('total', 0)}_",
        "",
        "## Summary",
        recs["summary"],
        "",
        "## Recommended content",
    ]
    for i, r in enumerate(recs["recommendations"], 1):
        gr = r.get("grounding", {})
        mark = "✅ numbers verified" if gr.get("grounded") else (
            f"⚠️ not verified: {', '.join(gr.get('unmatched_numbers', []) + gr.get('unknown_posts', [])) or 'no data cited'}")
        out += [
            f"### {i}. {r['title']}  ({r['priority']} priority, grows {r.get('goal', 'engagement')})",
            f"- **Format:** {r['format']}  ·  **Topic:** {r['topic']}  ·  **Style:** {r.get('style', '-')}  ·  "
            f"**When:** {r['best_day']}, {r['best_time']}",
            f"- **Why:** {r['why']}",
            f"- **Evidence:** {r['evidence']}  ({mark})",
        ]
        if r.get("based_on_posts"):
            out.append(f"- **Based on posts:** {', '.join(r['based_on_posts'])}")
        if r.get("caption_draft"):
            out.append(f"- **Caption draft:** {r['caption_draft']}")
        if r.get("hashtags"):
            out.append(f"- **Hashtags:** {' '.join('#' + h.lstrip('#') for h in r['hashtags'])}")
        out.append("")
    if recs.get("underperforming"):
        out += ["## Underperforming areas"]
        out += [f"- **{u['area']}**: {u['evidence']} → {u['suggestion']}" for u in recs["underperforming"]] + [""]
    out += ["## Key insights"] + [f"- {k['insight']} _({k['evidence']})_" for k in recs["key_insights"]] + [""]

    out += ["## Engagement over time"]
    if t.get("direction") not in (None, "not enough data"):
        out.append(f"Engagement is **{t['direction']}**: {_f(t['recent_engagement_rate'], '.2%')} in {t['recent_period']} vs "
                   f"{_f(t['early_engagement_rate'], '.2%')} in {t['early_period']} ({_f(t['engagement_change'], '+.0%')}); "
                   f"reach {_f(t['reach_change'], '+.0%')}.")
    out += ["", "| Month | Posts | Avg ER | Avg reach | Interactions |", "|---|---|---|---|---|"]
    out += [f"| {m['month']} | {m['posts']} | {_f(m['avg_engagement_rate'], '.2%')} | {_f(m['avg_reach'], ',.0f')} | "
            f"{m['interactions']:,} |" for m in stats["monthly_trend"]] + [""]

    out += ["## Best posts"] + _posts(stats["top_posts"]) + [""]
    out += ["## Worst posts"] + (_posts(stats["bottom_posts"]) if stats["bottom_posts"] else ["_No measurable posts._"]) + [""]

    out += ["## Breakdown", "_ER = engagement rate (interactions / reach). Lift = vs account average. "
            "* = fewer than 3 measurable posts, not used for recommendations._", ""]
    for key, title in BREAKDOWNS:
        out += [f"### {title}", _table(stats[key]), ""]
    return "\n".join(out) + "\n"
