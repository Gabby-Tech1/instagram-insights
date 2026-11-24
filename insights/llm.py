"""One place that talks to Claude, so every LLM feature gets the same guardrails:
structured JSON output validated against a schema, refusal/truncation checks,
and a clear exception the caller can turn into a non-AI fallback."""
from __future__ import annotations

import json
import os
from typing import Dict

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")


class LLMError(RuntimeError):
    """Raised for any LLM failure. Callers catch it and fall back to rules."""


def llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def claude_json(system: str, user: str, schema: Dict, effort: str = "medium", max_tokens: int = 16000) -> Dict:
    """Ask Claude for JSON matching `schema`. Returns the parsed object or raises LLMError."""
    import anthropic

    try:
        response = anthropic.Anthropic().beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            # If a safety classifier declines, the API retries on a suitable model server-side.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.APIError as e:
        raise LLMError(f"Claude API error: {e}") from e

    if response.stop_reason == "refusal":
        raise LLMError(f"model declined: {getattr(response, 'stop_details', None)}")
    if response.stop_reason == "max_tokens":
        raise LLMError("response hit max_tokens before finishing")
    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"response was not valid JSON: {e}") from e
