"""The HTTP API end to end, on temporary databases."""
import pytest
from fastapi.testclient import TestClient

import api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ICIS_DB_DIR", str(tmp_path))
    return TestClient(api.app)


def test_dashboard_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Content Intelligence" in r.text


def test_full_workflow_on_sample_data(client):
    assert client.get("/api/status").json()["stored"] == {"mock": 0, "instagram": 0}
    assert client.get("/api/stats").status_code == 404  # nothing synced yet

    assert client.post("/api/sync?source=mock").json() == {"stored": 96, "source": "mock"}
    stats = client.get("/api/stats").json()
    assert stats["overview"]["posts_analysed"] == 96 and stats["bottom_posts"] and stats["monthly_trend"]

    recs = client.get("/api/recommendations?use_llm=false").json()
    assert recs["engine"] == "rule-based" and recs["grounding_summary"]["total"] == len(recs["recommendations"])

    payload = client.get("/api/llm-input?context=coffee").json()
    assert payload["account_context"] == "coffee"


def test_sync_is_idempotent(client):
    client.post("/api/sync?source=mock")
    client.post("/api/sync?source=mock")
    assert client.get("/api/status").json()["stored"]["mock"] == 96


def test_instagram_without_token_gives_clear_error(client):
    r = client.post("/api/sync?source=instagram")
    assert r.status_code == 400 and "IG_ACCESS_TOKEN" in r.json()["detail"]


def test_unknown_source_rejected(client):
    assert client.post("/api/sync?source=tiktok").status_code == 422
