# ruff: noqa: E501  (the route signatures read better unwrapped)
"""Spec products: the data sheets (Settings > Products > Technical data: import with tds.import,
read with library.view), the consumption master (library.view to see, consumption.edit to change;
prices, cost and margin only with tender.margin), and a BOQ line's key points, its options and the
pick (the line's tender or quotation must be visible; editing needs tender.edit / quotation.edit,
picking also tender.margin as it builds the rate working)."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.auth.deps import CurrentPrincipal, require_permission
from app.costing import prices
from app.costing.models import RateGroupProduct
from app.db import DbSession
from app.execution.common import record, send_file
from app.masters.models import Product, System, SystemComponent
from app.spec import ai, keypoints, master, suggest, tds_import, vocab
from app.spec.models import SpecPoints, TdsDoc, TdsFact, TdsImport

router = APIRouter(prefix="/api/spec", tags=["spec products"])
TdsImportPerm = Annotated[str, Depends(require_permission("tds.import"))]
View = Annotated[str, Depends(require_permission("library.view"))]
MasterEdit = Annotated[str, Depends(require_permission("consumption.edit"))]
EXACT = {Decimal: str}  # figures as kept, never floats


def _j(x: Any) -> Any:
    return jsonable_encoder(x, custom_encoder=EXACT)


def _cost(principal) -> bool:
    return principal.permissions.get("tender.margin") is not None


def _404(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


def _422(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


# --- data sheets ---------------------------------------------------------------------------------


def _doc_out(db, d: TdsDoc, with_facts: bool = False) -> dict:
    p = db.get(Product, d.product_id) if d.product_id else None
    out = {
        "id": d.id, "import_id": d.import_id, "brand": d.brand, "product_name": d.product_name, "file_name": d.file_name, "rel_path": d.rel_path,
        "status": d.status, "needs_reading": d.needs_reading, "read_error": d.read_error, "pages": d.pages, "chars": d.chars,
        "product_id": d.product_id, "product": p.name if p else None, "match": d.match, "duplicate_of_id": d.duplicate_of_id,
        "replaces_id": d.replaces_id, "imported_at": d.imported_at, "has_file": bool(d.stored_path),
    }  # fmt: skip
    facts = list(
        db.scalars(select(TdsFact).where(TdsFact.doc_id == d.id).order_by(TdsFact.kind, TdsFact.id))
    )
    out["fact_count"] = len(facts)
    out["kinds"] = sorted({f.kind for f in facts})
    if with_facts:
        out["facts"] = [
            suggest.fact_out(f)
            | {"original": f.original, "checked_by_name": _who(db, f.checked_by)}
            for f in facts
        ]
    return out


def _who(db, uid) -> str | None:
    from app.models import User  # noqa: PLC0415

    u = db.get(User, uid) if uid else None
    return u.full_name if u and hasattr(u, "full_name") else (u.email if u else None)


@router.post("/tds/imports", status_code=status.HTTP_201_CREATED)
def new_import(db: DbSession, principal: CurrentPrincipal, _: TdsImportPerm) -> dict:
    imp = TdsImport(created_by=principal.user.id)
    db.add(imp)
    db.commit()
    return {"id": imp.id, "status": imp.status}


def _import(db, iid: int) -> TdsImport:
    imp = db.get(TdsImport, iid)
    if imp is None:
        raise _404("Import")
    return imp


@router.post("/tds/imports/{iid}/files")
async def add_files(iid: int, db: DbSession, principal: CurrentPrincipal, _: TdsImportPerm,
                    files: Annotated[list[UploadFile], File()], paths: Annotated[str | None, Form()] = None) -> dict:  # fmt: skip
    """A batch of PDFs of the folder (each with its path in the folder, which gives the brand)."""
    imp = _import(db, iid)
    if imp.status != "preview":
        raise HTTPException(status.HTTP_409_CONFLICT, "This import is already saved or dropped")
    rels = json.loads(paths) if paths else []
    products = list(db.scalars(select(Product).where(Product.is_active.is_(True))))
    out = []
    for i, f in enumerate(files):
        rel = rels[i] if i < len(rels) and rels[i] else (f.filename or "sheet.pdf")
        if not rel.lower().endswith(".pdf"):
            continue
        data = await f.read(tds_import.MAX_BYTES + 1)
        if len(data) > tds_import.MAX_BYTES or b"%PDF" not in data[:1024]:
            out.append(
                {
                    "file_name": rel.rsplit("/", 1)[-1],
                    "status": "skipped",
                    "read_error": "Not a PDF, or over 40 MB",
                }
            )
            continue
        d = tds_import.stage(db, imp, rel, data, principal.user.id, products)
        out.append(_doc_out(db, d))
    db.commit()
    return _j({"docs": out})


@router.get("/tds/imports/{iid}")
def get_import(iid: int, db: DbSession, principal: CurrentPrincipal, _: TdsImportPerm) -> dict:
    imp = _import(db, iid)
    docs = list(
        db.scalars(
            select(TdsDoc)
            .where(TdsDoc.import_id == imp.id)
            .order_by(TdsDoc.brand, TdsDoc.product_name)
        )
    )
    return _j(
        {
            "id": imp.id,
            "status": imp.status,
            "counts": tds_import.counts(db, imp),
            "docs": [_doc_out(db, d) for d in docs],
        }
    )


class SaveIn(BaseModel):
    create: list[int] = Field(default_factory=list)  # docs to make a new product for
    create_all: bool = False
    replace: list[int] = Field(default_factory=list)  # docs confirmed to replace the saved sheet


@router.post("/tds/imports/{iid}/save")
def save_import(
    iid: int,
    body: SaveIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: TdsImportPerm,
) -> dict:
    imp = _import(db, iid)
    if imp.status != "preview":
        raise HTTPException(status.HTTP_409_CONFLICT, "This import is already saved or dropped")
    create = set(body.create)
    if body.create_all:
        create |= set(
            db.scalars(
                select(TdsDoc.id).where(
                    TdsDoc.import_id == imp.id, TdsDoc.status == "preview", TdsDoc.match == "create"
                )
            )
        )
    result = tds_import.save(db, imp, create, set(body.replace), principal.user.id)
    record(db, request, principal, "tds.import", "tds_import", imp.id, after=result)
    db.commit()
    return _j(result | {"counts": tds_import.counts(db, imp)})


@router.post("/tds/imports/{iid}/discard")
def discard_import(iid: int, db: DbSession, principal: CurrentPrincipal, _: TdsImportPerm) -> dict:
    imp = _import(db, iid)
    if imp.status != "preview":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A saved import is not dropped: remove its sheets one by one"
        )
    n = tds_import.discard(db, imp)
    db.commit()
    return {"dropped": n}


class DocProductIn(BaseModel):
    product_id: int | None = None
    match: str = "matched"  # matched, create, skip


@router.put("/tds/docs/{did}/product")
def set_doc_product(
    did: int,
    body: DocProductIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: TdsImportPerm,
) -> dict:
    d = db.get(TdsDoc, did)
    if d is None:
        raise _404("Data sheet")
    if body.match not in ("matched", "create", "skip"):
        raise _422("Choose a product, create one, or keep it without one")
    if body.match == "matched":
        if body.product_id is None or db.get(Product, body.product_id) is None:
            raise _422("Unknown product")
        d.product_id = body.product_id
    else:
        d.product_id = None
    d.match = body.match
    if d.status == "saved":
        for f in db.scalars(select(TdsFact).where(TdsFact.doc_id == d.id)):
            f.product_id = d.product_id
    record(
        db,
        request,
        principal,
        "tds.product",
        "tds_doc",
        d.id,
        after={"product_id": d.product_id, "match": d.match},
    )
    db.commit()
    return _j(_doc_out(db, d))


@router.get("/tds/docs")
def list_docs(db: DbSession, principal: CurrentPrincipal, _: View, q: str = "", brand: str | None = None, needs_reading: bool = False,
              product_id: int | None = None, limit: int = 300) -> dict:  # fmt: skip
    stmt = select(TdsDoc).where(TdsDoc.status == "saved")
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                TdsDoc.product_name.ilike(like),
                TdsDoc.file_name.ilike(like),
                TdsDoc.brand.ilike(like),
            )
        )
    if brand:
        stmt = stmt.where(TdsDoc.brand == brand)
    if needs_reading:
        stmt = stmt.where(TdsDoc.needs_reading.is_(True))
    if product_id:
        stmt = stmt.where(TdsDoc.product_id == product_id)
    docs = list(
        db.scalars(stmt.order_by(TdsDoc.brand, TdsDoc.product_name).limit(min(limit, 1000)))
    )
    brands = sorted(
        {
            b
            for b in db.scalars(select(TdsDoc.brand).where(TdsDoc.status == "saved").distinct())
            if b
        }
    )
    open_import = db.scalar(
        select(TdsImport.id)
        .where(TdsImport.status == "preview")
        .order_by(TdsImport.id.desc())
        .limit(1)
    )
    return _j(
        {
            "docs": [_doc_out(db, d) for d in docs],
            "brands": brands,
            "ai_enabled": ai.enabled(),
            "open_import_id": open_import,
        }
    )


@router.get("/tds/docs/{did}")
def get_doc(did: int, db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    d = db.get(TdsDoc, did)
    if d is None:
        raise _404("Data sheet")
    return _j(_doc_out(db, d, with_facts=True) | {"ai_enabled": ai.enabled()})


@router.get("/tds/docs/{did}/file")
def doc_file(did: int, db: DbSession, principal: CurrentPrincipal, _: View):
    d = db.get(TdsDoc, did)
    if d is None:
        raise _404("Data sheet")
    return send_file(d.stored_path, d.file_name)


class FactIn(BaseModel):
    kind: str
    key: str | None = None
    lo: Decimal | None = None
    hi: Decimal | None = None
    unit: str | None = Field(default=None, max_length=20)
    text: str | None = Field(default=None, max_length=500)
    standard: str | None = Field(default=None, max_length=40)
    page: int | None = None
    sentence: str | None = Field(default=None, max_length=2000)
    per_coat: bool = False
    coats: int | None = None
    source: str = "manual"  # manual, or ai: a proposal a person confirmed with this click


def _fact_ok(body: FactIn) -> None:
    if body.kind not in ai.FACT_KINDS:
        raise _422("Unknown kind of fact")
    if body.lo is not None and body.hi is not None and body.lo > body.hi:
        raise _422("The lower figure is above the upper one")


@router.post("/tds/docs/{did}/facts", status_code=status.HTTP_201_CREATED)
def add_facts(
    did: int,
    body: list[FactIn],
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: TdsImportPerm,
) -> dict:
    """Facts typed by a person (a scanned sheet), or the AI's proposals a person confirmed."""
    d = db.get(TdsDoc, did)
    if d is None:
        raise _404("Data sheet")
    now = datetime.now(UTC)
    for b in body:
        _fact_ok(b)
        db.add(TdsFact(doc_id=d.id, product_id=d.product_id if d.status == "saved" else None, kind=b.kind, key=b.key, lo=b.lo, hi=b.hi if b.hi is not None else b.lo,
                       unit=b.unit, text=b.text, standard=b.standard, page=b.page, sentence=b.sentence, per_coat=b.per_coat, coats=b.coats,
                       source="ai" if b.source == "ai" else "manual", checked_by=principal.user.id, checked_at=now))  # fmt: skip
    if body:
        d.needs_reading = False
    record(db, request, principal, "tds.facts", "tds_doc", d.id, after={"added": len(body)})
    db.commit()
    return _j(_doc_out(db, d, with_facts=True))


