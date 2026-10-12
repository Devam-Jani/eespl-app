# ruff: noqa: E501  (user-facing sentences read better unwrapped)
"""Site control logic: rate contracts, the three-way match on vendor bills, "ready to bill" when
a stage is done, new-area requests, the labour productivity check, consumption variance."""

import statistics
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.execution.models import Attendance, DprLine, Labour, WoLine, WoMeasurement, WorkOrder
from app.finance.models import (
    ClientContract,
    ContractLine,
    SubconBill,
    SubconBillLine,
    VendorBill,
    VendorBillLine,
)
from app.masters.models import Product, System, SystemComponent
from app.material.models import Grn, GrnLine, PoLine, PurchaseOrder, SiteIssue, SiteIssueLine
from app.sitecontrol.deliveries import settings
from app.sitecontrol.models import (
    DeliveryNote,
    NewAreaRequest,
    ProductivityNorm,
    RateContract,
    RateContractVersion,
    ReadyToBill,
)
from app.sites.models import AreaScope, Site, SiteNode
from app.tenders.models import BoqLine

ZERO = Decimal(0)
SQFT_PER_SQM = Decimal("10.7639")


def now() -> datetime:
    return datetime.now(UTC)


def pct(a: Decimal, b: Decimal) -> Decimal:
    return ((a - b) / b * 100).quantize(Decimal("0.1")) if b else ZERO


# --- rate contracts ------------------------------------------------------------------------------


def active_contract(db: Session, vendor_id: int, product_id: int, on: date) -> RateContract | None:
    return db.scalar(
        select(RateContract).where(
            RateContract.vendor_id == vendor_id,
            RateContract.product_id == product_id,
            RateContract.is_active,
            RateContract.valid_from <= on,
            RateContract.valid_till >= on,
        )
    )


def check_overlap(db: Session, c: RateContract) -> None:
    """One active contract per vendor and product on any date."""
    clash = db.scalar(
        select(RateContract).where(
            RateContract.vendor_id == c.vendor_id,
            RateContract.product_id == c.product_id,
            RateContract.is_active,
            RateContract.id != (c.id or -1),
            RateContract.valid_from <= c.valid_till,
            RateContract.valid_till >= c.valid_from,
        )
    )
    if clash is not None and c.is_active is not False:  # unset (new) means active
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Another contract for this vendor and product runs {clash.valid_from:%d %b %Y} – {clash.valid_till:%d %b %Y}: end it first",
        )


def contract_snapshot(c: RateContract) -> dict[str, Any]:
    return {
        k: (str(v) if isinstance(v, Decimal | date) else v)
        for k, v in (
            ("vendor_id", c.vendor_id),
            ("product_id", c.product_id),
            ("rate", c.rate),
            ("freight_terms", c.freight_terms),
            ("valid_from", c.valid_from),
            ("valid_till", c.valid_till),
            ("agreed_by", c.agreed_by),
            ("notes", c.notes),
            ("attachment_path", c.attachment_path),
            ("is_active", c.is_active),
        )
    }


def save_contract_version(db: Session, c: RateContract, user_id) -> None:
    db.flush()
    last = (
        db.scalar(
            select(func.max(RateContractVersion.version)).where(
                RateContractVersion.contract_id == c.id
            )
        )
        or 0
    )
    c.version = last + 1
    db.add(
        RateContractVersion(
            contract_id=c.id, version=c.version, data=contract_snapshot(c), created_by=user_id
        )
    )


