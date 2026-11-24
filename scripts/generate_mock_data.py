"""Generates a realistic sample dataset for a fictional specialty coffee brand.

Patterns are baked in on purpose (Reels reach more people, tutorials get saved,
evenings beat mornings, promos underperform) so the analytics have something
real to find. Deterministic: same seed -> same file.

    python scripts/generate_mock_data.py
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

TOPICS = {
    "tutorial": (1.45, [
        "How to brew the perfect V60 in 4 steps", "3 tips for better espresso at home",
        "Step-by-step: cold brew that isn't bitter", "How to dial in your grinder - save this guide",
        "Latte art tutorial for beginners", "Learn the 4:6 pour-over method",
    ]),
    "behind_the_scenes": (1.25, [
        "Behind the scenes at the roastery this morning", "Meet the team roasting your next bag",
        "A day at origin with our farmers in Huila", "Inside our cupping session",
    ]),
    "product": (0.95, [
        "New single origin just landed: Ethiopia Guji", "Our house blend, now in 1kg bags",
        "Introducing the Sunrise decaf", "Fresh roast drop: Kenya AA",
    ]),
    "promo": (0.65, [
        "20% off everything this weekend only", "Flash sale - free shipping today",
        "Discount code inside, ends Sunday", "Black Friday deals are live",
    ]),
    "community": (1.15, [
        "Your setups this week are unreal", "Reposting the best home bar we've seen",
        "Customer spotlight: Ama's morning ritual", "You voted, we listened",
    ]),
}
FORMAT_MULT = {"REEL": (1.7, 1.0), "CAROUSEL": (1.0, 1.25), "IMAGE": (0.75, 0.85)}  # (reach, engagement)
WEEKDAY_MULT = [0.95, 1.15, 1.0, 1.15, 0.95, 0.85, 0.9]
QUESTIONS = ["What's your go-to brew?", "Which one would you pick?", "How do you take yours?"]
EMOJIS = ["☕", "🔥", "✨", "☕️🙌"]
CTAS = ["Save this for later.", "Tag a friend who needs this.", "Comment your favourite brew below.", "Link in bio."]
HASHTAGS = ["coffee", "specialtycoffee", "pourover", "espresso", "homebarista", "coffeetime",
            "v60", "latteart", "coffeelover", "roastery", "baristalife", "coffeeroaster",
            "cafe", "brewguide", "morningcoffee", "coffeegram", "coffeeaddict", "beans"]


def hour_mult(h: int) -> float:
    if 18 <= h <= 21:
        return 1.3
    if 11 <= h <= 14:
        return 1.05
    if h < 9:
        return 0.8
    return 0.95


def main() -> None:
    start = datetime(2026, 5, 1)
    posts = []
    for i in range(96):
        ts = start + timedelta(days=i * 2 + random.randint(0, 1), hours=random.choice([7, 8, 9, 12, 13, 15, 17, 18, 19, 20, 21]), minutes=random.randint(0, 59))
        topic = random.choices(list(TOPICS), weights=[3, 2, 3, 2, 2])[0]
        topic_mult, captions = TOPICS[topic]
        fmt = random.choices(list(FORMAT_MULT), weights=[4, 3, 3])[0]
        reach_m, eng_m = FORMAT_MULT[fmt]

        has_cta = random.random() < 0.5
        n_tags = random.choice([0, 2, 3, 4, 5, 5, 8, 12, 20, 25])
        tag_mult = 1.1 if 3 <= n_tags <= 6 else (0.85 if n_tags > 15 else 1.0)
        long_caption = random.random() < 0.45

        caption = random.choice(captions)
        if long_caption:
            caption += ". " + "We get asked about this a lot, so here's everything we've learned over years of roasting and brewing."
        else:
            caption += "."
        if has_cta:
            caption += " " + random.choice(CTAS)
        asks_question = random.random() < 0.3
        if asks_question:
            caption += " " + random.choice(QUESTIONS)
        if random.random() < 0.4:
            caption += " " + random.choice(EMOJIS)
        if n_tags:
            caption += "\n\n" + " ".join("#" + t for t in random.sample(HASHTAGS, min(n_tags, len(HASHTAGS))))

        growth = 1 + i / 160  # account slowly growing
        noise = random.lognormvariate(0, 0.22)
        reach = int(3200 * reach_m * WEEKDAY_MULT[ts.weekday()] * hour_mult(ts.hour) * tag_mult * growth * noise)
        er = 0.045 * eng_m * topic_mult * (1.1 if has_cta else 1.0) * (1.08 if asks_question else 1.0) * (1.05 if long_caption else 1.0) * random.lognormvariate(0, 0.15)
        interactions = int(reach * er)
        save_share = 0.32 if topic == "tutorial" else 0.12
        saves = int(interactions * save_share * (1.4 if fmt == "CAROUSEL" else 1))
        shares = int(interactions * (0.12 if fmt == "REEL" else 0.06))
        comments = int(interactions * (0.09 if has_cta else 0.04) * (1.6 if asks_question else 1.0))
        likes = max(interactions - saves - shares - comments, 0)

        posts.append({
            "id": f"mock_{i:03d}",
            "media_type": fmt,
            "caption": caption,
            "timestamp": ts.isoformat(),
            "permalink": f"https://www.instagram.com/p/mock_{i:03d}/",
            "likes": likes, "comments": comments, "saves": saves, "shares": shares,
            "reach": reach, "views": int(reach * (2.6 if fmt == "REEL" else 1.4)),
        })

    out = Path(__file__).resolve().parent.parent / "data" / "sample_posts.json"
    out.write_text(json.dumps(posts, indent=2))
    print(f"Wrote {len(posts)} posts to {out}")


if __name__ == "__main__":
    main()