@router.patch("/tds/facts/{fid}")
def edit_fact(
    fid: int,
    body: FactIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: TdsImportPerm,
) -> dict:
    """An edited fact is "checked by" who and when; the value as read is kept beside it."""
    f = db.get(TdsFact, fid)
    if f is None:
        raise _404("Fact")
    _fact_ok(body)
    if f.original is None:
        f.original = _j(suggest.fact_out(f))
    for k in (
        "kind",
        "key",
        "lo",
        "hi",
        "unit",
        "text",
        "standard",
        "page",
        "sentence",
        "per_coat",
        "coats",
    ):
        setattr(f, k, getattr(body, k))
    f.checked_by, f.checked_at = principal.user.id, datetime.now(UTC)
    record(
        db,
        request,
        principal,
        "tds.fact",
        "tds_fact",
        f.id,
        before=f.original,
        after=_j(body.model_dump()),
    )
    db.commit()
    return _j(
        suggest.fact_out(f) | {"original": f.original, "checked_by_name": _who(db, f.checked_by)}
    )


@router.delete("/tds/facts/{fid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_fact(
    fid: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: TdsImportPerm
) -> None:
    f = db.get(TdsFact, fid)
    if f is None:
        raise _404("Fact")
    record(
        db, request, principal, "tds.fact_delete", "tds_fact", f.id, before=_j(suggest.fact_out(f))
    )
    db.delete(f)
    db.commit()