def po_line_rate(
    db: Session,
    vendor_id: int,
    product: Product,
    unit: str,
    qty: Decimal,
    base_qty: Decimal,
    rate: Decimal | None,
    reason: str | None,
    on: date,
):
    """The PO line's rate against the vendor's contract: none given (or 0) -> the contract rate;
    above it -> needs a reason. Returns (rate, contract, contract rate per this unit)."""
    c = active_contract(db, vendor_id, product.id, on)
    if c is None:
        if rate is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{product.name}: enter the rate (no rate contract with this vendor)",
            )
        return rate, None, None
    per_unit = (
        (Decimal(c.rate) * Decimal(base_qty) / Decimal(qty)).quantize(Decimal("0.0001"))
        if qty
        else Decimal(c.rate)
    )
    if rate is None or rate == 0:
        return per_unit.quantize(Decimal("0.01")), c, per_unit
    if rate > per_unit * Decimal("1.0005") and not (reason or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{product.name}: above agreed rate by {pct(Decimal(rate), per_unit)}% (contract ₹{per_unit.quantize(Decimal('0.01'))} per {unit}): give the reason",
        )
    return rate, c, per_unit


# --- three-way match -----------------------------------------------------------------------------


def block_reasons(db: Session, bill: VendorBill) -> list[dict[str, Any]]:
    """A bill line for a PO is checked against the PO rate (and the rate contract) and the
    quantity confirmed received (accepted on posted GRNs, which follow the site's count).
    Any difference blocks the bill from "approved for payment"."""
    out: list[dict[str, Any]] = []
    lines = db.scalars(select(VendorBillLine).where(VendorBillLine.vendor_bill_id == bill.id)).all()
    for bl in lines:
        if not bl.po_line_id:
            continue
        pl = db.get(PoLine, bl.po_line_id)
        if pl is None:
            continue
        product = db.get(Product, pl.product_id)
        received = db.scalar(
            select(func.coalesce(func.sum(GrnLine.accepted_qty), 0))
            .join(Grn, Grn.id == GrnLine.grn_id)
            .where(GrnLine.po_line_id == pl.id, Grn.status == "approved")
        )
        billed = db.scalar(
            select(func.coalesce(func.sum(VendorBillLine.qty), 0))
            .join(VendorBill, VendorBill.id == VendorBillLine.vendor_bill_id)
            .where(VendorBillLine.po_line_id == pl.id, VendorBill.status != "cancelled")
        )
        if Decimal(billed) > Decimal(received) + Decimal("0.001"):
            open_dn = db.scalar(
                select(DeliveryNote.code)
                .where(DeliveryNote.po_id == pl.po_id, DeliveryNote.confirmed_at.is_(None))
                .limit(1)
            )
            out.append(
                {
                    "kind": "qty",
                    "line": product.name,
                    "message": f"{product.name}: billed {Decimal(billed):f} {pl.unit}, confirmed received {Decimal(received):f}"
                    + (f" ({open_dn} not confirmed at site)" if open_dn else ""),
                }
            )
        po_rate = (
            (Decimal(pl.amount) / Decimal(pl.qty)).quantize(Decimal("0.01"))
            if Decimal(pl.qty)
            else ZERO
        )
        if Decimal(bl.rate) > po_rate * Decimal("1.005"):
            out.append(
                {
                    "kind": "rate",
                    "line": product.name,
                    "message": f"{product.name}: bill rate ₹{Decimal(bl.rate):f} above the PO rate ₹{po_rate}",
                }
            )
        c = active_contract(db, bill.vendor_id, product.id, bill.bill_date)
        if c is not None:
            per_unit = (
                (Decimal(c.rate) * Decimal(pl.base_qty) / Decimal(pl.qty)).quantize(Decimal("0.01"))
                if Decimal(pl.qty)
                else Decimal(c.rate)
            )
            if Decimal(bl.rate) > per_unit * Decimal("1.005"):
                out.append(
                    {
                        "kind": "contract",
                        "line": product.name,
                        "message": f"{product.name}: bill rate ₹{Decimal(bl.rate):f} above the agreed rate ₹{per_unit} (rate contract)",
                    }
                )
    return out


def refresh_block(db: Session, bill: VendorBill) -> list[dict[str, Any]]:
    db.flush()
    bill.blocked_reasons = block_reasons(db, bill)
    return bill.blocked_reasons


