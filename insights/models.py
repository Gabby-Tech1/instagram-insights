"""Normalised data model shared by every data source."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

HASHTAG_RE = re.compile(r"#(\w+)")
MIN_REACH = 10


@dataclass
class Post:
    id: str
    media_type: str  # REEL | CAROUSEL | IMAGE
    caption: str
    timestamp: datetime
    permalink: str = ""
    likes: int = 0
    comments: int = 0
    saves: int = 0
    shares: int = 0
    reach: int = 0
    views: int = 0
    hashtags: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.hashtags:
            self.hashtags = HASHTAG_RE.findall(self.caption or "")

    @property
    def interactions(self) -> int:
        return self.likes + self.comments + self.saves + self.shares

    @property
    def engagement_rate(self) -> Optional[float]:
        """Interactions per account reached (reach-based ER).

        None when reach is too small to divide by: Meta often reports reach of
        0-1 for older posts, which would produce rates like 1500%."""
        return self.interactions / self.reach if self.reach >= MIN_REACH else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Post":
        d = dict(d)
        ts = d["timestamp"]
        if not isinstance(ts, datetime):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00").replace("+0000", "+00:00"))
        if ts.tzinfo is not None:  # store everything as naive UTC so sources can be mixed
            ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
        d["timestamp"] = ts
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
