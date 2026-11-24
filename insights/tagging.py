"""Tags every caption with a topic (what it's about) and a content style (how it's told).

- With Claude available: one batched call labels all untagged captions, reusing
  labels so similar posts group together. Results are cached in SQLite by caption
  hash, so re-running the analysis costs nothing until captions change.
- Without it (or on failure): keyword rules. They are tuned for common patterns,
  so on niche accounts many posts land in "other" - that's the trade-off.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

from .llm import LLMError, claude_json, llm_available
from .models import Post

log = logging.getLogger(__name__)

STYLES = [
    "how-to / tutorial", "tips / listicle", "behind the scenes", "promotional / offer",
    "announcement / launch", "storytelling / personal", "question / conversation",
    "community / user content", "humour / meme", "showcase / aesthetic", "other",
]

TOPIC_KEYWORDS = {
    "tutorial": ["how to", "tips", "step-by-step", "guide", "tutorial", "learn the", "method"],
    "behind_the_scenes": ["behind the scenes", "meet the team", "a day at", "inside our"],
    "promo": ["% off", "sale", "discount", "deals", "free shipping", "ends sunday"],
    "product": ["new ", "introducing", "just landed", "drop", "now in"],
    "community": ["your setups", "reposting", "spotlight", "you voted", "customer"],
}
STYLE_RULES = [
    ("promotional / offer", re.compile(r"% off|\bsale\b|discount|\bdeals?\b|free shipping|\bcode\b", re.I)),
    ("tips / listicle", re.compile(r"\b\d+\s+(tips|ways|reasons|things|steps|mistakes)\b", re.I)),
    ("how-to / tutorial", re.compile(r"how to|step-by-step|tutorial|\bguide\b|learn the|method", re.I)),
    ("behind the scenes", re.compile(r"behind the scenes|meet the team|a day at|inside our|\bbts\b", re.I)),
    ("community / user content", re.compile(r"your setups|reposting|spotlight|you voted|customer|shout ?out", re.I)),
    ("announcement / launch", re.compile(r"\bnew\b|introducing|just landed|launch|\bdrop\b|now in", re.I)),
    ("humour / meme", re.compile(r"\blol\b|\blmao\b|😂|🤣|meme|when you", re.I)),
    ("storytelling / personal", re.compile(r"\bmy (story|journey)\b|\bi remember\b|years ago|\bi learned\b", re.I)),
]


def caption_body(caption: str) -> str:
    """Caption text without the hashtag block (hashtags like #brewguide caused false matches)."""
    return (caption or "").split("#")[0].strip()


def classify_topic(text: str) -> str:
    text = (text or "").lower()
    for topic, words in TOPIC_KEYWORDS.items():
        if any(w in text for w in words):
            return topic
    return "other"


def classify_style(text: str) -> str:
    for style, rx in STYLE_RULES:
        if rx.search(text or ""):
            return style
    if (text or "").strip().endswith("?"):
        return "question / conversation"
    return "other"


def keyword_tags(post: Post) -> Dict[str, str]:
    body = caption_body(post.caption)
    return {"topic": classify_topic(body), "style": classify_style(body)}


def _hash(caption: str) -> str:
    return hashlib.sha256((caption or "").encode()).hexdigest()[:16]


TAG_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "topic": {"type": "string"},
                    "style": {"type": "string", "enum": STYLES},
                },
                "required": ["id", "topic", "style"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["tags"],
    "additionalProperties": False,
}

TAG_SYSTEM = """You label Instagram captions from one account so their performance can be compared by group.

For each caption return:
- topic: a short lowercase label (1-3 words) for what the post is about, e.g. "brewing guides", "new products".
  Use as FEW distinct topics as possible (aim for 4-8 for the whole account) and reuse the exact same label
  for similar posts, otherwise groups are too small to compare. Reuse labels from `existing_topics` when they fit.
- style: how the post is told, chosen from the allowed list.
Empty captions get topic "no caption" and style "other". Return one entry per id, using the given ids."""


def _llm_tag(posts: List[Post], existing_topics: List[str]) -> Dict[str, Dict[str, str]]:
    items = [{"id": p.id, "caption": caption_body(p.caption)[:400]} for p in posts]
    result = claude_json(
        TAG_SYSTEM,
        json.dumps({"existing_topics": existing_topics, "captions": items}, ensure_ascii=False),
        TAG_SCHEMA,
        effort="low",
    )
    valid = {p.id for p in posts}
    return {t["id"]: {"topic": t["topic"].strip().lower(), "style": t["style"]}
            for t in result["tags"] if t["id"] in valid}


def tag_posts(posts: List[Post], store=None, use_llm: bool = True, batch_size: int = 80) -> Tuple[Dict[str, Dict[str, str]], str]:
    """Returns ({post_id: {"topic", "style"}}, tagger_name)."""
    tags = {p.id: keyword_tags(p) for p in posts}
    if not (use_llm and llm_available()):
        return tags, "keywords"

    cached = store.get_tags("claude") if store else {}
    todo = [p for p in posts if cached.get(p.id, {}).get("hash") != _hash(p.caption)]
    fresh: Dict[str, Dict[str, str]] = {}
    try:
        topics = sorted({c["topic"] for c in cached.values()})
        for i in range(0, len(todo), batch_size):
            got = _llm_tag(todo[i:i + batch_size], topics)
            fresh.update(got)
            topics = sorted(set(topics) | {t["topic"] for t in got.values()})
    except LLMError as e:
        log.warning("LLM tagging failed, using keyword tags: %s", e)
        return tags, "keywords"

    if store and fresh:
        store.save_tags("claude", {pid: {**t, "hash": _hash(next(p.caption for p in todo if p.id == pid))}
                                   for pid, t in fresh.items()})
    llm_tags = {pid: {"topic": c["topic"], "style": c["style"]} for pid, c in cached.items()}
    llm_tags.update(fresh)
    covered = 0
    for p in posts:
        if p.id in llm_tags:
            tags[p.id] = llm_tags[p.id]
            covered += 1
    return tags, "claude" if covered == len(posts) else f"claude ({covered}/{len(posts)}) + keywords"


def tags_for(post_id: str, tags: Optional[Dict[str, Dict[str, str]]], post: Post) -> Dict[str, str]:
    return (tags or {}).get(post_id) or keyword_tags(post)