def approval_gate(db: Session, bill: VendorBill) -> None:
    """Called before "approved for payment": blocked bills need a release first."""
    reasons = refresh_block(db, bill)
    if reasons and bill.released_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Blocked by the three-way match: "
            + "; ".join(r["message"] for r in reasons)
            + ". Accounts can release it with a reason (delivery.escalate).",
        )


# --- stage done, bill it -------------------------------------------------------------------------


def on_scope_refresh(db: Session, scope: AreaScope, before: Decimal) -> ReadyToBill | None:
    """The stage's last task done (progress reached 100 %): a "ready to bill" item with the
    measured quantity, the survey's figure for the place and the contract line it maps to."""
    if Decimal(scope.progress_percent) < 100 or Decimal(before or 0) >= 100:
        return None
    if db.scalar(
        select(ReadyToBill.id).where(
            ReadyToBill.area_scope_id == scope.id, ReadyToBill.status != "dismissed"
        )
    ):
        return None
    contract = db.scalar(select(ClientContract).where(ClientContract.site_id == scope.site_id))
    cl = None
    if contract and scope.boq_line_id:
        cl = db.scalar(
            select(ContractLine).where(
                ContractLine.contract_id == contract.id,
                ContractLine.boq_line_id == scope.boq_line_id,
            )
        )
    survey_qty, camera_only = _survey_figure(db, scope)
    note = None
    if camera_only:
        note = "Camera-measured sizes: billable only with the camera billing setting or the client's certification"
    item = ReadyToBill(
        site_id=scope.site_id,
        node_id=scope.node_id,
        area_scope_id=scope.id,
        stage_template_id=scope.stage_template_id,
        boq_line_id=scope.boq_line_id,
        contract_line_id=cl.id if cl else None,
        qty=scope.qty,
        unit=scope.unit,
        survey_qty=survey_qty,
        camera_only=camera_only,
        note=note if cl else (note or "No contract line maps to this BOQ line yet"),
    )
    db.add(item)
    db.flush()
    from app.team.service import book_from_ready  # noqa: PLC0415

    book_from_ready(db, item)  # the measurement book: what RA bills take their quantities from
    return item


def _survey_figure(db: Session, scope: AreaScope) -> tuple[Decimal | None, bool]:
    """Treated sqm of the approved survey areas on the place (camera-only per the M6b setting)."""
    from app.survey import service as survey  # noqa: PLC0415
    from app.survey.models import CAMERA_METHODS, Survey, SurveyArea  # noqa: PLC0415

    areas = db.scalars(
        select(SurveyArea)
        .join(Survey, Survey.id == SurveyArea.survey_id)
        .where(SurveyArea.node_id == scope.node_id, Survey.status == "approved")
    ).all()
    if not areas:
        return None, False
    allowed = survey.settings(db).camera_billing_allowed
    camera = any(a.method in CAMERA_METHODS for a in areas) and not allowed
    return sum((Decimal(a.treated_area_sqm or 0) for a in areas), ZERO), camera


def ready_rows(db: Session, site_ids: list[int] | None = None, status_: str = "open") -> list[dict]:
    q = select(ReadyToBill).where(ReadyToBill.status == status_).order_by(ReadyToBill.created_at)
    if site_ids is not None:
        q = q.where(ReadyToBill.site_id.in_(site_ids or [-1]))
    out = []
    for r in db.scalars(q):
        site = db.get(Site, r.site_id)
        node = db.get(SiteNode, r.node_id)
        cl = db.get(ContractLine, r.contract_line_id) if r.contract_line_id else None
        boq = db.get(BoqLine, r.boq_line_id) if r.boq_line_id else None
        from app.sites.models import StageTemplate  # noqa: PLC0415

        st = db.get(StageTemplate, r.stage_template_id) if r.stage_template_id else None
        out.append(
            {
                "id": r.id,
                "site_id": site.id,
                "site": f"{site.code} · {site.name}",
                "node": node.name if node else None,
                "stage": st.name if st else None,
                "qty": r.qty,
                "unit": r.unit,
                "survey_qty": r.survey_qty,
                "camera_only": r.camera_only,
                "contract_line": cl.description[:80] if cl else None,
                "item_no": cl.item_no if cl else None,
                "value": (Decimal(r.qty) * Decimal(cl.rate)).quantize(Decimal("0.01"))
                if cl
                else None,
                "boq_line": boq.description[:80] if boq else None,
                "note": r.note,
                "status": r.status,
                "created_at": r.created_at,
                "age_days": (now() - r.created_at).days,
                "ra_bill_id": r.ra_bill_id,
            }
        )
    return out


