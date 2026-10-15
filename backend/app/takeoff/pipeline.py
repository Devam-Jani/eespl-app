"""Reading one drawing revision: DWG to DXF (kept beside the DWG, versioned with the revision),
the DXF read, the viewer's geometry written, the areas found. A failure is stored as the plain
message to show, never raised to the user as a crash."""

import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.takeoff import dwg, reader, service
from app.takeoff.models import CadFile

log = logging.getLogger("eespl.takeoff")
READABLE = (".dwg", ".dxf")


def media(rel: str) -> Path:
    return Path(settings.media_dir) / rel


def process(db: Session, f: CadFile) -> CadFile:
    from app.sites.models import DrawingRevision  # noqa: PLC0415

    rev = db.get(DrawingRevision, f.revision_id)
    src = media(rev.stored_path)
    suffix = src.suffix.lower()
    f.status, f.error = "reading", None
    db.commit()
    try:
        if suffix not in READABLE:
            raise dwg.CadError("Only AutoCAD drawings (.dwg or .dxf) can be read for areas.")
        if not src.is_file():
            raise dwg.CadError("The drawing's file is missing on the server; upload it again.")
        dwg.check_size(src.stat().st_size)
        warnings: list[str] = []
        if suffix == ".dwg":
            with src.open("rb") as fh:
                v = dwg.version(fh.read(6))
            f.dwg_version = f"{v.name} ({v.code})"
            dxf_rel = str(Path(rev.stored_path).with_suffix(".dxf"))
            warnings = dwg.to_dxf(src, media(dxf_rel))
            f.dxf_path = dxf_rel
        else:
            f.dwg_version = "DXF"
            f.dxf_path = rev.stored_path
        parsed = reader.read(media(f.dxf_path), f.dwg_version, service.hidden_layers(db, f))
        geo_rel = str(Path(rev.stored_path).with_suffix(".geometry.json.gz"))
        reader.write_geometry(parsed, media(geo_rel))
        f.geometry_path = geo_rel
        f.units_code = parsed.units_code
        if not f.units_set_by_hand:
            f.unit_m = parsed.unit_m
        f.summary = parsed.summary() | {"converter_warnings": len(warnings)}
        f.texts = parsed.texts
        f.dimensions = parsed.dimensions
        f.warnings = len(warnings)
        f.read_at = datetime.now(UTC)
        service.build_areas(db, f)
        f.status = "ready"
    except dwg.CadError as exc:
        db.rollback()
        f = db.get(CadFile, f.id)
        f.status, f.error = "failed", str(exc)
    except Exception as exc:  # noqa: BLE001  (never a crash: the message says what happened)
        log.exception("reading cad file %s failed", f.id)
        db.rollback()
        f = db.get(CadFile, f.id)
        f.status = "failed"
        f.error = (
            f"The drawing could not be read ({type(exc).__name__}). "
            "Try saving it as AutoCAD 2018 DWG and upload again."
        )
    db.commit()
    return f


def process_id(cad_file_id: int) -> None:
    """For a background task: its own session."""
    from app.db import SessionLocal  # noqa: PLC0415

    with SessionLocal() as db:
        f = db.get(CadFile, cad_file_id)
        if f is not None and f.status in ("queued", "reading"):
            process(db, f)


def sweep() -> None:
    """The worker: drawings left queued (an API restart mid-read)."""
    from app.db import SessionLocal  # noqa: PLC0415

    with SessionLocal() as db:
        ids = list(db.scalars(select(CadFile.id).where(CadFile.status == "queued").limit(3)))
    for i in ids:
        process_id(i)
