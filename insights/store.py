"""SQLite storage. Upserts so re-running a fetch refreshes metrics instead of duplicating posts."""
from __future__ import annotations

import sqlite3
from typing import Dict, List

from .models import Post

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id TEXT PRIMARY KEY, media_type TEXT, caption TEXT, timestamp TEXT, permalink TEXT,
    likes INTEGER, comments INTEGER, saves INTEGER, shares INTEGER, reach INTEGER, views INTEGER,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS post_tags (
    post_id TEXT, tagger TEXT, caption_hash TEXT, topic TEXT, style TEXT,
    PRIMARY KEY (post_id, tagger)
);
"""
COLS = ["id", "media_type", "caption", "timestamp", "permalink", "likes", "comments", "saves", "shares", "reach", "views"]


class Store:
    def __init__(self, path: str = "insights.db"):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

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

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]

    # --- caption tag cache (avoids re-paying for LLM tagging) ---
    def get_tags(self, tagger: str) -> Dict[str, Dict[str, str]]:
        cur = self.conn.execute("SELECT post_id, caption_hash, topic, style FROM post_tags WHERE tagger=?", (tagger,))
        return {pid: {"hash": h, "topic": t, "style": s} for pid, h, t, s in cur.fetchall()}

    def save_tags(self, tagger: str, tags: Dict[str, Dict[str, str]]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO post_tags (post_id, tagger, caption_hash, topic, style) VALUES (?,?,?,?,?)",
            [(pid, tagger, t["hash"], t["topic"], t["style"]) for pid, t in tags.items()],
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
