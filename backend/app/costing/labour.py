# ruff: noqa: E501  (the build-up rows and queries read better unwrapped)
"""Labour paid back to back with what we bill the client.

- Rate cards per labour contractor: job (coating covers surface preparation, cleaning, crack and
  joint treatment, the vata, primer and coat), unit, rate (₹10 per sq ft; plaster ₹15 to ₹18),
  valid from and to.
- A piece-rate bill takes its quantity from the measurement book: what was billed to the client
  for that item (or certified, when the client certified less), up to the bill's period, less what
  the contractor was already paid for it, times the rate. Nobody types a labour quantity.
- An attendance bill (a gang such as Laxmanbhai's): attendance records the site and hours each
  day, so the month's bill splits by site and each site's cost is right.
- TDS as in finance (the vendor's section and the year's thresholds); approval raises the vendor
  bill that payables pays.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import CurrentPrincipal, require_permission
from app.costing import prices
from app.costing.models import LABOUR_UNITS, LabourBill, LabourBillLine, LabourRateCard
from app.db import DbSession
from app.execution.common import names, record
from app.masters.models import Vendor
from app.masters.rate import SQFT_PER_SQM

router = APIRouter(prefix="/api/labour", tags=["labour rates"])
ZERO = Decimal(0)
CLIENT_BILLED = ("submitted", "certified_by_client", "certified", "invoiced")
DAY_FACTOR = {"present": Decimal(1), "half_day": Decimal("0.5"), "absent": ZERO}


def money(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q3(v) -> Decimal:
    return Decimal(v).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


# --- rate cards ----------------------------------------------------------------------------------


def card_in_force(db: Session, card_id: int, on: date) -> LabourRateCard:
    card = db.get(LabourRateCard, card_id)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Labour rate card not found")
    if card.valid_from > on or (card.valid_to and card.valid_to < on):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{card.job}: the rate is valid {card.valid_from:%d %b %Y} to "
            f"{card.valid_to:%d %b %Y}" if card.valid_to else f"{card.job}: valid from {card.valid_from:%d %b %Y}",
        )  # fmt: skip
    return card


def rate_in(card: LabourRateCard, unit: str) -> Decimal:
    """The card's rate in the client line's unit (₹ per sq ft × 10.7639 per sqm)."""
    cu, lu = card.unit, (unit or "").lower().replace("sft", "sqft")
    if cu == lu:
        return Decimal(card.rate)
    if cu == "sqft" and lu == "sqm":
        return Decimal(card.rate) * SQFT_PER_SQM
    if cu == "sqm" and lu == "sqft":
        return Decimal(card.rate) / SQFT_PER_SQM
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        f"{card.job} is per {card.unit}; the client's item is per {unit}",
    )


def card_out(db: Session, c: LabourRateCard) -> dict:
    v = db.get(Vendor, c.contractor_id)
    return {
        "id": c.id,
        "contractor_id": c.contractor_id,
        "contractor": v.name if v else None,
        "job": c.job,
        "covers": c.covers,
        "unit": c.unit,
        "rate": c.rate,
        "rate_max": c.rate_max,
        "valid_from": c.valid_from,
        "valid_to": c.valid_to,
        "in_force": c.valid_from <= date.today()
        and (c.valid_to is None or c.valid_to >= date.today()),
    }


SubconView = Annotated[str, Depends(require_permission("subcon.view"))]
SubconEdit = Annotated[str, Depends(require_permission("subcon.edit"))]
PayView = Annotated[str, Depends(require_permission("payables.view"))]
PayEdit = Annotated[str, Depends(require_permission("payables.edit"))]


@router.get("/rate-cards")
def rate_cards(db: DbSession, _: SubconView, contractor_id: int | None = None) -> list[dict]:
    q = select(LabourRateCard).order_by(
        LabourRateCard.contractor_id, LabourRateCard.job, LabourRateCard.valid_from.desc()
    )
    if contractor_id:
        q = q.where(LabourRateCard.contractor_id == contractor_id)
    return jsonable_encoder([card_out(db, c) for c in db.scalars(q)])


class CardIn(BaseModel):
    contractor_id: int
    job: str = Field(min_length=2, max_length=100)
    covers: str | None = None
    unit: str = Field("sqft", pattern="^(" + "|".join(LABOUR_UNITS) + ")$")
    rate: Decimal = Field(ge=0)
    rate_max: Decimal | None = Field(None, ge=0)
    valid_from: date
    valid_to: date | None = None


@router.post("/rate-cards", status_code=status.HTTP_201_CREATED)
def add_card(
    body: CardIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: SubconEdit
) -> dict:
    if db.get(Vendor, body.contractor_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown labour contractor")
    if body.rate_max is not None and body.rate_max < body.rate:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "The upper rate is below the rate"
        )
    if body.valid_to and body.valid_to < body.valid_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Valid to is before valid from")
    c = LabourRateCard(**body.model_dump(), created_by=principal.user.id)
    db.add(c)
    db.flush()
    record(
        db,
        request,
        principal,
        "labour_rate.create",
        "labour_rate_card",
        c.id,
        after=jsonable_encoder(body.model_dump()),
    )
    db.commit()
    return jsonable_encoder(card_out(db, c))


@router.put("/rate-cards/{cid}")
def update_card(
    cid: int,
    body: CardIn,
    request: Request,
    db: DbSession,
    principal: CurrentPrincipal,
    _: SubconEdit,
) -> dict:
    c = db.get(LabourRateCard, cid)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Labour rate card not found")
    before = jsonable_encoder(card_out(db, c))
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    record(
        db,
        request,
        principal,
        "labour_rate.update",
        "labour_rate_card",
        c.id,
        before=before,
        after=jsonable_encoder(body.model_dump()),
    )
    db.commit()
    return jsonable_encoder(card_out(db, c))


# --- piece rate: the quantity from the measurement book -------------------------------------------


def client_qty(
    db: Session, contract_line_id: int, upto: date, since: date | None = None
) -> tuple[Decimal, str]:
    """What the client was billed for the item in bills up to `upto`, or what they certified
    where that is less: (quantity, "certified" when a bill of the period was certified for less,
    else "billed")."""
    from app.finance.models import RaBill, RaBillLine  # noqa: PLC0415

    total, basis = ZERO, "billed"
    for ln in db.scalars(
        select(RaBillLine)
        .join(RaBill, RaBill.id == RaBillLine.ra_bill_id)
        .where(
            RaBillLine.contract_line_id == contract_line_id,
            RaBill.status.in_(CLIENT_BILLED),
            RaBill.period_to <= upto,
        )
    ):
        billed = Decimal(ln.qty)
        cert = ln.certified_qty if ln.certified_qty is not None else ln.client_qty
        if cert is not None and Decimal(cert) < billed:
            total += Decimal(cert)
            if since is None or ra_to(db, ln) >= since:
                basis = "certified"
        else:
            total += billed
    return total, basis


def ra_to(db: Session, ln) -> date:
    from app.finance.models import RaBill  # noqa: PLC0415

    return db.get(RaBill, ln.ra_bill_id).period_to


def paid_qty(
    db: Session, contract_line_id: int, contractor_id: int, exclude_bill: int | None = None
) -> Decimal:
    q = (
        select(func.coalesce(func.sum(LabourBillLine.qty), 0))
        .join(LabourBill, LabourBill.id == LabourBillLine.bill_id)
        .where(
            LabourBillLine.contract_line_id == contract_line_id,
            LabourBill.contractor_id == contractor_id,
            LabourBill.kind == "piece",
            LabourBill.status != "cancelled",
        )
    )
    if exclude_bill:
        q = q.where(LabourBill.id != exclude_bill)
    return Decimal(db.scalar(q))


def piece_lines(
    db: Session,
    site_id: int,
    contractor_id: int,
    upto: date,
    picks: list[dict],
    since: date | None = None,
) -> list[dict]:
    """For each picked item and job: the client's quantity to date less what was paid, × the
    rate (in the item's unit)."""
    from app.finance.models import ClientContract, ContractLine  # noqa: PLC0415

    out = []
    for pick in picks:
        cl = db.get(ContractLine, pick["contract_line_id"])
        contract = db.get(ClientContract, cl.contract_id) if cl else None
        if cl is None or contract is None or contract.site_id != site_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "That item is not on this site's contract"
            )
        card = card_in_force(db, pick["rate_card_id"], upto)
        if card.contractor_id != contractor_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"{card.job} is another contractor's rate"
            )
        done, basis = client_qty(db, cl.id, upto, since)
        qty = q3(max(ZERO, done - paid_qty(db, cl.id, contractor_id)))
        rate = rate_in(card, cl.unit).quantize(Decimal("0.0001"))
        out.append({
            "site_id": site_id, "contract_line_id": cl.id, "rate_card_id": card.id,
            "description": f"{cl.item_no or ''} {cl.description[:120]} · {card.job}".strip(),
            "basis": basis, "client_qty": q3(done), "qty": qty, "unit": cl.unit,
            "rate": rate, "amount": money(qty * rate),
        })  # fmt: skip
    return out