# --- new areas -----------------------------------------------------------------------------------


def check_booking(
    db: Session, site: Site, node_id: int | None, new_area_id: int | None, area_scope_id: int | None
) -> None:
    """Material and work are booked only on the site's list (its structure, or an area scope),
    or on a new area waiting for planning's approval."""
    has_list = (
        db.scalar(select(SiteNode.id).where(SiteNode.site_id == site.id).limit(1)) is not None
    )
    if area_scope_id:
        return
    if node_id:
        n = db.get(SiteNode, node_id)
        if n is None or n.site_id != site.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "That area is not on this site's list: ask for a new area",
            )
        return
    if new_area_id:
        r = db.get(NewAreaRequest, new_area_id)
        if r is None or r.site_id != site.id or r.status == "rejected":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "That new area is not open on this site"
            )
        return
    if has_list:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Pick the area it was used on (from the site's list), or ask for a new area",
        )


def approve_area(
    db: Session, r: NewAreaRequest, user_id, parent_id: int | None = None, kind: str = "other"
) -> SiteNode:
    """Added to the structure (and to the site's latest survey); planning is prompted to add it
    to the BOQ / contract and the material plan."""
    from app.portal.service import notify  # noqa: PLC0415
    from app.survey.models import Survey, SurveyArea  # noqa: PLC0415

    node = SiteNode(
        site_id=r.site_id,
        parent_id=parent_id if parent_id is not None else r.parent_node_id,
        kind=kind,
        name=r.name,
        area_sqm=r.approx_sqm,
        created_by=user_id,
    )
    db.add(node)
    db.flush()
    r.status, r.decided_by, r.decided_at, r.node_id = "approved", user_id, now(), node.id
    db.execute(
        SiteIssue.__table__.update().where(SiteIssue.new_area_id == r.id).values(node_id=node.id)
    )
    db.execute(
        DprLine.__table__.update().where(DprLine.new_area_id == r.id).values(node_id=node.id)
    )
    survey = db.scalar(
        select(Survey).where(Survey.site_id == r.site_id).order_by(Survey.id.desc()).limit(1)
    )
    if survey is not None and r.approx_sqm:
        db.add(
            SurveyArea(
                survey_id=survey.id,
                node_id=node.id,
                name=r.name,
                area_type_id=r.area_type_id,
                shape="direct",
                direct_area_sqm=r.approx_sqm,
                method="manual",
                remarks="New area approved from site (approximate size)",
                created_by=user_id,
            )
        )
    site = db.get(Site, r.site_id)
    notify(
        db,
        [user_id, settings(db).planning_user_id],
        "new_area",
        f"{r.name} added at {site.name}: add it to the BOQ / contract and the material plan",
        link=f"/sites/{site.id}",
        site_id=site.id,
    )
    return node


def reject_area(db: Session, r: NewAreaRequest, user_id, move_to: int, note: str | None) -> None:
    """Rejected: the work and material booked on it move to the area the planner picks."""
    n = db.get(SiteNode, move_to)
    if n is None or n.site_id != r.site_id:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Pick an area of this site to move the booked work to",
        )
    db.execute(
        SiteIssue.__table__.update()
        .where(SiteIssue.new_area_id == r.id)
        .values(node_id=move_to, new_area_id=None)
    )
    db.execute(
        DprLine.__table__.update()
        .where(DprLine.new_area_id == r.id)
        .values(node_id=move_to, new_area_id=None)
    )
    r.status, r.decided_by, r.decided_at, r.moved_to_node_id, r.decision_note = (
        "rejected",
        user_id,
        now(),
        move_to,
        note,
    )


