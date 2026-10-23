# ruff: noqa: E501
""""Ask the helper": Claude explains an error and the next step, from the page's help text, the
field rules and the error. Off unless HELPER_AI_ENABLED is set (and the API key is in .env). It
never changes data: it only answers. What it is sent is scrubbed: no passwords, keys or tokens, no
place; for a client user no cost, rate or margin. Tests replace _post (no real call)."""

import httpx

from app.config import settings
from app.issues.service import for_ai

API_VERSION = "2023-06-01"
SYSTEM = (
    "You are the in-app helper of a waterproofing company's business app. A user hit a problem on a page. "
    "In plain, short words (at most 6 sentences), say what most likely went wrong and what the user can do next, "
    "using only the page's help text, the field rules and the error given. Never ask for passwords or keys. "
    "Never claim you changed anything: you cannot change data. If the error looks like a bug on our side, say it is "
    "recorded and suggest 'Report this' with what they were doing. Do not use names of people."
)


def enabled() -> bool:
    return bool(settings.helper_ai_enabled and settings.anthropic_api_key and settings.anthropic_api_key.get_secret_value())


def prompt(*, page: str | None, help_text: str | None, field_rules: list[str], error: str | None, question: str | None, client: bool) -> str:
    """The one message the AI gets (built here so a test can read exactly what is sent)."""
    parts = [f"Page: {for_ai(page, client)}"]
    if help_text:
        parts.append(f"The page's help:\n{for_ai(help_text, client)}")
    if field_rules:
        parts.append("Field rules:\n" + "\n".join(f"- {for_ai(r, client)}" for r in field_rules[:20]))
    if error:
        parts.append(f"The error the user saw:\n{for_ai(error, client)}")
    parts.append(f"The user asks: {for_ai(question, client) if question else 'What went wrong and what do I do now?'}")
    return "\n\n".join(parts)


def _post(payload: dict) -> dict:
    """One call to the Messages API (tests replace this; they never call the real API)."""
    key = settings.anthropic_api_key.get_secret_value()
    with httpx.Client(base_url=settings.anthropic_base_url, timeout=settings.anthropic_timeout_seconds) as c:
        r = c.post("/v1/messages", json=payload, headers={"x-api-key": key, "anthropic-version": API_VERSION})
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} from the AI service")
    return r.json()


def ask(message: str) -> str:
    data = _post({"model": settings.helper_ai_model, "max_tokens": 400, "system": SYSTEM, "messages": [{"role": "user", "content": message}]})
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
