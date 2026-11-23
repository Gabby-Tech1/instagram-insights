"""HTTP API + web dashboard over the same pipeline as the CLI.

    uvicorn api:app --reload
    open http://127.0.0.1:8000        (dashboard)
    open http://127.0.0.1:8000/docs   (API docs)
"""
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=".*OpenSSL.*")

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from insights.analytics import analyse
from insights.intelligence import MODEL, recommend
from insights.sources import get_source
from insights.store import Store

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = FastAPI(title="Instagram Insights", version="0.2.0")

SOURCES = ("mock", "instagram")
Source = Query("mock", pattern="^(mock|instagram)$")


def _store(source: str) -> Store:
    # One database per source, so sample data never mixes with a real account.
    return Store(str(ROOT / f"insights_{source}.db"))


def _stats(source: str):
    posts = _store(source).all_posts()
    if not posts:
        raise HTTPException(404, f"No {source} posts stored yet - sync first")
    return analyse(posts)


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/status")
def status():
    """What's configured, so the dashboard can show it."""
    return {
        "llm": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
        "llm_model": MODEL,
        "instagram": bool(os.environ.get("IG_ACCESS_TOKEN")),
        "stored": {s: len(_store(s).all_posts()) for s in SOURCES},
    }


@app.post("/api/sync")
def sync(source: str = Source, limit: int = Query(100, ge=1, le=1000)):
    """Pull posts from the source and store them."""
    try:
        posts = get_source(source).fetch_posts(limit=limit)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    return {"stored": _store(source).upsert(posts), "source": source}


@app.get("/api/stats")
def stats(source: str = Source):
    """Performance breakdown by format, topic, day, time, hashtags, caption length and CTA."""
    return _stats(source)


@app.get("/api/recommendations")
def recommendations(source: str = Source, context: str = "", use_llm: bool = True):
    """Evidence-backed content recommendations."""
    return recommend(_stats(source), account_context=context, use_llm=use_llm)