@router.post("/tds/docs/{did}/ai-read")
def ai_read(did: int, db: DbSession, principal: CurrentPrincipal, _: TdsImportPerm) -> dict:
    """The AI reads a scanned sheet's pages: its facts come back for a person to confirm; nothing
    is saved here."""
    if not ai.enabled():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Reading with AI is off (HELPER_AI_ENABLED and the API key)"
        )
    d = db.get(TdsDoc, did)
    if d is None or not d.stored_path:
        raise _404("Data sheet")
    try:
        found = ai.read_sheet(tds_import.media(d.stored_path).read_bytes(), d.product_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The AI could not read it: {exc}"
        ) from None
    return _j({"proposed": found})


# --- the consumption master ----------------------------------------------------------------------


@router.get("/vocab")
def vocab_out(_: View) -> dict:
    return {"types": [{"key": k, "label": label} for k, label, _p in vocab.TYPES],
            "areas": [{"key": k, "label": vocab.USE_LABEL.get(k, k)} for k, _p in vocab.USES],
            "properties": [{"key": k, "label": label, "unit": u} for k, label, u, _p in vocab.PROPERTIES]}  # fmt: skip


@router.get("/master")
def master_list(
    db: DbSession, principal: CurrentPrincipal, _: View, q: str = "", area: str | None = None
) -> dict:
    return _j({"items": master.items(db, q, area, with_cost=False), "can_edit": principal.permissions.get("consumption.edit") is not None,
               "can_cost": _cost(principal)})  # fmt: skip


