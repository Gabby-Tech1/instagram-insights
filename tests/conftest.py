import json
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch):
    """Tests never use real keys or tokens, even if a local .env was loaded."""
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "IG_ACCESS_TOKEN", "IG_USER_ID", "ACCOUNT_TIMEZONE"):
        monkeypatch.delenv(var, raising=False)


class FakeClaude:
    """Stands in for anthropic.Anthropic(). `handler(kwargs) -> (stop_reason, text)`."""

    calls = []

    def __init__(self, handler):
        self._handler = handler
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        FakeClaude.calls.append(kwargs)
        stop_reason, text = self._handler(kwargs)
        return SimpleNamespace(stop_reason=stop_reason, stop_details=None,
                               content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture
def fake_claude(monkeypatch):
    """Usage: fake_claude(handler) installs a fake client and an API key; returns the call log."""
    import anthropic

    def install(handler):
        FakeClaude.calls = []
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: FakeClaude(handler))
        return FakeClaude.calls

    return install


def as_json(obj) -> str:
    return json.dumps(obj)
