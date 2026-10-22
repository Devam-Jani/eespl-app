# ruff: noqa: E501
"""Health, the settings that must be filled before go-live, the media volume's size, the backup
status and the missed-backup alert.

The worker writes its heartbeat every round; the backup job (its own container, nightly) writes
the last archive's time, size and copy here. The health page reads both, and the database and our
OSRM. A night without a backup tells the director and the office admin (in the app, and by email to
staff when EMAIL_ENABLED is set)."""

import os
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.ops.models import SystemStatus

WORKER_STALE = timedelta(minutes=3)  # the worker ticks every minute
BACKUP_STALE = timedelta(hours=26)  # nightly, with two hours to spare


def now() -> datetime:
    return datetime.now(UTC)


def put(db: Session, key: str, value: dict[str, Any], at: datetime | None = None) -> None:
    row = db.get(SystemStatus, key)
    if row is None:
        row = SystemStatus(key=key)
        db.add(row)
    row.value, row.at = value, at or now()


def get(db: Session, key: str) -> SystemStatus | None:
    return db.get(SystemStatus, key)


def heartbeat(db: Session) -> None:
    put(db, "worker", {"pid": os.getpid()})
    db.commit()


# --- health -------------------------------------------------------------------------------------


def _osrm() -> tuple[str, str | None]:
    """A short route in Ahmedabad on our own OSRM (nothing leaves the server)."""
    url = f"{settings.osrm_url}/route/v1/driving/72.5714,23.0225;72.5800,23.0300?overview=false"
    try:
        with urllib.request.urlopen(url, timeout=4) as r:  # noqa: S310  (our own container)
            return ("ok", None) if r.status == 200 else ("error", f"HTTP {r.status}")
    except Exception as exc:  # noqa: BLE001
        return "error", type(exc).__name__


def health(db: Session) -> dict:
    out: dict[str, Any] = {}
    try:
        db.execute(text("SELECT 1"))
        out["db"] = "ok"
    except Exception as exc:  # noqa: BLE001
        out["db"] = "error"
        out["db_detail"] = type(exc).__name__
        return {"status": "error", **out}
    w = get(db, "worker")
    out["worker"] = "ok" if w and now() - w.at < WORKER_STALE else "stale" if w else "never ran"
    out["worker_seen"] = w.at.isoformat() if w else None
    out["osrm"], detail = _osrm()
    if detail:
        out["osrm_detail"] = detail
    b = get(db, "backup")
    out["last_backup"] = b.at.isoformat() if b else None
    if settings.backup_enabled:
        out["backup"] = "ok" if b and now() - b.at < BACKUP_STALE and b.value.get("ok") else "missed"
    if settings.training_mode:
        out["company"] = "training"
    bad = [k for k in ("db", "worker", "osrm", "backup") if out.get(k) not in (None, "ok")]
    out["status"] = "ok" if not bad else "degraded"
    out["problems"] = bad
    return out


# --- the settings to fill before go-live -------------------------------------------------------------


def go_live_checks(db: Session) -> list[dict]:
    """What is not set yet: each with where to fill it. Empty when the company is ready."""
    from app.masters.models import (  # noqa: PLC0415
        CompanyBankAccount,
        CompanyGstin,
        CompanyProfile,
        Product,
    )
    from app.quotations.models import Letterhead  # noqa: PLC0415

    out = []
    p = db.get(CompanyProfile, 1)
    if p is None or not p.legal_name or not p.pan:
        out.append({"key": "company", "what": "Company legal name and PAN", "where": "/settings/company"})
    g = db.scalar(select(CompanyGstin).where(CompanyGstin.is_default).limit(1))
    if g is None or not (g.address or "").strip():
        out.append({"key": "gstin", "what": "The company's GSTIN and address (a default one)", "where": "/settings/gstins"})
    if db.scalar(select(CompanyBankAccount.id).where(CompanyBankAccount.is_default).limit(1)) is None:
        out.append({"key": "bank", "what": "The bank account printed on invoices (a default one)", "where": "/settings/bank-accounts"})
    no_hsn = db.scalar(select(func.count()).select_from(Product).where(Product.is_active, Product.is_demo.is_(False), (Product.hsn_code.is_(None)) | (Product.hsn_code == "")))
    if no_hsn:
        out.append({"key": "hsn", "what": f"HSN codes: {no_hsn} active products have none (invoices need them)", "where": "/products?missing=hsn"})
    h = db.scalars(select(Letterhead).where(Letterhead.is_active).order_by(Letterhead.id)).first()
    if h is None or not h.signatory_name or not h.signatory_designation:
        out.append({"key": "letterhead", "what": "The letterhead's signatory and designation (certificates and offers)", "where": "/settings/quotation-library"})
    return out


# --- the media volume -----------------------------------------------------------------------------------


def media_report(root: str | None = None) -> dict:
    """Size of the media volume by top folder (photos, drawings, PDFs ...), largest first."""
    base = Path(root or settings.media_dir)
    folders: dict[str, list[int]] = {}
    total = files = 0
    if base.exists():
        for dirpath, _dirs, names in os.walk(base):
            rel = Path(dirpath).relative_to(base)
            top = rel.parts[0] if rel.parts else "(top)"
            for n in names:
                try:
                    size = (Path(dirpath) / n).stat().st_size
                except OSError:
                    continue
                f = folders.setdefault(top, [0, 0])
                f[0] += size
                f[1] += 1
                total += size
                files += 1
    rows = sorted(({"folder": k, "bytes": v[0], "files": v[1]} for k, v in folders.items()), key=lambda r: -r["bytes"])
    return {"bytes": total, "files": files, "folders": rows}


# --- backups -------------------------------------------------------------------------------------------


def backup_status(db: Session) -> dict:
    b = get(db, "backup")
    val = dict(b.value) if b else {}
    return {"enabled": settings.backup_enabled, "last_at": b.at if b else None, "ok": bool(val.get("ok")), "archive": val.get("archive"), "bytes": val.get("bytes"),
            "offsite": val.get("offsite"), "kept": val.get("kept"), "removed": val.get("removed"), "error": val.get("error"),
            "missed": bool(settings.backup_enabled and (b is None or now() - b.at >= BACKUP_STALE or not val.get("ok"))),
            "retention": {"daily": settings.backup_keep_daily, "weekly": settings.backup_keep_weekly, "monthly": settings.backup_keep_monthly}}  # fmt: skip


def missed_backup_sweep(db: Session, at: datetime | None = None) -> bool:
    """A night without a good backup: tell the director and the office admin (once a day)."""
    if not settings.backup_enabled:
        return False
    at = at or now()
    b = get(db, "backup")
    if b is not None and at - b.at < BACKUP_STALE and b.value.get("ok"):
        return False
    from app.process import engine  # noqa: PLC0415

    last = b.at.strftime("%d.%m.%Y %H:%M") if b else "never"
    why = (b.value.get("error") if b else None) or "no backup ran"
    ev = engine.emit(db, "backup_missed", subject=f"backup:{at:%Y-%m-%d}", at=at, data={"last": last, "why": why[:200]})
    db.commit()
    return ev is not None