def _system(db, sid: int) -> System:
    s = db.get(System, sid)
    if s is None:
        raise _404("Work item")
    return s


@router.get("/master/{sid}")
def master_item(sid: int, db: DbSession, principal: CurrentPrincipal, _: View) -> dict:
    _system(db, sid)
    item = master.items(db, system_id=sid, with_cost=_cost(principal))[0]
    hist = [{"id": h.id, "what": h.what, "field": h.field, "old": h.old, "new": h.new, "reason": h.reason, "at": h.changed_at, "by": _who(db, h.changed_by)}
            for h in master.history(db, sid)]  # fmt: skip
    from app.estimate.models import MixDesign  # noqa: PLC0415

    mixes = [
        {"id": m.id, "code": m.code, "name": m.name, "thickness_mm": m.thickness_mm}
        for m in db.scalars(select(MixDesign).order_by(MixDesign.code))
    ]
    return _j(
        item
        | {
            "history": hist,
            "mix_designs": mixes,
            "can_edit": principal.permissions.get("consumption.edit") is not None,
            "can_cost": _cost(principal),
        }
    )


def _guard(fn, *args):
    try:
        return fn(*args)
    except master.MasterError as exc:
        raise _422(str(exc)) from None


class ItemIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    unit: str = "sqm"
    area_keys: list[str] = Field(default_factory=list)
    spec_type: str | None = None


@router.post("/master", status_code=status.HTTP_201_CREATED)
def master_add(
    body: ItemIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: MasterEdit
) -> dict:
    if body.unit not in ("sqm", "sqft", "rmt", "rft", "nos"):
        raise _422("A work item is per sqm, sq ft, rmt, rft or nos")
    s = _guard(
        master.add_item, db, body.name, body.unit, body.area_keys, body.spec_type, principal.user.id
    )
    record(
        db,
        request,
        principal,
        "consumption.item",
        "system",
        s.id,
        after={"name": s.name, "unit": s.unit},
    )
    db.commit()
    return {"id": s.id}


class ItemPatch(BaseModel):
    name: str | None = None
    area_keys: list[str] | None = None
    spec_type: str | None = None
    labour_rate: Decimal | None = None
    labour_unit: str | None = None
    default_margin_percent: Decimal | None = None
    is_active: bool | None = None
    reason: str | None = None


@router.patch("/master/{sid}")
def master_patch(
    sid: int,
    body: ItemPatch,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: MasterEdit,
) -> dict:
    s = _system(db, sid)
    data = body.model_dump(exclude_unset=True)
    reason = data.pop("reason", None)
    if {"labour_rate", "labour_unit", "default_margin_percent"} & set(data) and not _cost(
        principal
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Labour and margin are for those who see costs"
        )
    _guard(master.set_item, db, s, data, reason, principal.user.id)
    record(db, request, principal, "consumption.item", "system", s.id, after=_j(data))
    db.commit()
    return {"ok": True}


