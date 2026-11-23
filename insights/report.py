"""Renders stats + recommendations as a readable Markdown report."""
from __future__ import annotations

from typing import Dict, List


def _table(segs: List[Dict]) -> str:
    lines = ["| Segment | Posts | Avg ER | ER lift | Avg reach | Reach lift |", "|---|---|---|---|---|---|"]
    for s in segs:
        flag = "" if s["reliable"] else " *"
        lines.append(f"| {s['segment']}{flag} | {s['posts']} | {s['avg_engagement_rate']:.2%} | "
                     f"{s['lift']:.2f}x | {s['avg_reach']:,.0f} | {s['reach_lift']:.2f}x |")
    return "\n".join(lines)


def render_markdown(stats: Dict, recs: Dict) -> str:
    o = stats["overview"]
    out = [
        "# Instagram Content Report",
        "",
        f"**Period:** {o['date_range']}  ·  **Posts:** {o['posts_analysed']}  ·  "
        f"**Posting rate:** {o['posts_per_week']:.1f}/week  ·  **Engine:** {recs.get('engine', '-')}",
        "",
        f"**Avg engagement rate:** {o['avg_engagement_rate']:.2%}  ·  **Avg reach:** {o['avg_reach']:,.0f}  ·  "
        f"**Total interactions:** {o['total_interactions']:,}",
        "",
        "## Summary",
        recs["summary"],
        "",
        "## Recommended content",
    ]
    for i, r in enumerate(recs["recommendations"], 1):
        out += [
            f"### {i}. {r['title']}  ({r['priority']} priority)",
            f"- **Format:** {r['format']}  ·  **Topic:** {r['topic']}  ·  **When:** {r['best_day']}, {r['best_time']}",
            f"- **Why:** {r['why']}",
            f"- **Evidence:** {r['evidence']}",
        ]
        if r.get("caption_draft"):
            out.append(f"- **Caption draft:** {r['caption_draft']}")
        if r.get("hashtags"):
            out.append(f"- **Hashtags:** {' '.join('#' + h.lstrip('#') for h in r['hashtags'])}")
        out.append("")
    if recs.get("stop_doing"):
        out += ["## Stop doing"] + [f"- {s}" for s in recs["stop_doing"]] + [""]
    out += ["## Key insights"] + [f"- {k['insight']} _({k['evidence']})_" for k in recs["key_insights"]] + [""]

    out += ["## Breakdown", "_ER = engagement rate (interactions / reach). Lift = vs account average. * = fewer than 3 posts._", ""]
    for key, title in [("by_format", "Format"), ("by_topic", "Topic"), ("by_weekday", "Day"),
                       ("by_time_window", "Time of day"), ("by_hashtag_count", "Hashtags"),
                       ("by_caption_length", "Caption length"), ("by_cta", "Call to action")]:
        out += [f"### {title}", _table(stats[key]), ""]

    out += ["## Top posts", "| Post | Format | Topic | Posted | ER | Reach |", "|---|---|---|---|---|---|"]
    for p in stats["top_posts"]:
        out.append(f"| [{p['caption'][:50]}]({p['permalink']}) | {p['media_type']} | {p['topic']} | {p['posted']} | "
                   f"{p['engagement_rate']:.2%} | {p['reach']:,} |")
    return "\n".join(out) + "\n"
