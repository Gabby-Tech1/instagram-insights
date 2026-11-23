"""Data sources. Every source returns a list of normalised `Post` objects,
so the rest of the pipeline does not care where the data came from."""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

import requests

from .models import Post

log = logging.getLogger(__name__)


class DataSource(ABC):
    @abstractmethod
    def fetch_posts(self, limit: int = 100) -> List[Post]: ...


class MockSource(DataSource):
    """Loads posts from a JSON file - lets the whole pipeline run without credentials."""

    DEFAULT = Path(__file__).resolve().parent.parent / "data" / "sample_posts.json"

    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else self.DEFAULT

    def fetch_posts(self, limit: int = 100) -> List[Post]:
        rows = json.loads(self.path.read_text())
        return [Post.from_dict(r) for r in rows[:limit]]


class InstagramSource(DataSource):
    """Instagram Graph API (Business/Creator accounts). Supports both token types Meta issues:

    - Instagram Login tokens (start with "IG")  -> graph.instagram.com, /me/media
    - Facebook / system-user tokens ("EAA...")  -> graph.facebook.com, /{IG_USER_ID}/media

    Docs: https://developers.facebook.com/docs/instagram-platform
    Meta renames/deprecates insight metrics from time to time, so each metric is
    requested separately and a missing one is treated as 0 instead of failing.
    """

    MEDIA_FIELDS = "id,caption,media_type,media_product_type,timestamp,permalink,like_count,comments_count"
    INSIGHT_METRICS = ["reach", "saved", "shares", "views"]
    TYPE_MAP = {"CAROUSEL_ALBUM": "CAROUSEL", "IMAGE": "IMAGE", "VIDEO": "REEL"}

    def __init__(self, access_token: str | None = None, api_version: str | None = None, user_id: str | None = None):
        self.token = (access_token or os.environ.get("IG_ACCESS_TOKEN") or "").strip()
        if not self.token:
            raise ValueError("IG_ACCESS_TOKEN is not set - add it to .env or use --source mock")
        self.version = api_version or os.environ.get("IG_API_VERSION", "v23.0")
        self.session = requests.Session()
        if self.token.startswith("IG"):
            self.base, self.user = "https://graph.instagram.com", "me"
        else:
            self.base = "https://graph.facebook.com"
            self.user = user_id or os.environ.get("IG_USER_ID")
            if not self.user:
                raise ValueError("This is a Facebook-style token: set IG_USER_ID in .env "
                                 "(the Instagram account ID shown in the Meta app dashboard)")

    def _get(self, path: str, **params) -> dict:
        url = path if path.startswith("http") else f"{self.base}/{self.version}/{path}"
        params.setdefault("access_token", self.token)
        resp = self.session.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Instagram API {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    def _insights(self, media_id: str) -> dict:
        values: dict = {}
        # Ask for each metric separately so one unsupported metric doesn't fail the rest.
        for metric in self.INSIGHT_METRICS:
            try:
                data = self._get(f"{media_id}/insights", metric=metric).get("data", [])
                if data:
                    values[metric] = data[0]["values"][0]["value"]
            except RuntimeError as e:
                log.debug("metric %s unavailable for %s: %s", metric, media_id, e)
        return values

    def fetch_posts(self, limit: int = 100) -> List[Post]:
        posts: List[Post] = []
        page = self._get(f"{self.user}/media", fields=self.MEDIA_FIELDS, limit=min(limit, 50))
        while True:
            for m in page.get("data", []):
                media_type = "REEL" if m.get("media_product_type") == "REELS" else self.TYPE_MAP.get(m.get("media_type"), m.get("media_type"))
                ins = self._insights(m["id"])
                posts.append(Post.from_dict({
                    "id": m["id"],
                    "media_type": media_type,
                    "caption": m.get("caption", ""),
                    "timestamp": m["timestamp"],
                    "permalink": m.get("permalink", ""),
                    "likes": m.get("like_count", 0),
                    "comments": m.get("comments_count", 0),
                    "saves": ins.get("saved", 0),
                    "shares": ins.get("shares", 0),
                    "reach": ins.get("reach", 0),
                    "views": ins.get("views", 0),
                }))
                if len(posts) >= limit:
                    return posts
            next_url = page.get("paging", {}).get("next")
            if not next_url:
                return posts
            page = self._get(next_url)


def get_source(name: str, **kwargs) -> DataSource:
    if name == "mock":
        return MockSource(**kwargs)
    if name == "instagram":
        return InstagramSource(**kwargs)
    raise ValueError(f"Unknown source: {name}")