class OptionIn(BaseModel):
    brand: str = Field(min_length=1, max_length=100)


@router.post("/master/{sid}/options", status_code=status.HTTP_201_CREATED)
def master_option(
    sid: int,
    body: OptionIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: MasterEdit,
) -> dict:
    s = _system(db, sid)
    o = _guard(master.add_option, db, s, body.brand, principal.user.id)
    record(db, request, principal, "consumption.option", "system", s.id, after={"brand": o.brand})
    db.commit()
    return {"id": o.id}


class CopyIn(BaseModel):
    brand: str = Field(min_length=1, max_length=100)
    swaps: dict[int, int] = Field(
        default_factory=dict
    )  # product id -> the other brand's product id


@router.post("/master/{sid}/options/{oid}/copy", status_code=status.HTTP_201_CREATED)
def master_copy(
    sid: int,
    oid: int,
    body: CopyIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: MasterEdit,
) -> dict:
    s = _system(db, sid)
    o = _guard(master.copy_option, db, s, oid, body.brand, body.swaps, principal.user.id)
    record(
        db,
        request,
        principal,
        "consumption.copy",
        "system",
        s.id,
        after={"from": oid, "brand": o.brand, "swaps": body.swaps},
    )
    db.commit()
    return {"id": o.id}


class ComponentPatch(BaseModel):
    consumption_per_unit: Decimal | None = None
    wastage_percent: Decimal | None = None
    wastage_included: bool | None = None
    coats: int | None = None
    reason: str | None = None


def _component(s: System, cid: int) -> SystemComponent:
    c = next((x for x in s.components if x.id == cid), None)
    if c is None:
        raise _404("Product row")
    return c


@router.put("/master/{sid}/components/{cid}")
def master_component(
    sid: int,
    cid: int,
    body: ComponentPatch,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: MasterEdit,
) -> dict:
    s = _system(db, sid)
    c = _component(s, cid)
    data = body.model_dump(exclude_unset=True)
    reason = data.pop("reason", None)
    _guard(master.set_component, db, s, c, data, reason, principal.user.id)
    record(
        db,
        request,
        principal,
        "consumption.component",
        "system_component",
        c.id,
        after=_j(data | {"reason": reason}),
    )
    db.commit()
    return {"ok": True}


class ComponentIn(BaseModel):
    option_id: int | None = None
    product_id: int
    consumption_per_unit: Decimal | None = None
    coats: int | None = None
    wastage_percent: Decimal | None = None


@router.post("/master/{sid}/components", status_code=status.HTTP_201_CREATED)
def master_add_component(
    sid: int,
    body: ComponentIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: MasterEdit,
) -> dict:
    s = _system(db, sid)
    c = _guard(
        master.add_component,
        db,
        s,
        body.option_id,
        body.product_id,
        body.consumption_per_unit,
        body.coats,
        body.wastage_percent,
        principal.user.id,
    )
    record(
        db,
        request,
        principal,
        "consumption.component",
        "system_component",
        c.id,
        after=_j(body.model_dump()),
    )
    db.commit()
    return {"id": c.id}


@router.delete("/master/{sid}/components/{cid}", status_code=status.HTTP_204_NO_CONTENT)
def master_remove_component(
    sid: int,
    cid: int,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: MasterEdit,
    reason: str = "",
) -> None:
    s = _system(db, sid)
    c = _component(s, cid)
    record(
        db,
        request,
        principal,
        "consumption.component_delete",
        "system_component",
        c.id,
        after={"reason": reason},
    )
    _guard(master.remove_component, db, s, c, reason, principal.user.id)
    db.commit()


class MixIn(BaseModel):
    mix_design_id: int | None = None
    thickness_mm: Decimal | None = None


@router.put("/master/{sid}/options/{oid}/mix")
def master_mix(
    sid: int,
    oid: int,
    body: MixIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: MasterEdit,
) -> dict:
    s = _system(db, sid)
    _guard(master.attach_mix, db, s, oid, body.mix_design_id, body.thickness_mm, principal.user.id)
    record(db, request, principal, "consumption.mix", "system", s.id, after=_j(body.model_dump()))
    db.commit()
    return {"ok": True}


class PriceIn(BaseModel):
    rate: Decimal = Field(gt=0)
    unit: str | None = None  # per pack (bag, pail) or blank: per the product's unit; converted once
    note: str | None = Field(default=None, max_length=300)