# --- attendance: a gang's hours per site ---------------------------------------------------------


def gang_lines(db: Session, contractor_id: int, start: date, end: date) -> list[dict]:
    """The gang's attendance in the period, by site: hours (the day's hours, else a day's
    standard hours by the status) and the wage for them, plus overtime."""
    from app.execution.models import Attendance, Labour  # noqa: PLC0415
    from app.sites.models import Site  # noqa: PLC0415

    day = Decimal(prices.settings(db).day_hours)
    by_site: dict[int, dict] = defaultdict(lambda: {"hours": ZERO, "amount": ZERO, "days": 0})
    for a in db.scalars(
        select(Attendance)
        .join(Labour, Labour.id == Attendance.labour_id)
        .where(
            Labour.subcontractor_id == contractor_id,
            Attendance.on_date >= start,
            Attendance.on_date <= end,
        )
    ):
        hours = Decimal(a.hours) if a.hours is not None else DAY_FACTOR[a.status] * day
        if hours <= 0 and not a.ot_hours:
            continue
        s = by_site[a.site_id]
        s["hours"] += hours + Decimal(a.ot_hours or 0)
        s["amount"] += hours / day * Decimal(a.daily_wage) + Decimal(a.ot_hours or 0) * Decimal(
            a.ot_rate_per_hour
        )
        s["days"] += 1
    # the supervisor's gang check-ins: each person's hours on each site (a worker with a muster
    # roll entry that day is counted there, not twice); a headcount without names at the gang's
    # average wage
    from app.field.service import gang_hours  # noqa: PLC0415

    marked = set(db.execute(select(Attendance.labour_id, Attendance.on_date).join(Labour, Labour.id == Attendance.labour_id)
                            .where(Labour.subcontractor_id == contractor_id, Attendance.on_date >= start, Attendance.on_date <= end)).all())  # fmt: skip
    gang = {
        w.id: w for w in db.scalars(select(Labour).where(Labour.subcontractor_id == contractor_id))
    }
    wages = [Decimal(w.daily_wage) for w in gang.values() if w.daily_wage]
    average = sum(wages, ZERO) / len(wages) if wages else ZERO
    worker_days: set = set()
    for (site_id, labour_id, on), hours in gang_hours(db, contractor_id, start, end).items():
        if labour_id is not None and (labour_id, on) in marked:
            continue
        s = by_site[site_id]
        wage = Decimal(gang[labour_id].daily_wage) if labour_id in gang else average
        s["hours"] += hours
        s["amount"] += hours / day * wage
        if (site_id, labour_id, on) not in worker_days:
            worker_days.add((site_id, labour_id, on))
            s["days"] += 1
    out = []
    for site_id, s in sorted(by_site.items()):
        site = db.get(Site, site_id)
        amount = money(s["amount"])
        out.append({
            "site_id": site_id, "contract_line_id": None, "rate_card_id": None,
            "description": f"{site.code} {site.name}: {s['days']} worker-days",
            "basis": "hours", "qty": q3(s["hours"]), "unit": "hour",
            "rate": (amount / s["hours"]).quantize(Decimal("0.0001")) if s["hours"] else ZERO,
            "amount": amount,
        })  # fmt: skip
    return out


