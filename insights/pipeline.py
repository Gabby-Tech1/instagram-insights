"""The workflow in one place, shared by the CLI and the API:

    collect (source -> store)  ->  tag captions  ->  analyse  ->  recommend (+ grounding check)
"""
from __future__ import annotations

from typing import Dict

from .analytics import analyse
from .intelligence import recommend
from .sources import get_source
from .store import Store
from .tagging import tag_posts


def collect(store: Store, source: str, limit: int = 100, **source_kwargs) -> int:
    posts = get_source(source, **source_kwargs).fetch_posts(limit=limit)
    return store.upsert(posts)


def analyse_store(store: Store, use_llm: bool = True) -> Dict:
    posts = store.all_posts()
    if not posts:
        raise LookupError("No posts stored yet - sync/fetch first")
    tags, tagger = tag_posts(posts, store=store, use_llm=use_llm)
    stats = analyse(posts, tags=tags)
    stats["overview"]["tagger"] = tagger
    return stats


def run(store: Store, context: str = "", use_llm: bool = True) -> Dict:
    stats = analyse_store(store, use_llm=use_llm)
    return {"stats": stats, "recommendations": recommend(stats, account_context=context, use_llm=use_llm)}
