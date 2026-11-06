# ruff: noqa: E501
"""The AI's two jobs here, both off unless HELPER_AI_ENABLED (and the API key in .env): read a
scanned data sheet's pages (vision), and add the key points the rules missed on a BOQ line. It
only proposes: a sheet's facts are shown for a person to confirm (never saved without a click), a
line's chips stay "suggested by AI" until confirmed. Tests replace _post (no real call)."""

import base64
import io
import json
import re

import httpx

from app.config import settings
from app.issues.helper_ai import enabled  # noqa: F401  (the one switch for every AI helper)
from app.spec import vocab

API_VERSION = "2023-06-01"
MAX_PAGES = 3
FACT_KINDS = (
    "chemistry",
    "use",
    "consumption",
    "coats",
    "dft",
    "thickness",
    "pack",
    "density",
    "solids",
    "primer",
    "uv",
    "potable",
    "property",
)
TDS_SYSTEM = (
    "You read a construction chemical's technical data sheet (TDS) from page images. Return ONLY a JSON array of facts the pages state, "
    'never a guess. Each fact: {"kind": one of '
    + ", ".join(FACT_KINDS)
    + ', "key": for chemistry one of '
    + ", ".join(vocab.TYPE_LABEL)
    + "; for use one of "
    + ", ".join(k for k, _p in vocab.USES)
    + "; for property one of "
    + ", ".join(vocab.PROPERTY_LABEL)
    + '; for consumption the unit as kg/sqm, L/sqm, kg/rmt or kg/sqm/mm, "lo": number, "hi": number, "unit": text, '
    '"standard": e.g. ASTM D412 or null, "page": 1-based, "sentence": the words on the page}. Convert sq ft to sqm (1 sqm = 10.7639 sq ft).'
)
LINE_SYSTEM = (
    "You read one BOQ line of a waterproofing tender. Other key points were already read by rules (given). Return ONLY a JSON array of the "
    'key points the rules MISSED, each {"kind": one of area, system, coats, dft, thickness, kg_sqm, mesh, upturn, protection, property, '
    'make, potable, uv, pond_test, warranty, "label": short words, "value": object, "words": the exact words of the line it came from}. '
    "Never repeat a key point already given. An empty array when nothing is missed."
)


def _post(payload: dict) -> dict:
    """One call to the Messages API (tests replace this; they never call the real API)."""
    key = settings.anthropic_api_key.get_secret_value()
    with httpx.Client(
        base_url=settings.anthropic_base_url, timeout=settings.anthropic_timeout_seconds
    ) as c:
        r = c.post(
            "/v1/messages",
            json=payload,
            headers={"x-api-key": key, "anthropic-version": API_VERSION},
        )
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} from the AI service")
    return r.json()


def _text(data: dict) -> str:
    return "".join(
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    ).strip()


def _array(text: str) -> list:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [x for x in out if isinstance(x, dict)]


def page_images(data: bytes) -> list[str]:
    """The first pages as PNG (base64), for the vision read."""
    import pypdfium2 as pdfium  # noqa: PLC0415

    pdf = pdfium.PdfDocument(data)
    out = []
    for i in range(min(len(pdf), MAX_PAGES)):
        img = pdf[i].render(scale=1.6).to_pil()
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out.append(base64.b64encode(buf.getvalue()).decode())
    return out


def read_sheet(data: bytes, product: str) -> list[dict]:
    """The facts the AI reads on a scanned sheet: proposals only."""
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b}}
        for b in page_images(data)
    ]
    content.append({"type": "text", "text": f"The product: {product}. List the facts."})
    raw = _array(
        _text(
            _post(
                {
                    "model": settings.helper_ai_model,
                    "max_tokens": 2000,
                    "system": TDS_SYSTEM,
                    "messages": [{"role": "user", "content": content}],
                }
            )
        )
    )
    out = []
    for f in raw:
        if f.get("kind") not in FACT_KINDS:
            continue
        out.append({"kind": f["kind"], "key": (str(f.get("key"))[:30] if f.get("key") is not None else None), "lo": vocab.dec(f.get("lo")) if f.get("lo") is not None else None,
                    "hi": vocab.dec(f.get("hi")) if f.get("hi") is not None else None, "unit": (str(f.get("unit"))[:20] if f.get("unit") else None),
                    "standard": (str(f.get("standard"))[:40] if f.get("standard") else None), "page": f.get("page") if isinstance(f.get("page"), int) else None,
                    "sentence": str(f.get("sentence") or "")[:300], "text": str(f.get("sentence") or "")[:120], "source": "ai"})  # fmt: skip
    return out


def line_points(text: str, chips: list[dict]) -> list[dict]:
    """The key points the rules missed: each a chip "suggested by AI", not confirmed."""
    given = "\n".join(f"- {c['kind']}: {c['label']}" for c in chips)
    msg = f"The line:\n{text}\n\nAlready read:\n{given or '(none)'}"
    raw = _array(
        _text(
            _post(
                {
                    "model": settings.helper_ai_model,
                    "max_tokens": 800,
                    "system": LINE_SYSTEM,
                    "messages": [{"role": "user", "content": msg}],
                }
            )
        )
    )
    have = {(c["kind"], c["label"].lower()) for c in chips}
    out = []
    for r in raw:
        kind, label = str(r.get("kind") or ""), str(r.get("label") or "")[:120]
        if not kind or not label or (kind, label.lower()) in have:
            continue
        words = str(r.get("words") or "")
        s = text.lower().find(words.lower()) if words else -1
        out.append({"kind": kind, "label": label, "value": r.get("value") if isinstance(r.get("value"), dict) else {},
                    "spans": [[s, s + len(words)]] if s >= 0 else [], "words": words[:200], "source": "ai", "confirmed": False})  # fmt: skip
    return out