# --- the bills -----------------------------------------------------------------------------------


def _number(db: Session, on: date) -> str:
    fy = on.year if on.month >= 4 else on.year - 1
    prefix = f"LB/{fy % 100:02d}-{(fy + 1) % 100:02d}/"
    n = db.scalar(
        select(func.count()).select_from(LabourBill).where(LabourBill.number.like(f"{prefix}%"))
    )
    return f"{prefix}{n + 1:04d}"


def make_bill(
    db: Session,
    kind: str,
    contractor: Vendor,
    start: date,
    end: date,
    on: date,
    rows: list[dict],
    user_id,
    remark=None,
) -> LabourBill:
    from app.finance import service as fsvc  # noqa: PLC0415

    rows = [r for r in rows if Decimal(r["qty"]) > 0]
    if not rows:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to bill in this period")
    b = LabourBill(
        number=_number(db, on), kind=kind, contractor_id=contractor.id, period_from=start,
        period_to=end, bill_date=on, remark=remark, created_by=user_id,
    )  # fmt: skip
    b.lines = [
        LabourBillLine(**{k: r[k] for k in ("site_id", "contract_line_id", "rate_card_id", "description", "basis", "qty", "unit", "rate", "amount")})
        for r in rows
    ]  # fmt: skip
    b.gross = money(sum((Decimal(r["amount"]) for r in rows), ZERO))
    b.tds_section, b.tds_percent, b.tds, b.tds_note = fsvc.tds_on_bill(db, contractor, b.gross, on)
    b.net = b.gross - b.tds
    db.add(b)
    db.flush()
    return b


