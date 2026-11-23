"""Minimal HTTP API over the same pipeline.

    uvicorn api:app --reload
    open http://127.0.0.1:8000/docs
"""
import warnings

warnings.filterwarnings("ignore", message=".*OpenSSL.*")

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from insights.analytics import analyse
from insights.intelligence import recommend
from insights.sources import get_source
from insights.store import Store

load_dotenv()
app = FastAPI(title="Instagram Insights", version="0.1.0")
DB = "insights.db"


@app.post("/sync")
def sync(source: str = "mock", limit: int = 100):
    """Pull posts from the source and store them."""
    try:
        posts = get_source(source).fetch_posts(limit=limit)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    return {"stored": Store(DB).upsert(posts), "source": source}


def _stats():
    posts = Store(DB).all_posts()
    if not posts:
        raise HTTPException(404, "No posts stored yet - call POST /sync first")
    return analyse(posts)


@app.get("/stats")
def stats():
    """Performance breakdown by format, topic, day, time, hashtags, caption length and CTA."""
    return _stats()


@app.get("/recommendations")
def recommendations(context: str = "", use_llm: bool = True):
    """Evidence-backed content recommendations."""
    return recommend(_stats(), account_context=context, use_llm=use_llm)