# --- labour productivity -------------------------------------------------------------------------


def _norm(
    db: Session, system_id: int | None, area_type_id: int | None
) -> tuple[Decimal | None, bool]:
    """(expected sqm per man-day, a norm row exists): the system's, else the area type's."""
    for col, val in (
        (ProductivityNorm.system_id, system_id),
        (ProductivityNorm.area_type_id, area_type_id),
    ):
        if val is None:
            continue
        n = db.scalar(select(ProductivityNorm).where(col == val))
        if n is not None and n.sqm_per_manday:
            return Decimal(n.sqm_per_manday), True
    return None, False


def mandays(db: Session, site_id: int, subcontractor_id: int, start: date, end: date) -> Decimal:
    rows = db.execute(
        select(Attendance.status, func.count())
        .join(Labour, Labour.id == Attendance.labour_id)
        .where(
            Labour.subcontractor_id == subcontractor_id,
            Attendance.site_id == site_id,
            Attendance.on_date.between(start, end),
            Attendance.status.in_(("present", "half_day")),
        )
        .group_by(Attendance.status)
    ).all()
    return sum((Decimal(n) * (Decimal("0.5") if s == "half_day" else 1) for s, n in rows), ZERO)


def productivity_check(db: Session, bill: SubconBill) -> str:
    """Man-days from attendance in the bill period against the sqm done on this contractor's
    work in that period. More than 20 % (setting) below the expected sqm per man-day: low."""
    wo = db.get(WorkOrder, bill.wo_id)
    rows = db.execute(
        select(WoMeasurement, WoLine)
        .join(SubconBillLine, SubconBillLine.measurement_id == WoMeasurement.id)
        .join(WoLine, WoLine.id == WoMeasurement.line_id)
        .where(SubconBillLine.subcon_bill_id == bill.id)
    ).all()
    sqm, systems, area_types, days = ZERO, defaultdict(Decimal), defaultdict(Decimal), []
    for m, ln in rows:
        unit = (ln.unit or "").lower()
        q = Decimal(m.qty)
        if unit == "sqft":
            q = q / SQFT_PER_SQM
        elif unit != "sqm":
            continue
        sqm += q
        days.append(m.on_date)
        boq = db.get(BoqLine, ln.boq_line_id) if ln.boq_line_id else None
        if boq and boq.system_id:
            systems[boq.system_id] += q
        if ln.area_scope_id:
            at = _area_type_of_scope(db, ln.area_scope_id)
            if at:
                area_types[at] += q
    if not days or sqm <= 0:
        bill.productivity_status, bill.productivity = (
            "none",
            {"note": "No sqm measured on this bill"},
        )
        return "none"
    start, end = min(days), max(days)
    md = mandays(db, wo.site_id, wo.subcontractor_id, start, end)
    system_id = max(systems, key=systems.get) if systems else None
    area_type_id = max(area_types, key=area_types.get) if area_types else None
    expected, _has = _norm(db, system_id, area_type_id)
    actual = (sqm / md).quantize(Decimal("0.01")) if md else None
    drop = Decimal(settings(db).productivity_drop_percent)
    info = {
        "period_from": start.isoformat(),
        "period_to": end.isoformat(),
        "mandays": str(md),
        "sqm": str(sqm.quantize(Decimal("0.01"))),
        "actual": str(actual) if actual is not None else None,
        "expected": str(expected) if expected is not None else None,
        "system_id": system_id,
        "area_type_id": area_type_id,
        "drop_percent": str(drop),
    }
    if expected is None:
        state = "to_be_set"
    elif actual is None:
        state = "none"
        info["note"] = "No attendance for this contractor's labour in the period"
    else:
        info["below_percent"] = str(pct(expected, actual) if actual else 100)
        state = "low" if actual < expected * (1 - drop / 100) else "ok"
    bill.productivity_status, bill.productivity = state, info
    return state