def bill_out(db: Session, b: LabourBill) -> dict:
    from app.sites.models import Site  # noqa: PLC0415

    v = db.get(Vendor, b.contractor_id)
    who = names(db, [b.created_by, b.approved_by])
    return {
        "id": b.id, "number": b.number, "kind": b.kind, "contractor_id": b.contractor_id,
        "contractor": v.name if v else None, "period_from": b.period_from, "period_to": b.period_to,
        "bill_date": b.bill_date, "gross": b.gross, "tds_section": b.tds_section,
        "tds_percent": b.tds_percent, "tds": b.tds, "tds_note": b.tds_note, "net": b.net,
        "status": b.status, "made_by": who.get(b.created_by), "approved_by": who.get(b.approved_by),
        "remark": b.remark,
        "lines": [
            {"id": ln.id, "site_id": ln.site_id, "site": db.get(Site, ln.site_id).code,
             "contract_line_id": ln.contract_line_id, "rate_card_id": ln.rate_card_id,
             "description": ln.description, "basis": ln.basis, "qty": ln.qty, "unit": ln.unit,
             "rate": ln.rate, "amount": ln.amount}
            for ln in b.lines
        ],
    }  # fmt: skip


@router.get("/bills")
def bills(
    db: DbSession, _: PayView, contractor_id: int | None = None, site_id: int | None = None
) -> list[dict]:
    q = select(LabourBill).order_by(LabourBill.bill_date.desc(), LabourBill.id.desc())
    if contractor_id:
        q = q.where(LabourBill.contractor_id == contractor_id)
    if site_id:
        q = q.where(
            LabourBill.id.in_(
                select(LabourBillLine.bill_id).where(LabourBillLine.site_id == site_id)
            )
        )
    return jsonable_encoder([bill_out(db, b) for b in db.scalars(q.limit(200))])


@router.get("/bills/{bid}")
def get_bill(bid: int, db: DbSession, _: PayView) -> dict:
    b = db.get(LabourBill, bid)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    return jsonable_encoder(bill_out(db, b))


class Pick(BaseModel):
    contract_line_id: int
    rate_card_id: int


class PieceIn(BaseModel):
    contractor_id: int
    site_id: int
    period_from: date
    period_to: date
    bill_date: date | None = None
    lines: list[Pick] = Field(min_length=1)
    remark: str | None = None


@router.post("/bills/piece/preview")
def piece_preview(body: PieceIn, db: DbSession, _: PayView) -> dict:
    """What the bill would be: per item, the client's quantity to date, what was paid, the rate."""
    rows = piece_lines(
        db,
        body.site_id,
        body.contractor_id,
        body.period_to,
        [p.model_dump() for p in body.lines],
        body.period_from,
    )
    return jsonable_encoder({"lines": rows, "gross": money(sum((r["amount"] for r in rows), ZERO))})


