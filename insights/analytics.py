"""Turns raw posts into the stats the intelligence layer reasons over.

Every segment reports `lift` = segment avg engagement rate / overall avg, so
insights can be phrased as "X performs 1.4x better than your average".
"""
from __future__ import annotations

from typing import Dict, List

import pandas as pd

from .models import Post

MIN_SAMPLE = 3  # ignore segments with fewer posts - too noisy to recommend from
MIN_POSTS_FOR_RECOMMENDATIONS = 10  # account-level minimum for data-driven advice

# Lightweight keyword topic tagger. Good enough for a first pass; the LLM layer
# can refine themes, and it's easy to swap for an LLM classifier later.
TOPIC_KEYWORDS = {
    "tutorial": ["how to", "tips", "step-by-step", "guide", "tutorial", "learn the", "method"],
    "behind_the_scenes": ["behind the scenes", "meet the team", "a day at", "inside our"],
    "promo": ["% off", "sale", "discount", "deals", "free shipping", "ends sunday"],
    "product": ["new ", "introducing", "just landed", "drop", "now in"],
    "community": ["your setups", "reposting", "spotlight", "you voted", "customer"],
}
CTA_KEYWORDS = ["save this", "tag a friend", "comment", "link in bio", "share this", "dm us"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def classify_topic(caption: str) -> str:
    text = (caption or "").lower()
    for topic, words in TOPIC_KEYWORDS.items():
        if any(w in text for w in words):
            return topic
    return "other"


def time_window(hour: int) -> str:
    if 5 <= hour < 11:
        return "morning (5-11)"
    if 11 <= hour < 15:
        return "midday (11-15)"
    if 15 <= hour < 18:
        return "afternoon (15-18)"
    if 18 <= hour < 22:
        return "evening (18-22)"
    return "night (22-5)"


def to_frame(posts: List[Post]) -> pd.DataFrame:
    rows = []
    for p in posts:
        body = (p.caption or "").split("#")[0]
        rows.append({
            "id": p.id, "media_type": p.media_type, "caption": p.caption, "timestamp": p.timestamp,
            "permalink": p.permalink, "likes": p.likes, "comments": p.comments, "saves": p.saves,
            "shares": p.shares, "reach": p.reach, "views": p.views, "interactions": p.interactions,
            "engagement_rate": p.engagement_rate, "hashtag_count": len(p.hashtags),
            "caption_words": len(body.split()), "topic": classify_topic(body),
            "has_cta": any(k in (p.caption or "").lower() for k in CTA_KEYWORDS),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Posts without usable reach stay in (they still count for volume, reach and
    # timing) but have no engagement rate; pandas means skip the NaNs.
    df["engagement_rate"] = pd.to_numeric(df["engagement_rate"], errors="coerce")
    ts = pd.to_datetime(df["timestamp"])
    df["weekday"] = ts.dt.dayofweek.map(lambda d: WEEKDAYS[d])
    df["hour"] = ts.dt.hour
    df["time_window"] = df["hour"].map(time_window)
    df["month"] = ts.dt.to_period("M").astype(str)
    df["caption_length"] = pd.cut(df["caption_words"], [-1, 15, 40, 10_000], labels=["short (<=15 words)", "medium (16-40)", "long (40+)"]).astype(str)
    df["hashtag_bucket"] = pd.cut(df["hashtag_count"], [-1, 0, 2, 6, 15, 100], labels=["none", "1-2", "3-6", "7-15", "16+"]).astype(str)
    return df


def segment(df: pd.DataFrame, col: str) -> List[Dict]:
    overall = df["engagement_rate"].mean()
    g = df.groupby(col).agg(
        posts=("id", "count"), posts_with_er=("engagement_rate", "count"),
        avg_engagement_rate=("engagement_rate", "mean"),
        avg_reach=("reach", "mean"), avg_saves=("saves", "mean"),
        avg_shares=("shares", "mean"), avg_comments=("comments", "mean"),
    ).reset_index()
    g["lift"] = g["avg_engagement_rate"] / overall
    avg_reach = df["reach"].mean()
    g["reach_lift"] = g["avg_reach"] / avg_reach if avg_reach else float("nan")
    g["reliable"] = g["posts_with_er"] >= MIN_SAMPLE
    g = g.sort_values("avg_engagement_rate", ascending=False, na_position="last")
    return [_round(r) for r in g.rename(columns={col: "segment"}).to_dict("records")]


def _round(d: Dict) -> Dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, float) and pd.isna(v):
            out[k] = None  # keeps the JSON valid (no NaN)
        elif isinstance(v, float):
            out[k] = round(v, 4 if "rate" in k else 2)
        elif hasattr(v, "item"):
            out[k] = v.item()
        else:
            out[k] = v
    return out


def _post_summary(r: pd.Series) -> Dict:
    return {
        "id": r["id"], "media_type": r["media_type"], "topic": r["topic"],
        "posted": f"{r['weekday']} {int(r['hour']):02d}:00",
        "engagement_rate": None if pd.isna(r["engagement_rate"]) else round(float(r["engagement_rate"]), 4),
        "reach": int(r["reach"]), "likes": int(r["likes"]),
        "saves": int(r["saves"]), "shares": int(r["shares"]), "comments": int(r["comments"]),
        "caption": (r["caption"] or "").split("\n")[0][:160], "permalink": r["permalink"],
    }


def analyse(posts: List[Post]) -> Dict:
    df = to_frame(posts)
    if df.empty:
        raise ValueError("No posts to analyse")

    span_days = max((df["timestamp"].max() - df["timestamp"].min()).days, 1)
    ranked = df.sort_values(["engagement_rate", "interactions"], ascending=False, na_position="last")
    n = min(max(len(df) // 10, 3), len(df))
    with_er = int(df["engagement_rate"].count())

    by_month = df.groupby("month").agg(posts=("id", "count"), avg_engagement_rate=("engagement_rate", "mean"), avg_reach=("reach", "mean")).reset_index()

    return {
        "overview": _round({
            "posts_analysed": int(len(df)),
            "posts_with_engagement_data": with_er,
            # Below this, patterns are noise - recommendations switch to a testing plan.
            "enough_data": with_er >= MIN_POSTS_FOR_RECOMMENDATIONS,
            "date_range": f"{df['timestamp'].min():%Y-%m-%d} to {df['timestamp'].max():%Y-%m-%d}",
            "posts_per_week": len(df) / span_days * 7 if span_days >= 14 else None,  # meaningless over a few days
            "avg_engagement_rate": df["engagement_rate"].mean(),
            "median_engagement_rate": df["engagement_rate"].median(),
            "avg_reach": df["reach"].mean(),
            "total_interactions": int(df["interactions"].sum()),
            "total_reach": int(df["reach"].sum()),
        }),
        "by_format": segment(df, "media_type"),
        "by_topic": segment(df, "topic"),
        "by_weekday": segment(df, "weekday"),
        "by_time_window": segment(df, "time_window"),
        "by_caption_length": segment(df, "caption_length"),
        "by_hashtag_count": segment(df, "hashtag_bucket"),
        "by_cta": segment(df.assign(cta=df["has_cta"].map({True: "with CTA", False: "no CTA"})), "cta"),
        "monthly_trend": [_round(r) for r in by_month.to_dict("records")],
        "top_posts": [_post_summary(r) for _, r in ranked.head(n).iterrows()],
        "bottom_posts": [_post_summary(r) for _, r in ranked.tail(n).iloc[::-1].iterrows()],
    }


def rule_based_insights(stats: Dict) -> List[Dict]:
    """Deterministic, evidence-backed insights. Used on their own when no LLM is
    configured, and handed to the LLM as grounding when one is."""
    insights = []
    if not stats["overview"]["enough_data"]:
        return insights
    labels = {
        "by_format": "format", "by_topic": "content topic", "by_weekday": "posting day",
        "by_time_window": "posting time", "by_caption_length": "caption length",
        "by_hashtag_count": "hashtag count", "by_cta": "call to action",
    }
    # Two lenses: engagement rate (how much people who see it interact) and
    # reach (how many people see it). Timing and hashtags mostly move reach.
    for metric, lift_key, word in [("engagement", "lift", "engagement rate"), ("reach", "reach_lift", "reach")]:
        for key, label in labels.items():
            segs = sorted((s for s in stats[key] if s["reliable"] and s[lift_key] is not None),
                          key=lambda s: s[lift_key], reverse=True)
            if len(segs) < 2:
                continue
            best, worst = segs[0], segs[-1]
            gap = best[lift_key] - worst[lift_key]
            if gap < 0.15:  # differences this small are noise, not insight
                continue
            insights.append({
                "metric": metric,
                "dimension": label,
                "best": best["segment"],
                "worst": worst["segment"],
                "insight": f"Best {label} for {word}: {best['segment']} ({best[lift_key]:.2f}x your average, "
                           f"{best['posts']} posts). Weakest: {worst['segment']} ({worst[lift_key]:.2f}x).",
                "lift_gap": round(gap, 2),
            })
    return sorted(insights, key=lambda i: i["lift_gap"], reverse=True)