def _area_type_of_scope(db: Session, scope_id: int) -> int | None:
    from app.survey.models import SurveyArea  # noqa: PLC0415

    scope = db.get(AreaScope, scope_id)
    if scope is None:
        return None
    return db.scalar(
        select(SurveyArea.area_type_id)
        .where(SurveyArea.node_id == scope.node_id, SurveyArea.area_type_id.is_not(None))
        .limit(1)
    )


def productivity_gate(db: Session, bill: SubconBill) -> None:
    if productivity_check(db, bill) == "low" and bill.productivity_override_at is None:
        info = bill.productivity or {}
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Productivity low: {info.get('actual')} sqm per man-day against {info.get('expected')} expected. Approval needs labourcheck.override with a note.",
        )


def productivity_report(db: Session, site_id: int | None = None) -> list[dict]:
    """Per site, contractor and month: man-days, sqm, actual vs expected."""
    rows = db.execute(
        select(WorkOrder, WoLine, WoMeasurement)
        .join(WoLine, WoLine.wo_id == WorkOrder.id)
        .join(WoMeasurement, WoMeasurement.line_id == WoLine.id)
        .where(
            WoMeasurement.status != "rejected", *([WorkOrder.site_id == site_id] if site_id else [])
        )
    ).all()
    groups: dict[tuple, dict] = {}
    for wo, ln, m in rows:
        unit = (ln.unit or "").lower()
        if unit not in ("sqm", "sqft"):
            continue
        q = Decimal(m.qty) / (SQFT_PER_SQM if unit == "sqft" else 1)
        key = (wo.site_id, wo.subcontractor_id, m.on_date.strftime("%Y-%m"))
        g = groups.setdefault(
            key, {"sqm": ZERO, "systems": defaultdict(Decimal), "from": m.on_date, "to": m.on_date}
        )
        g["sqm"] += q
        g["from"], g["to"] = min(g["from"], m.on_date), max(g["to"], m.on_date)
        boq = db.get(BoqLine, ln.boq_line_id) if ln.boq_line_id else None
        if boq and boq.system_id:
            g["systems"][boq.system_id] += q
    from app.masters.models import Vendor  # noqa: PLC0415

    drop = Decimal(settings(db).productivity_drop_percent)
    out = []
    for (sid, sub, month), g in sorted(groups.items(), key=lambda kv: kv[0][2], reverse=True):
        y, mth = map(int, month.split("-"))
        start = date(y, mth, 1)
        end = date(y + (mth == 12), mth % 12 + 1, 1)
        md = mandays(db, sid, sub, start, date.fromordinal(end.toordinal() - 1))  # the whole month
        system_id = max(g["systems"], key=g["systems"].get) if g["systems"] else None
        expected, _h = _norm(db, system_id, None)
        actual = (g["sqm"] / md).quantize(Decimal("0.01")) if md else None
        state = (
            "to_be_set"
            if expected is None
            else (
                "no attendance"
                if actual is None
                else ("low" if actual < expected * (1 - drop / 100) else "ok")
            )
        )
        site = db.get(Site, sid)
        vendor = db.get(Vendor, sub)
        out.append(
            {
                "site": f"{site.code} · {site.name}",
                "contractor": vendor.name if vendor else None,
                "month": month,
                "mandays": md,
                "sqm": g["sqm"].quantize(Decimal("0.01")),
                "actual": actual,
                "expected": expected,
                "status": state,
            }
        )
    return out


# --- consumption variance ------------------------------------------------------------------------


def _expected_per_sqm(db: Session, system_id: int) -> dict[int, Decimal]:
    """Per product of the system: consumption per sqm including its wastage (base unit)."""
    out = {}
    for c in db.scalars(select(SystemComponent).where(SystemComponent.system_id == system_id)):
        out[c.product_id] = Decimal(c.consumption_per_unit) * (
            1 + Decimal(c.wastage_percent or 0) / 100
        )
    return out


