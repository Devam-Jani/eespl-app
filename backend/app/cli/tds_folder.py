"""python -m app.cli tds-import --dir FOLDER [--save] (Prompt 39a): every PDF under the folder read
into one preview import (the brand from its folder), the same as Settings > Products > Technical
data does in batches; without --save it stays a preview to look at (and save or drop) on that page.
Prints the counts."""

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.masters.models import Product
from app.spec import tds_import
from app.spec.models import TdsDoc, TdsImport


def run(db: Session, folder: Path, save: bool = False) -> str:
    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")
    imp = TdsImport()
    db.add(imp)
    db.flush()
    products = list(db.scalars(select(Product).where(Product.is_active.is_(True))))
    for i, f in enumerate(files, start=1):
        data = f.read_bytes()
        if len(data) > tds_import.MAX_BYTES:
            continue
        tds_import.stage(db, imp, f.relative_to(folder).as_posix(), data, None, products)
        if i % 50 == 0:
            db.commit()
    db.commit()
    out = {"import_id": imp.id, "pdfs": len(files), **tds_import.counts(db, imp)}
    if save:
        create = set(
            db.scalars(
                select(TdsDoc.id).where(
                    TdsDoc.import_id == imp.id, TdsDoc.status == "preview", TdsDoc.match == "create"
                )
            )
        )
        out["saved"] = tds_import.save(db, imp, create, set())
        db.commit()
    return json.dumps(out, indent=1, default=str)
