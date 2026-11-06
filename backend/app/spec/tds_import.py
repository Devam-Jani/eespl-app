# ruff: noqa: E501  (the count rows read better unwrapped)
"""Importing data sheets: each PDF is read and kept as a preview (its file under media/, its facts),
matched to the product master or offered as a new product; nothing is a product's sheet until the
import is saved. The same PDF twice, or the same product of the same brand twice in one import, is
merged into one (the newer or fuller sheet kept); a sheet for a product that already has a saved one
replaces it only once confirmed. A scanned PDF (no text) is listed as "needs reading"."""

import hashlib
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.knowledge import extract
from app.masters.bom import _code, norm
from app.masters.models import Product
from app.spec import tds
from app.spec.models import TdsDoc, TdsFact, TdsImport

MAX_BYTES = 40 * 1024 * 1024
MATCH_AT = 0.6
# a brand's own marks and maker words: not part of the product's name when matching
NOISE_WORDS = {
    "THE",
    "AND",
    "OF",
    "FOR",
    "WITH",
    "LTD",
    "PVT",
    "INDIA",
    "SHEET",
    "DATA",
    "TECHNICAL",
    "PRODUCT",
}


def media(rel: str) -> Path:
    return Path(settings.media_dir) / rel


def _words(name: str, brand: str | None) -> set[str]:
    t = re.sub(r"[^A-Z0-9 ]", " ", norm(name))
    drop = set(re.sub(r"[^A-Z0-9 ]", " ", (brand or "").upper()).split()) | NOISE_WORDS
    return {w for w in t.split() if w not in drop and len(w) > 1}


def product_key(brand: str | None, name: str) -> str:
    return f"{(brand or '').strip().lower()}|{' '.join(sorted(_words(name, brand)))}"


def match_product(
    db: Session, brand: str | None, name: str, products: list[Product] | None = None
) -> tuple[Product | None, float]:
    """The product master's product this sheet is for: the same words (the brand's own left
    out), or most of them with the same brand. (product, score)"""
    want = _words(name, brand)
    if not want:
        return None, 0.0
    best, score = None, 0.0
    for p in (
        products
        if products is not None
        else db.scalars(select(Product).where(Product.is_active.is_(True)))
    ):
        names = [p.name, *(p.aliases or [])]
        same_brand = bool(
            brand
            and p.brand
            and (p.brand.lower() in brand.lower() or brand.lower() in p.brand.lower())
        )
        for n in names:
            have = _words(n, p.brand or brand)
            if not have:
                continue
            s = len(want & have) / len(want | have)
            if not same_brand and brand and p.brand:
                s *= 0.5  # another brand's product of the same name is not this one
            if s > score:
                best, score = p, s
    return (best, score) if score >= MATCH_AT else (None, score)


def brand_from_text(text: str) -> str | None:
    head = text[:1500]
    for label, pat in extract.BRANDS:
        if re.search(pat, head, re.I):
            return label.split(" / ")[0]
    return None


def stage(
    db: Session,
    imp: TdsImport,
    rel_path: str,
    data: bytes,
    user_id=None,
    products: list[Product] | None = None,
) -> TdsDoc:
    """Read one PDF into the import's preview."""
    sha = hashlib.sha256(data).hexdigest()
    file_name = Path(rel_path).name
    brand = tds.brand_of(rel_path)
    doc = TdsDoc(
        import_id=imp.id,
        file_name=file_name[:300],
        rel_path=rel_path,
        sha256=sha,
        imported_by=user_id,
        product_name=file_name[:200],
    )
    db.add(doc)
    db.flush()
    same = db.scalar(
        select(TdsDoc).where(
            TdsDoc.import_id == imp.id,
            TdsDoc.sha256 == sha,
            TdsDoc.status != "duplicate",
            TdsDoc.id != doc.id,
        )
    )
    if same is None:
        same = db.scalar(select(TdsDoc).where(TdsDoc.sha256 == sha, TdsDoc.status == "saved"))
    if same is not None:
        doc.brand, doc.product_name = same.brand, same.product_name
        doc.status, doc.duplicate_of_id, doc.match = "duplicate", same.id, "skip"
        db.flush()
        return doc
    if tds.NOT_TDS.search(file_name):
        doc.brand, doc.product_name, doc.status, doc.match = (
            brand,
            tds.product_name(file_name, brand)[:200],
            "skipped",
            "skip",
        )
        doc.read_error = "A safety data sheet (MSDS), not a TDS"
        db.flush()
        return doc
    sheet = tds.read_pdf(data)
    doc.brand = brand or (brand_from_text(sheet.text) if not sheet.error else None)
    doc.product_name = tds.product_name(file_name, doc.brand)[:200]
    doc.pages, doc.chars = len(sheet.pages), len(sheet.text)
    doc.read_error = sheet.error
    doc.needs_reading = sheet.scanned
    rel = f"tds/{imp.id}/{uuid.uuid4().hex}__{re.sub(r'[^A-Za-z0-9._ -]', '_', file_name)[-150:]}"
    media(rel).parent.mkdir(parents=True, exist_ok=True)
    media(rel).write_bytes(data)
    doc.stored_path = rel
    p, _score = match_product(db, doc.brand, doc.product_name, products)
    doc.product_id, doc.match = (p.id, "matched") if p else (None, "create")
    db.flush()
    if not sheet.error and not sheet.scanned:
        for f in tds.facts(sheet, doc.product_name):
            db.add(TdsFact(doc_id=doc.id, kind=f.kind, key=f.key, lo=f.lo, hi=f.hi, unit=f.unit, text=f.text[:500], standard=f.standard,
                           page=f.page, sentence=f.sentence, per_coat=f.per_coat, coats=f.coats, source="rule"))  # fmt: skip
    # the same product of the same brand already in this import: the fuller sheet stays
    key = product_key(doc.brand, doc.product_name)
    for other in db.scalars(
        select(TdsDoc).where(
            TdsDoc.import_id == imp.id, TdsDoc.status == "preview", TdsDoc.id != doc.id
        )
    ):
        if product_key(other.brand, other.product_name) == key:
            keep, drop = (doc, other) if doc.chars > other.chars else (other, doc)
            drop.status, drop.duplicate_of_id = "duplicate", keep.id
            break
    # a saved sheet for this product: replaced only once confirmed
    if doc.status == "preview":
        for saved in db.scalars(select(TdsDoc).where(TdsDoc.status == "saved")):
            if product_key(saved.brand, saved.product_name) == key or (
                doc.product_id and saved.product_id == doc.product_id
            ):
                doc.replaces_id = saved.id
                break
    db.flush()
    return doc