def _issued(db: Session, site_id: int) -> dict[tuple[int, int], Decimal]:
    """{(node, product): base qty issued (returns taken off)} from material issues."""
    rows = db.execute(
        select(
            SiteIssue.kind,
            SiteIssue.node_id,
            AreaScope.node_id,
            SiteIssueLine.product_id,
            SiteIssueLine.qty,
        )
        .join(SiteIssueLine, SiteIssueLine.issue_id == SiteIssue.id)
        .outerjoin(AreaScope, AreaScope.id == SiteIssue.area_scope_id)
        .where(SiteIssue.site_id == site_id)
    ).all()
    out: dict[tuple[int, int], Decimal] = defaultdict(Decimal)
    for kind, node, scope_node, product, qty in rows:
        n = node or scope_node
        if n is None:
            continue
        out[(n, product)] += Decimal(qty) * (-1 if kind == "return" else 1)
    return out


def node_label(db: Session, node: SiteNode | None) -> str | None:
    """The place with its parents ("Tower A / Floor 3 / Toilet 1"): names repeat across floors."""
    names = []
    while node is not None:
        names.append(node.name)
        node = db.get(SiteNode, node.parent_id) if node.parent_id else None
    return " / ".join(reversed(names)) or None


def consumption(db: Session, site_id: int) -> list[dict]:
    """Per place and product: material issued against treated area done × the system's
    consumption per sqm; variance %, flagged outside ±15 % (setting). A place with no material
    booked to it is left out (its material may be booked to the site as a whole)."""
    tol = Decimal(settings(db).consumption_tolerance_percent)
    issued = _issued(db, site_id)
    done: dict[int, list[tuple[Decimal, int]]] = defaultdict(list)  # node -> [(sqm done, system)]
    for scope, boq in db.execute(
        select(AreaScope, BoqLine)
        .join(BoqLine, BoqLine.id == AreaScope.boq_line_id)
        .where(AreaScope.site_id == site_id)
    ).all():
        if not boq.system_id:
            continue
        unit = (scope.unit or boq.unit or "").lower()
        if unit not in ("sqm", "sqft"):
            continue
        sqm = (
            Decimal(scope.qty)
            * Decimal(scope.progress_percent)
            / 100
            / (SQFT_PER_SQM if unit == "sqft" else 1)
        )
        done[scope.node_id].append((sqm, boq.system_id))
    out = []
    for node_id, parts in done.items():
        node = db.get(SiteNode, node_id)
        expected: dict[int, Decimal] = defaultdict(Decimal)
        sqm_total = ZERO
        systems = set()
        for sqm, system_id in parts:
            sqm_total += sqm
            systems.add(system_id)
            for product_id, per in _expected_per_sqm(db, system_id).items():
                expected[product_id] += sqm * per
        for product_id in set(expected) | {p for (n, p) in issued if n == node_id}:
            exp = expected.get(product_id, ZERO)
            got = issued.get((node_id, product_id), ZERO)
            if got <= 0:
                continue
            var = pct(got, exp) if exp > 0 else None
            product = db.get(Product, product_id)
            out.append(
                {
                    "node_id": node_id,
                    "node": node_label(db, node),
                    "product_id": product_id,
                    "product": product.name,
                    "unit": product.unit,
                    "sqm_done": sqm_total.quantize(Decimal("0.01")),
                    "issued": got.quantize(Decimal("0.001")),
                    "expected": exp.quantize(Decimal("0.001")),
                    "actual_per_sqm": (got / sqm_total).quantize(Decimal("0.0001"))
                    if sqm_total
                    else None,
                    "variance_percent": var,
                    "flag": var is None or abs(var) > tol,
                    "systems": sorted(systems),
                }
            )
    return sorted(out, key=lambda r: (r["node"] or "", r["product"]))


