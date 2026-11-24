"""HTTP API + web dashboard over the same pipeline as the CLI.

    uvicorn api:app --port 8000
    open http://127.0.0.1:8000        (dashboard)
    open http://127.0.0.1:8000/docs   (API docs)
"""
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message=".*OpenSSL.*")
warnings.filterwarnings("ignore", message="Mean of empty slice")  # expected for accounts without reach data

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from insights import pipeline
from insights.intelligence import build_llm_payload, recommend
from insights.llm import MODEL, llm_available
from insights.store import Store

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
app = FastAPI(title="Instagram Content Intelligence System", version="0.3.0")

SOURCES = ("mock", "instagram")
Source = Query("mock", pattern="^(mock|instagram)$")


def _store(source: str) -> Store:
    # One database per source, so sample data never mixes with a real account.
    db_dir = Path(os.environ.get("ICIS_DB_DIR") or ROOT)
    return Store(str(db_dir / f"insights_{source}.db"))


def _stats(source: str, use_llm: bool):
    try:
        return pipeline.analyse_store(_store(source), use_llm=use_llm)
    except LookupError as e:
        raise HTTPException(404, f"No {source} posts stored yet - sync first") from e


@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/status")
def status():
    """What's configured, so the dashboard can show it."""
    return {
        "llm": llm_available(),
        "llm_model": MODEL,
        "instagram": bool(os.environ.get("IG_ACCESS_TOKEN")),
        "stored": {s: _store(s).count() for s in SOURCES},
    }


@app.post("/api/sync")
def sync(source: str = Source, limit: int = Query(100, ge=1, le=1000)):
    """Pull posts from the source and store them."""
    try:
        n = pipeline.collect(_store(source), source, limit=limit)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    return {"stored": n, "source": source}


@app.get("/api/stats")
def stats(source: str = Source, use_llm: bool = True):
    """Performance breakdown, trends, best/worst posts. `use_llm` controls caption tagging."""
    return _stats(source, use_llm)


@app.get("/api/recommendations")
def recommendations(source: str = Source, context: str = "", use_llm: bool = True):
    """Evidence-backed content recommendations, each checked against the data."""
    return recommend(_stats(source, use_llm), account_context=context, use_llm=use_llm)


@app.get("/api/llm-input")
def llm_input(source: str = Source, context: str = "", use_llm: bool = True):
    """Exactly what the intelligence layer sends to the LLM - for transparency."""
    return build_llm_payload(_stats(source, use_llm), context)