@router.post("/master/products/{pid}/price", status_code=status.HTTP_201_CREATED)
def master_price(
    pid: int,
    body: PriceIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: MasterEdit,
) -> dict:
    """ "Update rate": a price row in the master price list (Prompt 38 rules)."""
    if not _cost(principal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Prices are for those who see costs")
    if db.get(Product, pid) is None:
        raise _404("Product")
    try:
        p = prices.record_price(db, pid, body.rate, source="manual", user_id=principal.user.id, unit=body.unit,
                                note=body.note or "Consumption master", ref="Consumption master", return_existing=True)  # fmt: skip
    except prices.UnitNotConvertible as exc:
        raise _422(str(exc)) from None
    record(
        db,
        request,
        principal,
        "consumption.price",
        "product",
        pid,
        after={"rate": str(body.rate), "unit": body.unit},
    )
    db.commit()
    return _j(prices.price_out(db, p))


# --- a BOQ line's key points, its options, the pick ----------------------------------------------


def _line(db, kind: str, line_id: int, principal, edit: bool = False):
    if kind not in ("boq", "quotation"):
        raise _404("Line")
    line = suggest.line_of(db, kind, line_id)
    if line is None:
        raise _404("Line")
    if kind == "boq":
        from app.tenders.service import get_visible  # noqa: PLC0415

        scope = principal.permissions.get("tender.view")
        if scope is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to tenders")
        get_visible(db, line.tender_id, scope, principal)
        if edit and principal.permissions.get("tender.edit") is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Tender editing is not for your role")
    else:
        from app.quotations import service as qsvc  # noqa: PLC0415
        from app.quotations.models import QuotationItem  # noqa: PLC0415

        scope = principal.permissions.get("quotation.view")
        if scope is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to quotations")
        qsvc.get_visible(db, db.get(QuotationItem, line.item_id).quotation_id, scope, principal)
        if edit and principal.permissions.get("quotation.edit") is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Quotation editing is not for your role")
    return line


def _points_out(db, kind, line) -> dict:
    chips, kept = suggest.points(db, kind, line)
    picks = [
        {"rank": p.rank, "system_id": p.system_id, "option_id": p.option_id, "group_id": p.group_id}
        for p in suggest.picks_of(db, kind, line.id)
    ]
    return {"line_id": line.id, "kind": kind, "description": line.description, "unit": suggest.line_unit(line), "qty": line.qty,
            "chips": chips, "kept": kept, "picks": picks, "ai_enabled": ai.enabled()}  # fmt: skip


@router.get("/lines/{kind}/{line_id}/points")
def line_points(kind: str, line_id: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    line = _line(db, kind, line_id, principal)
    return _j(_points_out(db, kind, line))


class PointsIn(BaseModel):
    chips: list[dict[str, Any]]


def _store(db, kind, line, chips, user_id) -> SpecPoints:
    row = suggest.stored(db, kind, line.id)
    if row is None:
        row = SpecPoints(
            **({"boq_line_id": line.id} if kind == "boq" else {"quotation_line_id": line.id}),
            text_hash="",
            chips=[],
        )
        db.add(row)
    row.text_hash = keypoints.text_hash(line.description, suggest.line_unit(line))
    row.chips, row.updated_by, row.updated_at = chips, user_id, datetime.now(UTC)
    return row


@router.put("/lines/{kind}/{line_id}/points")
def save_points(
    kind: str,
    line_id: int,
    body: PointsIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> dict:
    """The chips as a person left them (edited, added, an AI chip confirmed or removed)."""
    line = _line(db, kind, line_id, principal, edit=True)
    for c in body.chips:
        if not isinstance(c.get("kind"), str) or not isinstance(c.get("label"), str):
            raise _422("Each key point needs a kind and its words")
        c.setdefault("value", {})
        c.setdefault("spans", [])
        c.setdefault("source", "user")
        c.setdefault("confirmed", True)
    _store(db, kind, line, body.chips, principal.user.id)
    record(
        db,
        request,
        principal,
        "spec.points",
        f"{kind}_line",
        line.id,
        after={"chips": len(body.chips)},
    )
    db.commit()
    return _j(_points_out(db, kind, line))


@router.post("/lines/{kind}/{line_id}/points/reset")
def reset_points(kind: str, line_id: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    """Back to what the rules read from the words."""
    line = _line(db, kind, line_id, principal, edit=True)
    row = suggest.stored(db, kind, line.id)
    if row is not None:
        db.delete(row)
    db.commit()
    return _j(_points_out(db, kind, line))


@router.post("/lines/{kind}/{line_id}/points/ai")
def ai_points(kind: str, line_id: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    """The AI adds what the rules missed: shown "suggested by AI" until a person confirms."""
    if not ai.enabled():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The AI pass is off (HELPER_AI_ENABLED and the API key)"
        )
    line = _line(db, kind, line_id, principal, edit=True)
    chips, _kept = suggest.points(db, kind, line)
    try:
        extra = ai.line_points(line.description, chips)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The AI could not read it: {exc}"
        ) from None
    _store(db, kind, line, chips + extra, principal.user.id)
    db.commit()
    return _j(_points_out(db, kind, line) | {"added": len(extra)})


@router.get("/lines/{kind}/{line_id}/options")
def line_options(kind: str, line_id: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    line = _line(db, kind, line_id, principal)
    chips, _kept = suggest.points(db, kind, line)
    return _j(
        suggest.suggest(db, chips, with_cost=_cost(principal)) | {"can_pick": _cost(principal)}
    )


class PickIn(BaseModel):
    system_id: int
    option_id: int | None = None
    rank: int = Field(default=1, ge=1, le=2)


@router.post("/lines/{kind}/{line_id}/pick")
def pick(
    kind: str,
    line_id: int,
    body: PickIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> dict:
    line = _line(db, kind, line_id, principal, edit=True)
    if not _cost(principal):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Picking builds the rate working: for the estimator and the director",
        )
    chips, _kept = suggest.points(db, kind, line)
    try:
        p = suggest.pick(
            db, kind, line, body.system_id, body.option_id, body.rank, chips, principal.user.id
        )
    except suggest.PickError as exc:
        db.rollback()
        raise _422(str(exc)) from None
    record(
        db,
        request,
        principal,
        "spec.pick",
        f"{kind}_line",
        line.id,
        after={"system_id": body.system_id, "option_id": body.option_id, "rank": body.rank},
    )
    db.commit()
    return _j(
        _points_out(db, kind, line)
        | {"pick_id": p.id, "sub_lines": suggest.sub_lines(db, kind, line)}
    )


@router.delete("/lines/{kind}/{line_id}/pick/{rank}")
def unpick(kind: str, line_id: int, rank: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    """The tick taken off (the rate working's main item stays: it is the working's to change)."""
    line = _line(db, kind, line_id, principal, edit=True)
    for p in suggest.picks_of(db, kind, line.id):
        if p.rank == rank:
            db.delete(p)
    db.commit()
    return _j(_points_out(db, kind, line))


@router.get("/lines/{kind}/{line_id}/sub-lines")
def sub_lines(kind: str, line_id: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    line = _line(db, kind, line_id, principal)
    out = suggest.sub_lines(db, kind, line)
    if out and not _cost(principal):
        out.pop("rate", None)
    return _j({"sub_lines": out})


class SubLineIn(BaseModel):
    consumption: Decimal | None = None  # blank: back to the calculated figure
    reason: str | None = Field(default=None, max_length=300)


@router.put("/lines/{kind}/{line_id}/sub-lines/{rgp_id}")
def set_sub_line(
    kind: str,
    line_id: int,
    rgp_id: int,
    body: SubLineIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
) -> dict:
    line = _line(db, kind, line_id, principal, edit=True)
    if not _cost(principal):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The rate working is for the estimator and the director"
        )
    p = db.get(RateGroupProduct, rgp_id)
    first = next((x for x in suggest.picks_of(db, kind, line.id) if x.rank == 1), None)
    if p is None or first is None or p.group_id != first.group_id:
        raise _404("Step")
    from app.costing.models import RateGroup, RateWorking  # noqa: PLC0415

    if db.get(RateWorking, db.get(RateGroup, p.group_id).working_id).locked:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This revision was submitted: its working is kept as it was"
        )
    if body.consumption is not None and body.consumption < 0:
        raise _422("A consumption cannot be below 0")
    suggest.set_sub_line(db, rgp_id, body.consumption, body.reason)
    record(
        db,
        request,
        principal,
        "spec.sub_line",
        "rate_group_product",
        rgp_id,
        after=_j(body.model_dump()),
    )
    db.commit()
    return _j({"sub_lines": suggest.sub_lines(db, kind, line)})