def learned(db: Session, system_id: int | None = None) -> list[dict]:
    """Across completed areas (scope at 100 %): the median actual consumption per sqm for each
    system and product, with the count of areas. Shown next to the system's figure; it never
    changes the master by itself."""
    samples: dict[tuple[int, int], list[Decimal]] = defaultdict(list)
    site_ids = db.scalars(
        select(AreaScope.site_id).where(AreaScope.progress_percent >= 100).distinct()
    ).all()
    for sid in site_ids:
        issued = _issued(db, sid)
        for scope, boq in db.execute(
            select(AreaScope, BoqLine)
            .join(BoqLine, BoqLine.id == AreaScope.boq_line_id)
            .where(AreaScope.site_id == sid, AreaScope.progress_percent >= 100)
        ).all():
            if not boq.system_id or (system_id and boq.system_id != system_id):
                continue
            unit = (scope.unit or "").lower()
            if unit not in ("sqm", "sqft"):
                continue
            sqm = Decimal(scope.qty) / (SQFT_PER_SQM if unit == "sqft" else 1)
            if sqm <= 0:
                continue
            for product_id in _expected_per_sqm(db, boq.system_id):
                got = issued.get((scope.node_id, product_id))
                if got:
                    samples[(boq.system_id, product_id)].append(got / sqm)
    out = []
    for (sys_id, product_id), vals in samples.items():
        comp = db.scalar(
            select(SystemComponent).where(
                SystemComponent.system_id == sys_id, SystemComponent.product_id == product_id
            )
        )
        out.append(
            {
                "system_id": sys_id,
                "system": f"{system.code} · {system.name}"
                if (system := db.get(System, sys_id))
                else None,
                "product_id": product_id,
                "product": db.get(Product, product_id).name,
                "site_average": Decimal(statistics.median(vals)).quantize(Decimal("0.0001")),
                "areas": len(vals),
                "master": Decimal(comp.consumption_per_unit) if comp else None,
            }
        )
    return out


def site_flags(db: Session, site_id: int) -> dict:
    """For the site page: pending new areas and consumption rows off the system."""
    return {
        "pending_new_areas": db.scalar(
            select(func.count()).where(
                NewAreaRequest.site_id == site_id, NewAreaRequest.status == "pending"
            )
        ),
        "consumption_flags": sum(1 for r in consumption(db, site_id) if r["flag"]),
        "deliveries_unconfirmed": db.scalar(
            select(func.count()).where(
                DeliveryNote.site_id == site_id,
                DeliveryNote.confirmed_at.is_(None),
                DeliveryNote.status == "dispatched",
            )
        ),
    }


def unconfirmed_count(db: Session, site_ids: list[int] | None = None) -> int:
    q = select(func.count()).where(
        DeliveryNote.confirmed_at.is_(None), DeliveryNote.status == "dispatched"
    )
    if site_ids is not None:
        q = q.where(DeliveryNote.site_id.in_(site_ids or [-1]))
    return db.scalar(q) or 0


def billed_not_confirmed(db: Session) -> list[dict]:
    """Bill lines for PO deliveries the site has not confirmed."""
    rows = db.execute(
        select(VendorBill, DeliveryNote)
        .join(VendorBillLine, VendorBillLine.vendor_bill_id == VendorBill.id)
        .join(PoLine, PoLine.id == VendorBillLine.po_line_id)
        .join(DeliveryNote, DeliveryNote.po_id == PoLine.po_id)
        .where(
            DeliveryNote.confirmed_at.is_(None),
            DeliveryNote.status == "dispatched",
            VendorBill.status != "cancelled",
        )
        .distinct()
    ).all()
    return [
        {
            "bill": b.number,
            "bill_id": b.id,
            "delivery": dn.code,
            "delivery_id": dn.id,
            "expected_at": dn.expected_at,
        }
        for b, dn in rows
    ]


def po_of(db: Session, po_id: int) -> PurchaseOrder | None:
    return db.get(PurchaseOrder, po_id)
