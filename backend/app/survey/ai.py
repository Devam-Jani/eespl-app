"""AI suggestion from an area photo (Claude vision). Off until management turns it on in the
survey settings, and hidden without ANTHROPIC_API_KEY in .env. It suggests the area type, the
condition (cracks, dampness, existing treatment) and the best matching system from our active
systems (names only: no costs leave the app). It never suggests or changes sizes. Each call is
logged with its tokens and estimated cost; calls stop once the month's cap is reached.

The key is only ever sent in the x-api-key header: never stored, logged, or returned.
"""

import base64
import io
import json
import re
from datetime import datetime
from decimal import Decimal

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.execution.common import media
from app.execution.service import IST
from app.masters.models import System
from app.survey.models import AiCall, AreaType, SurveyArea, SurveyPhoto
from app.survey.service import settings

LONG_SIDE = 1600
API_VERSION = "2023-06-01"


def key_present() -> bool:
    key = app_settings.anthropic_api_key
    return key is not None and bool(key.get_secret_value().strip())


def available(db: Session) -> bool:
    return settings(db).ai_enabled and key_present()


def month_spend(db: Session) -> Decimal:
    now = datetime.now(IST)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return Decimal(
        db.scalar(
            select(func.coalesce(func.sum(AiCall.cost_inr), 0)).where(AiCall.created_at >= start)
        )
    )


def _image(photo: SurveyPhoto) -> str:
    """The photo as a JPEG about 1,600 px on its long side, base64."""
    from PIL import Image, ImageOps

    with Image.open(media(photo.stored_path)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((LONG_SIDE, LONG_SIDE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def prompt(db: Session) -> str:
    types = [
        t.name
        for t in db.scalars(
            select(AreaType).where(AreaType.is_active).order_by(AreaType.sort_order)
        )
    ]
    systems = [
        s.name for s in db.scalars(select(System).where(System.is_active).order_by(System.name))
    ]
    return (
        "You look at a site photo for a waterproofing contractor. Answer only with JSON:\n"
        '{"area_type": one of the area types or null, "condition_notes": short notes on cracks, '
        'dampness, existing treatment or surface condition, "system": the best matching system '
        'name from the list or null, "confidence": "low"|"medium"|"high"}.\n'
        "Do not estimate any sizes or quantities.\n"
        f"Area types: {json.dumps(types)}\nSystems: {json.dumps(systems)}"
    )


def _post(payload: dict) -> dict:
    """One call to the Messages API (tests replace this; they never call the real API)."""
    key = app_settings.anthropic_api_key.get_secret_value()
    with httpx.Client(
        base_url=app_settings.anthropic_base_url, timeout=app_settings.anthropic_timeout_seconds
    ) as c:
        r = c.post(
            "/v1/messages",
            json=payload,
            headers={"x-api-key": key, "anthropic-version": API_VERSION},
        )
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code} from the AI service")
    return r.json()


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"condition_notes": text.strip()[:500]}
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return {"condition_notes": text.strip()[:500]}
    return {k: data.get(k) for k in ("area_type", "condition_notes", "system", "confidence")}


def suggest(db: Session, area: SurveyArea, photo: SurveyPhoto, user_id) -> AiCall:
    s = settings(db)
    if not available(db):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "AI suggestions are off")
    if month_spend(db) >= Decimal(s.ai_monthly_cap_inr):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This month's AI spend cap (₹{s.ai_monthly_cap_inr:,.0f}) is reached",
        )
    payload = {
        "model": s.ai_model,
        "max_tokens": 600,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": _image(photo),
                        },
                    },
                    {"type": "text", "text": prompt(db)},
                ],
            }
        ],
    }
    call = AiCall(
        survey_area_id=area.id, photo_id=photo.id, user_id=user_id, model=s.ai_model, status="ok"
    )
    try:
        body = _post(payload)
        usage = body.get("usage") or {}
        call.input_tokens, call.output_tokens = (
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
        )
        text = "".join(
            part.get("text", "") for part in body.get("content", []) if part.get("type") == "text"
        )
        call.suggestion = _match(db, _parse(text))
    except (RuntimeError, httpx.HTTPError, ValueError) as exc:
        call.status, call.error = "error", str(exc)[:300]
    usd = (
        Decimal(call.input_tokens) * Decimal(s.ai_usd_per_mtok_in)
        + Decimal(call.output_tokens) * Decimal(s.ai_usd_per_mtok_out)
    ) / Decimal(1_000_000)
    call.cost_inr = (usd * Decimal(s.ai_inr_per_usd)).quantize(Decimal("0.0001"))
    db.add(call)
    db.flush()
    if call.status == "ok":
        area.ai_suggestion = {"call_id": call.id, **(call.suggestion or {})}
    return call


def _match(db: Session, s: dict) -> dict:
    """Tie the suggested names to our area type and system ids (unknown names are dropped)."""
    out = dict(s)
    if s.get("area_type"):
        t = db.scalar(
            select(AreaType).where(func.lower(AreaType.name) == str(s["area_type"]).lower())
        )
        out["area_type_id"] = t.id if t else None
    if s.get("system"):
        sy = db.scalar(
            select(System).where(
                func.lower(System.name) == str(s["system"]).lower(), System.is_active
            )
        )
        out["system_id"] = sy.id if sy else None
    return out