def save(db: Session, imp: TdsImport, create: set[int], replace: set[int], user_id=None) -> dict:
    """Keep the preview: each sheet becomes its product's (the product master's, or a new one
    where asked); one that would replace a saved sheet only where confirmed."""
    made = kept = replaced = held = 0
    for doc in db.scalars(
        select(TdsDoc)
        .where(TdsDoc.import_id == imp.id, TdsDoc.status == "preview")
        .order_by(TdsDoc.id)
    ):
        if doc.replaces_id:
            if doc.id not in replace:
                doc.status = "duplicate"  # not confirmed: the saved sheet stays the product's
                doc.duplicate_of_id = doc.replaces_id
                held += 1
                continue
            old = db.get(TdsDoc, doc.replaces_id)
            if old is not None:
                old.status = "replaced"
                doc.product_id = doc.product_id or old.product_id
            doc.replace_confirmed = True
            replaced += 1
        if doc.product_id is None and doc.id in create:
            doc.product_id = new_product(db, doc, user_id).id
            doc.match = "matched"
            made += 1
        elif doc.product_id is None:
            doc.match = "skip"
        doc.status = "saved"
        kept += 1
        for f in db.scalars(select(TdsFact).where(TdsFact.doc_id == doc.id)):
            f.product_id = doc.product_id
    imp.status, imp.saved_at = "saved", datetime.now(UTC)
    db.flush()
    return {"saved": kept, "products_created": made, "replaced": replaced, "kept_older": held}


def new_product(db: Session, doc: TdsDoc, user_id=None) -> Product:
    facts = list(db.scalars(select(TdsFact).where(TdsFact.doc_id == doc.id)))
    unit = "kg"
    use = next((f.key for f in facts if f.kind == "consumption" and f.key), "")
    if use.startswith("L/"):
        unit = "ltr"
    elif any(f.kind == "chemistry" and f.key in ("mesh", "geotextile") for f in facts):
        unit = "sqm"
    elif any(f.kind == "chemistry" and f.key in ("tape", "swellable") for f in facts):
        unit = "rmt"
    pack = next((f for f in facts if f.kind == "pack" and f.lo), None)
    name = (
        doc.product_name
        if not doc.brand or doc.brand.lower() in doc.product_name.lower()
        else f"{doc.brand} {doc.product_name}"
    )
    p = Product(code=_code(db, "TDS-P", norm(f"{doc.brand}|{doc.product_name}"), Product), name=name[:200], brand=doc.brand, unit=unit,
                pack_size=Decimal(pack.lo) if pack and unit in ("kg", "ltr") else None, pack_unit=unit if pack and unit in ("kg", "ltr") else None,
                created_by=user_id)  # fmt: skip
    db.add(p)
    db.flush()
    return p


def discard(db: Session, imp: TdsImport) -> int:
    n = 0
    for doc in db.scalars(
        select(TdsDoc).where(
            TdsDoc.import_id == imp.id, TdsDoc.status.in_(("preview", "duplicate", "skipped"))
        )
    ):
        if doc.stored_path and not db.scalar(
            select(TdsDoc.id).where(TdsDoc.stored_path == doc.stored_path, TdsDoc.id != doc.id)
        ):
            media(doc.stored_path).unlink(missing_ok=True)
        db.delete(doc)
        n += 1
    imp.status = "discarded"
    db.flush()
    return n


def counts(db: Session, imp: TdsImport) -> dict:
    docs = list(db.scalars(select(TdsDoc).where(TdsDoc.import_id == imp.id)))
    read = [d for d in docs if d.status in ("preview", "saved")]
    facts = db.execute(
        select(TdsFact.kind, TdsFact.doc_id)
        .join(TdsDoc)
        .where(TdsDoc.import_id == imp.id, TdsDoc.status.in_(("preview", "saved")))
    ).all()
    by_kind: dict[str, int] = {}
    for k, _d in facts:
        by_kind[k] = by_kind.get(k, 0) + 1
    with_facts = {d for _k, d in facts}
    return {
        "files": len(docs),
        "products_read": len(read),
        "with_facts": len([d for d in read if d.id in with_facts]),
        "needs_reading": len([d for d in read if d.needs_reading]),
        "read_errors": len([d for d in read if d.read_error]),
        "duplicates": len([d for d in docs if d.status == "duplicate"]),
        "skipped": len([d for d in docs if d.status == "skipped"]),
        "matched": len([d for d in read if d.match == "matched"]),
        "to_create": len([d for d in read if d.match == "create"]),
        "replaces_saved": len([d for d in read if d.replaces_id]),
        "brands": len({d.brand for d in read if d.brand}),
        "facts": by_kind,
    }
