"""Turns raw posts into the stats the intelligence layer reasons over.

Metric choices (full reasoning in TECHNICAL.md):
- Engagement rate (ER) = (likes + comments + saves + shares) / reach. Reach, not
  followers, because it measures the people who actually saw the post.
- Reach is tracked separately: ER says whether viewers cared, reach says how many
  people saw it. Timing and hashtags mostly move reach; topic and format move both.
- Every group reports `lift` = group average / account average, so insights read
  as "tutorials get 1.33x your average engagement".
- Groups with fewer than MIN_SAMPLE posts are flagged unreliable and never used
  for recommendations; accounts with fewer than MIN_POSTS_FOR_RECOMMENDATIONS
  measurable posts get a testing plan instead of patterns.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

import pandas as pd

from .models import Post
from .tagging import caption_body, classify_topic, tags_for  # noqa: F401  (classify_topic re-exported)

MIN_SAMPLE = 3
MIN_POSTS_FOR_RECOMMENDATIONS = 10

CTA_KEYWORDS = ["save this", "tag a friend", "comment", "link in bio", "share this", "dm us", "follow for"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")

DIMENSIONS = {
    "by_format": ("media_type", "format"),
    "by_topic": ("topic", "content topic"),
    "by_style": ("style", "content style"),
    "by_weekday": ("weekday", "posting day"),
    "by_time_window": ("time_window", "posting time"),
    "by_caption_length": ("caption_length", "caption length"),
    "by_hashtag_count": ("hashtag_bucket", "hashtag count"),
    "by_cta": ("cta", "call to action"),
    "by_question": ("question", "asking a question"),
    "by_emoji": ("emoji", "emoji use"),
}


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


def to_frame(posts: List[Post], tags: Optional[Dict] = None, timezone: Optional[str] = None) -> pd.DataFrame:
    rows = []
    for p in posts:
        body = caption_body(p.caption)
        t = tags_for(p.id, tags, p)
        rows.append({
            "id": p.id, "media_type": p.media_type, "caption": p.caption or "", "timestamp": p.timestamp,
            "permalink": p.permalink, "likes": p.likes, "comments": p.comments, "saves": p.saves,
            "shares": p.shares, "reach": p.reach, "views": p.views, "interactions": p.interactions,
            "engagement_rate": p.engagement_rate, "hashtags": p.hashtags, "hashtag_count": len(p.hashtags),
            "caption_words": len(body.split()), "topic": t["topic"], "style": t["style"],
            "cta": "with CTA" if any(k in body.lower() for k in CTA_KEYWORDS) else "no CTA",
            "question": "asks a question" if "?" in body else "no question",
            "emoji": "uses emoji" if EMOJI_RE.search(body) else "no emoji",
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # Posts without usable reach stay in (they count for volume, reach and timing)
    # but have no engagement rate; pandas means skip the NaNs.
    df["engagement_rate"] = pd.to_numeric(df["engagement_rate"], errors="coerce")
    ts = pd.to_datetime(df["timestamp"])
    if timezone:  # stored as UTC; posting-time analysis should use the account's local time
        ts = ts.dt.tz_localize("UTC").dt.tz_convert(timezone).dt.tz_localize(None)
    df["local_time"] = ts
    df["weekday"] = ts.dt.dayofweek.map(lambda d: WEEKDAYS[d])
    df["hour"] = ts.dt.hour
    df["time_window"] = df["hour"].map(time_window)
    df["month"] = ts.dt.strftime("%Y-%m")
    df["caption_length"] = pd.cut(df["caption_words"], [-1, 15, 40, 10_000],
                                  labels=["short (<=15 words)", "medium (16-40)", "long (40+)"]).astype(str)
    df["hashtag_bucket"] = pd.cut(df["hashtag_count"], [-1, 0, 2, 6, 15, 100],
                                  labels=["none", "1-2", "3-6", "7-15", "16+"]).astype(str)
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
            out[k] = round(float(v), 4 if ("rate" in k or "change" in k) else 2)
        elif hasattr(v, "item"):
            out[k] = v.item()
        else:
            out[k] = v
    return out


def _post_summary(r: pd.Series) -> Dict:
    return {
        "id": r["id"], "media_type": r["media_type"], "topic": r["topic"], "style": r["style"],
        "posted": f"{r['local_time']:%Y-%m-%d} {r['weekday']} {int(r['hour']):02d}:00",
        "engagement_rate": None if pd.isna(r["engagement_rate"]) else round(float(r["engagement_rate"]), 4),
        "reach": int(r["reach"]), "likes": int(r["likes"]), "comments": int(r["comments"]),
        "saves": int(r["saves"]), "shares": int(r["shares"]), "views": int(r["views"]),
        "hashtags": list(r["hashtags"])[:10],
        "caption": caption_body(r["caption"]).split("\n")[0][:160], "permalink": r["permalink"],
    }


def _trend(df: pd.DataFrame) -> Dict:
    """Compares the earlier half of measurable posts with the more recent half."""
    measured = df.dropna(subset=["engagement_rate"]).sort_values("local_time")
    if len(measured) < 2 * MIN_SAMPLE:
        return {"direction": "not enough data"}
    half = len(measured) // 2
    early, recent = measured.iloc[:half], measured.iloc[half:]
    e, r = early["engagement_rate"].mean(), recent["engagement_rate"].mean()
    er, rr = early["reach"].mean(), recent["reach"].mean()
    change = r / e - 1 if e else 0.0
    return _round({
        "early_period": f"{early['local_time'].min():%Y-%m-%d} to {early['local_time'].max():%Y-%m-%d}",
        "recent_period": f"{recent['local_time'].min():%Y-%m-%d} to {recent['local_time'].max():%Y-%m-%d}",
        "early_engagement_rate": e, "recent_engagement_rate": r, "engagement_change": change,
        "early_avg_reach": er, "recent_avg_reach": rr, "reach_change": rr / er - 1 if er else 0.0,
        "direction": "up" if change > 0.05 else "down" if change < -0.05 else "flat",
    })


def analyse(posts: List[Post], tags: Optional[Dict] = None, timezone: Optional[str] = None) -> Dict:
    timezone = timezone if timezone is not None else (os.environ.get("ACCOUNT_TIMEZONE") or None)
    df = to_frame(posts, tags, timezone)
    if df.empty:
        raise ValueError("No posts to analyse")

    span_days = max((df["timestamp"].max() - df["timestamp"].min()).days, 1)
    ranked = df.sort_values(["engagement_rate", "interactions"], ascending=False, na_position="last")
    measured = ranked.dropna(subset=["engagement_rate"])
    n = min(max(len(df) // 10, 3), len(df))
    with_er = int(df["engagement_rate"].count())
    reach_total = df["reach"].sum()
    # Save/share rates only over measurable posts - same rule as ER (reach 1 gave a 200% save rate)
    m = df.dropna(subset=["engagement_rate"])
    m_reach = m["reach"].sum()

    by_month = df.groupby("month").agg(
        posts=("id", "count"), avg_engagement_rate=("engagement_rate", "mean"),
        avg_reach=("reach", "mean"), interactions=("interactions", "sum"),
    ).reset_index()

    stats = {
        "overview": _round({
            "posts_analysed": int(len(df)),
            "posts_with_engagement_data": with_er,
            "enough_data": with_er >= MIN_POSTS_FOR_RECOMMENDATIONS,
            "date_range": f"{df['local_time'].min():%Y-%m-%d} to {df['local_time'].max():%Y-%m-%d}",
            "timezone": timezone or "UTC",
            "posts_per_week": len(df) / span_days * 7 if span_days >= 14 else None,
            "avg_engagement_rate": df["engagement_rate"].mean(),
            "median_engagement_rate": df["engagement_rate"].median(),
            "avg_reach": df["reach"].mean(),
            "save_rate": m["saves"].sum() / m_reach if m_reach else None,
            "share_rate": m["shares"].sum() / m_reach if m_reach else None,
            "total_interactions": int(df["interactions"].sum()),
            "total_reach": int(reach_total),
        }),
        "trend": _trend(df),
        "monthly_trend": [_round(r) for r in by_month.to_dict("records")],
        # Best/worst only among posts we can measure; posts without reach data can't be ranked fairly.
        "top_posts": [_post_summary(r) for _, r in (measured if len(measured) else ranked).head(n).iterrows()],
        "bottom_posts": [_post_summary(r) for _, r in measured.tail(min(n, len(measured))).iloc[::-1].iterrows()],
    }
    for key, (col, _) in DIMENSIONS.items():
        stats[key] = segment(df, col)
    return stats


def rule_based_insights(stats: Dict) -> List[Dict]:
    """Deterministic, evidence-backed insights. Used on their own when no LLM is
    configured, and handed to the LLM as grounding when one is."""
    insights: List[Dict] = []
    if not stats["overview"]["enough_data"]:
        return insights
    t = stats.get("trend", {})
    if t.get("direction") in ("up", "down"):
        insights.append({
            "metric": "trend", "dimension": "over time", "best": t["recent_period"], "worst": t["early_period"],
            "insight": f"Engagement is {t['direction']} {abs(t['engagement_change']):.0%} recently "
                       f"({t['recent_engagement_rate']:.2%} vs {t['early_engagement_rate']:.2%} earlier); "
                       f"reach changed {t['reach_change']:+.0%}.",
            "lift_gap": round(abs(t["engagement_change"]), 2),
        })
    # Two lenses: engagement rate (how much people who see it interact) and
    # reach (how many people see it).
    for metric, lift_key, word in [("engagement", "lift", "engagement rate"), ("reach", "reach_lift", "reach")]:
        for key, (_, label) in DIMENSIONS.items():
            segs = sorted((s for s in stats[key] if s["reliable"] and s[lift_key] is not None),
                          key=lambda s: s[lift_key], reverse=True)
            if len(segs) < 2:
                continue
            best, worst = segs[0], segs[-1]
            gap = best[lift_key] - worst[lift_key]
            if gap < 0.15:  # differences this small are noise, not insight
                continue
            insights.append({
                "metric": metric, "dimension": label, "best": best["segment"], "worst": worst["segment"],
                "insight": f"Best {label} for {word}: {best['segment']} ({best[lift_key]:.2f}x your average, "
                           f"{best['posts']} posts). Weakest: {worst['segment']} ({worst[lift_key]:.2f}x).",
                "lift_gap": round(gap, 2),
            })
    return sorted(insights, key=lambda i: i["lift_gap"], reverse=True)