@router.post("/bills/piece", status_code=status.HTTP_201_CREATED)
def piece_bill(
    body: PieceIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayEdit
) -> dict:
    contractor = db.get(Vendor, body.contractor_id)
    if contractor is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown labour contractor")
    if body.period_to < body.period_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "The period ends before it starts"
        )
    rows = piece_lines(
        db,
        body.site_id,
        body.contractor_id,
        body.period_to,
        [p.model_dump() for p in body.lines],
        body.period_from,
    )
    b = make_bill(
        db,
        "piece",
        contractor,
        body.period_from,
        body.period_to,
        body.bill_date or date.today(),
        rows,
        principal.user.id,
        body.remark,
    )
    record(
        db,
        request,
        principal,
        "labour_bill.create",
        "labour_bill",
        b.id,
        after={"number": b.number, "kind": "piece", "gross": str(b.gross)},
    )
    db.commit()
    return jsonable_encoder(bill_out(db, b))


class AttendanceIn(BaseModel):
    contractor_id: int
    month: date  # any day of the month
    bill_date: date | None = None
    remark: str | None = None


@router.post("/bills/attendance", status_code=status.HTTP_201_CREATED)
def attendance_bill(
    body: AttendanceIn, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayEdit
) -> dict:
    """The gang's month from attendance, one line per site."""
    contractor = db.get(Vendor, body.contractor_id)
    if contractor is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown labour contractor")
    start = body.month.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    clash = db.scalar(
        select(LabourBill.number).where(
            LabourBill.contractor_id == contractor.id, LabourBill.kind == "attendance",
            LabourBill.status != "cancelled", LabourBill.period_from <= end, LabourBill.period_to >= start,
        )
    )  # fmt: skip
    if clash:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{clash} already bills this month")
    rows = gang_lines(db, contractor.id, start, end)
    b = make_bill(
        db,
        "attendance",
        contractor,
        start,
        end,
        body.bill_date or min(end, date.today()),
        rows,
        principal.user.id,
        body.remark,
    )
    record(
        db,
        request,
        principal,
        "labour_bill.create",
        "labour_bill",
        b.id,
        after={"number": b.number, "kind": "attendance", "gross": str(b.gross)},
    )
    db.commit()
    return jsonable_encoder(bill_out(db, b))


@router.post("/bills/{bid}/approve")
def approve(
    bid: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayEdit
) -> dict:
    """Approved: a vendor bill (kind subcontract) for the net, paid like any bill; each site's
    line counts in that site's labour cost."""
    from app.finance import service as fsvc  # noqa: PLC0415
    from app.finance.models import VendorBill, VendorBillLine  # noqa: PLC0415
    from app.finance.payables import _bill_tax, is_interstate  # noqa: PLC0415

    b = db.get(LabourBill, bid)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    if b.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{b.number} is {b.status}")
    v = db.get(Vendor, b.contractor_id)
    sites = {ln.site_id for ln in b.lines}
    vb = VendorBill(
        number=fsvc.next_number(db, "VB", b.bill_date), kind="subcontract", vendor_id=v.id, vendor=v,
        bill_no=b.number, bill_date=b.bill_date,
        due_date=b.bill_date + timedelta(days=v.payment_terms_days or 15),
        site_id=next(iter(sites)) if len(sites) == 1 else None,
        interstate=is_interstate(v, fsvc.our_gstin(db, None)), itc_eligible=False,
        tds_section=b.tds_section, tds_percent=b.tds_percent, status="approved",
        approved_by=principal.user.id, approved_at=fsvc.now(),
        remark=f"Labour bill {b.number} ({b.kind})", created_by=principal.user.id,
    )  # fmt: skip
    vb.lines = [
        VendorBillLine(
            description=ln.description[:200], qty=1, rate=ln.amount, amount=ln.amount, gst_percent=0
        )
        for ln in b.lines
    ]
    _bill_tax(db, vb)
    vb.tds_amount = b.tds
    vb.payable = b.net
    db.add(vb)
    db.flush()
    b.status, b.vendor_bill_id = "approved", vb.id
    b.approved_by, b.approved_at = principal.user.id, fsvc.now()
    record(
        db,
        request,
        principal,
        "labour_bill.approve",
        "labour_bill",
        b.id,
        after={"vendor_bill": vb.number},
    )
    db.commit()
    return jsonable_encoder(bill_out(db, b))


