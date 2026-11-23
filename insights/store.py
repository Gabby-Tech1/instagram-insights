"""SQLite storage. Upserts so re-running a fetch refreshes metrics instead of duplicating posts."""
from __future__ import annotations

import sqlite3
from typing import List

from .models import Post

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY, media_type TEXT, caption TEXT, timestamp TEXT, permalink TEXT,
    likes INTEGER, comments INTEGER, saves INTEGER, shares INTEGER, reach INTEGER, views INTEGER,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""
COLS = ["id", "media_type", "caption", "timestamp", "permalink", "likes", "comments", "saves", "shares", "reach", "views"]


class Store:
    def __init__(self, path: str = "insights.db"):
        self.conn = sqlite3.connect(path)
        self.conn.execute(SCHEMA)

    def upsert(self, posts: List[Post]) -> int:
        rows = [tuple(p.to_dict()[c] for c in COLS) for p in posts]
        placeholders = ",".join("?" * len(COLS))
        updates = ",".join(f"{c}=excluded.{c}" for c in COLS[1:])
        self.conn.executemany(
            f"INSERT INTO posts ({','.join(COLS)}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}, fetched_at=CURRENT_TIMESTAMP",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def all_posts(self) -> List[Post]:
        cur = self.conn.execute(f"SELECT {','.join(COLS)} FROM posts ORDER BY timestamp")
        return [Post.from_dict(dict(zip(COLS, r))) for r in cur.fetchall()]