@router.post("/bills/{bid}/cancel")
def cancel(
    bid: int, request: Request, db: DbSession, principal: CurrentPrincipal, _: PayEdit
) -> dict:
    b = db.get(LabourBill, bid)
    if b is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Bill not found")
    if b.status != "draft":
        raise HTTPException(status.HTTP_409_CONFLICT, f"{b.number} is {b.status}")
    b.status = "cancelled"
    record(db, request, principal, "labour_bill.cancel", "labour_bill", b.id)
    db.commit()
    return jsonable_encoder(bill_out(db, b))


# --- labour cost per sqm per site, against the rate working's labour line -----------------------


def site_labour(db: Session, site_id: int) -> dict:
    """Labour paid on the site (approved labour bills' lines on it, own labour's wages,
    subcontract measurements) per sqm billed to the client, against the labour the rate working
    priced (₹ per sq ft × 10.7639, weighted by the billed area of each main item)."""
    from app.costing.models import RateGroup, RateGroupLine, RateWorking  # noqa: PLC0415
    from app.execution import service as ex  # noqa: PLC0415
    from app.finance.models import ClientContract, ContractLine, RaBill, RaBillLine  # noqa: PLC0415
    from app.sites.models import Site  # noqa: PLC0415

    site = db.get(Site, site_id)
    actual = ex.actuals(db, site_id)
    labour_cost = Decimal(actual.get("labour", ZERO)) + Decimal(actual.get("subcontract", ZERO))
    contract = db.scalar(select(ClientContract).where(ClientContract.site_id == site_id))
    area = ZERO
    per_line: dict[int, Decimal] = {}
    if contract:
        for cl in db.scalars(select(ContractLine).where(ContractLine.contract_id == contract.id)):
            unit = (cl.unit or "").lower()
            if unit not in ("sqm", "sqft", "sft"):
                continue
            billed = Decimal(
                db.scalar(
                    select(func.coalesce(func.sum(RaBillLine.qty), 0))
                    .join(RaBill, RaBill.id == RaBillLine.ra_bill_id)
                    .where(RaBillLine.contract_line_id == cl.id, RaBill.status.in_(CLIENT_BILLED))
                )
            )
            sqm = billed if unit == "sqm" else billed / SQFT_PER_SQM
            area += sqm
            if cl.boq_line_id:
                per_line[cl.boq_line_id] = per_line.get(cl.boq_line_id, ZERO) + sqm
    planned = None
    if site and site.tender_id and per_line:
        w = db.scalar(
            select(RateWorking)
            .where(RateWorking.tender_id == site.tender_id)
            .order_by(RateWorking.rev_no.desc())
            .limit(1)
        )
        if w is not None:
            num = den = ZERO
            for g, gl in db.execute(
                select(RateGroup, RateGroupLine)
                .join(RateGroupLine, RateGroupLine.group_id == RateGroup.id)
                .where(RateGroup.working_id == w.id)
            ).all():
                sqm = per_line.get(gl.boq_line_id or -1, ZERO)
                num += sqm * Decimal(g.labour_used_sqft or 0) * SQFT_PER_SQM
                den += sqm
            planned = money(num / den) if den else None
    per_sqm = money(labour_cost / area) if area else None
    return {
        "labour_cost": money(labour_cost),
        "area_sqm": q3(area),
        "per_sqm": per_sqm,
        "working_per_sqm": planned,
        "over": per_sqm is not None and planned is not None and per_sqm > planned,
    }


@router.get("/sites/{site_id}/labour-cost")
def labour_cost(site_id: int, db: DbSession, principal: CurrentPrincipal) -> dict:
    """Labour cost per sqm on the site against the rate working's labour line (cost data)."""
    from app.sites import service as site_service  # noqa: PLC0415

    if principal.permissions.get("tender.margin") is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Labour cost is cost data")
    scope = principal.permissions.get("site.view")
    if scope is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to sites")
    site_service.get_visible(db, site_id, scope, principal)
    return jsonable_encoder(site_labour(db, site_id))


def bill_lines_cost(db: Session, site_id: int) -> Decimal:
    """Approved labour bills' lines on the site (for the site's labour head)."""
    return Decimal(
        db.scalar(
            select(func.coalesce(func.sum(LabourBillLine.amount), 0))
            .join(LabourBill, LabourBill.id == LabourBillLine.bill_id)
            .where(LabourBillLine.site_id == site_id, LabourBill.status == "approved")
        )
    )
