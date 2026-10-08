# ruff: noqa: E501  (user-facing sentences read better unwrapped)
"""Strategy analytics, to win more sites: the tender funnel, win / loss by segment, lost reasons,
pricing position against the rate library, repeat clients.

Definitions:
- Funnel (leads and tenders received in the range): leads (junk excluded) -> tenders -> submitted
  (ever sent to the client) -> won / lost. Conversion at each step = this step / the one before;
  win rate = won / (won + lost). Tenders without a lead still count from the tender step on.
- Win / loss: tenders decided (won or lost) in the range; win rate = won / (won + lost).
- Pricing position: for each quoted BOQ line linked to a rate-library item, our rate / the
  library median rate (from all historic BOQs); the median of those ratios, won vs lost.
- Repeat client: a client with two or more sites (imported historic ones included) or two or more
  won tenders. Revenue = billed (taxable, less credit notes) in the range.
"""

import statistics
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics.common import ZERO, Filters, money, pct, size_band, today
from app.analytics.models import MonthlySummary
from app.auth.deps import Principal
from app.crm.models import Lead
from app.masters.models import Client, LibraryItem, LibraryLine, System
from app.models import User
from app.sites.models import Site
from app.tenders.models import LOST_REASONS, BoqLine, Tender, TenderRevision

SOURCE_DIRECT = "direct (no lead)"


def _names(db: Session):
    return (
        dict(db.execute(select(User.id, User.full_name)).all()),
        {c.id: c for c in db.scalars(select(Client))},
        dict(db.execute(select(System.id, System.name)).all()),
    )


def main_systems(db: Session, tender_ids) -> dict[int, int]:
    """The system with the largest quoted amount on each tender's BOQ."""
    best: dict[int, tuple[Decimal, int]] = {}
    for tid, sid, amount in db.execute(
        select(BoqLine.tender_id, BoqLine.system_id, func.sum(func.coalesce(BoqLine.amount, 0)))
        .where(BoqLine.tender_id.in_(list(tender_ids) or [0]), BoqLine.system_id.is_not(None))
        .group_by(BoqLine.tender_id, BoqLine.system_id)
    ):
        if tid not in best or Decimal(amount) > best[tid][0]:
            best[tid] = (Decimal(amount), sid)
    return {k: v[1] for k, v in best.items()}


def tender_rows(
    db: Session, principal: Principal, scope: str, f: Filters, by: str = "received"
) -> list[dict]:
    """One dict per tender in the range (received, or decided when by="decided")."""
    users, clients, systems = _names(db)
    q = select(Tender).where(Tender.is_demo == f.demo)
    if scope == "own":
        q = q.where(Tender.owner_id == principal.user.id)
    if f.salesperson:
        q = q.where(Tender.owner_id == f.salesperson)
    tenders = list(db.scalars(q))
    submitted = set(db.scalars(select(TenderRevision.tender_id).distinct()))
    sources = dict(
        db.execute(
            select(Lead.tender_id, Lead.lead_source).where(Lead.tender_id.is_not(None))
        ).all()
    )
    mains = main_systems(db, [t.id for t in tenders])
    out = []
    for t in tenders:
        on = t.received_on or t.created_at.date()
        if by == "decided":
            if t.status not in ("won", "lost") or not t.decided_at:
                continue
            on = t.decided_at.date()
        if not (f.date_from <= on <= f.date_to):
            continue
        c = clients.get(t.client_id)
        row = {
            "id": t.id,
            "code": t.code,
            "status": t.status,
            "month": f"{on:%Y-%m}",
            "salesperson": users.get(t.owner_id, "unassigned"),
            "client_type": c.type if c else "unknown",
            "source": sources.get(t.id, SOURCE_DIRECT),
            "region": t.site_state or (c.state if c else None) or "unknown",
            "system": systems.get(mains.get(t.id), "unspecified"),
            "band": size_band(t.quoted_total),
            "quoted": Decimal(t.quoted_total or 0),
            "submitted": t.id in submitted or t.status in ("submitted", "won", "lost"),
            "lost_reason": t.lost_reason,
            "lost_to": t.lost_to,
        }
        if f.client_type and row["client_type"] != f.client_type:
            continue
        if f.region and row["region"] != f.region:
            continue
        out.append(row)
    return out


def lead_rows(db: Session, principal: Principal, scope: str, f: Filters) -> list[dict]:
    users, clients, _ = _names(db)
    q = select(Lead).where(Lead.is_demo == f.demo, Lead.status != "junk")
    if scope == "own":
        q = q.where(Lead.owner_id == principal.user.id)
    if f.salesperson:
        q = q.where(Lead.owner_id == f.salesperson)
    out = []
    for x in db.scalars(q):
        on = x.created_at.date()
        if not (f.date_from <= on <= f.date_to):
            continue
        c = clients.get(x.client_id)
        row = {
            "id": x.id,
            "month": f"{on:%Y-%m}",
            "salesperson": users.get(x.owner_id, "unassigned"),
            "client_type": c.type if c else "unknown",
            "source": x.lead_source,
            "region": x.state or "unknown",
            "status": x.status,
            "value": Decimal(x.est_value or 0),
            "lost_reason": x.lost_reason,
            "lost_to": x.lost_to,
        }
        if f.client_type and row["client_type"] != f.client_type:
            continue
        if f.region and row["region"] != f.region:
            continue
        out.append(row)
    return out


def _steps(leads: list[dict], tenders: list[dict]) -> dict:
    sub = [t for t in tenders if t["submitted"]]
    won = [t for t in tenders if t["status"] == "won"]
    lost = [t for t in tenders if t["status"] == "lost"]
    steps = [
        {
            "step": "leads",
            "label": "Leads",
            "count": len(leads),
            "value": money(sum((x["value"] for x in leads), ZERO)),
        },
        {
            "step": "tenders",
            "label": "Tenders",
            "count": len(tenders),
            "value": money(sum((t["quoted"] for t in tenders), ZERO)),
        },
        {
            "step": "submitted",
            "label": "Submitted",
            "count": len(sub),
            "value": money(sum((t["quoted"] for t in sub), ZERO)),
        },
        {
            "step": "won",
            "label": "Won",
            "count": len(won),
            "value": money(sum((t["quoted"] for t in won), ZERO)),
        },
    ]
    for prev, cur in zip(steps, steps[1:], strict=False):
        cur["conversion"] = pct(cur["count"], prev["count"])
    steps[0]["conversion"] = None
    return {
        "steps": steps,
        "lost": {"count": len(lost), "value": money(sum((t["quoted"] for t in lost), ZERO))},
        "win_rate": pct(len(won), len(won) + len(lost)),
    }


DIMENSIONS = ("month", "salesperson", "client_type", "source", "region")


def funnel(
    db: Session, principal: Principal, scope: str, f: Filters, group_by: str | None = None
) -> dict:
    leads, tenders = lead_rows(db, principal, scope, f), tender_rows(db, principal, scope, f)
    out = {"total": _steps(leads, tenders), "group_by": group_by, "groups": []}
    if group_by in DIMENSIONS:
        keys = sorted({x[group_by] for x in leads} | {t[group_by] for t in tenders})
        for k in keys:
            g = _steps(
                [x for x in leads if x[group_by] == k], [t for t in tenders if t[group_by] == k]
            )
            out["groups"].append({"key": k, **g})
    return out


def winloss(db: Session, principal: Principal, scope: str, f: Filters) -> dict:
    rows = tender_rows(db, principal, scope, f, by="decided")
    segments = {}
    for dim in ("client_type", "band", "system", "region", "salesperson"):
        acc: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        val: dict[str, Decimal] = defaultdict(Decimal)
        for r in rows:
            acc[r[dim]][0 if r["status"] == "won" else 1] += 1
            if r["status"] == "won":
                val[r[dim]] += r["quoted"]
        segments[dim] = sorted(
            (
                {
                    "key": k,
                    "won": w,
                    "lost": lo,
                    "win_rate": pct(w, w + lo),
                    "won_value": money(val[k]),
                }
                for k, (w, lo) in acc.items()
            ),
            key=lambda x: -(x["won"] + x["lost"]),
        )
    reasons: dict[str, list] = {r: [0, ZERO, 0] for r in LOST_REASONS}  # tenders, value, leads
    competitors: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["status"] == "lost":
            key = r["lost_reason"] or "other"
            reasons[key][0] += 1
            reasons[key][1] += r["quoted"]
            if r["lost_to"]:
                competitors[r["lost_to"].strip()] += 1
    for x in lead_rows(db, principal, scope, f):
        if x["status"] == "lost":
            reasons[x["lost_reason"] or "other"][2] += 1
            if x["lost_to"]:
                competitors[x["lost_to"].strip()] += 1
    won = sum(1 for r in rows if r["status"] == "won")
    return {
        "decided": len(rows),
        "won": won,
        "win_rate": pct(won, len(rows)),
        "segments": segments,
        "lost_reasons": [
            {"reason": k, "tenders": v[0], "value": money(v[1]), "leads": v[2]}
            for k, v in reasons.items()
        ],
        "competitors": sorted(
            ({"name": k, "count": v} for k, v in competitors.items()), key=lambda x: -x["count"]
        )[:15],
    }


def pricing(db: Session, principal: Principal, scope: str, f: Filters) -> dict:
    rows = {r["id"]: r for r in tender_rows(db, principal, scope, f, by="decided")}
    _, _, systems = _names(db)
    ratios: dict[tuple[str, str], list[float]] = defaultdict(list)
    q = (
        select(BoqLine.tender_id, BoqLine.system_id, BoqLine.rate, LibraryItem.median_rate)
        .join(LibraryItem, LibraryItem.id == BoqLine.library_item_id)
        .where(
            BoqLine.tender_id.in_(list(rows) or [0]), BoqLine.rate > 0, LibraryItem.median_rate > 0
        )
    )
    for tid, sid, rate, median in db.execute(q):
        outcome = rows[tid]["status"]
        ratios[(systems.get(sid, "No system"), outcome)].append(
            float(Decimal(rate) / Decimal(median))
        )
        ratios[("All systems", outcome)].append(float(Decimal(rate) / Decimal(median)))

    def stat(xs):
        return {"lines": len(xs), "median_ratio": round(statistics.median(xs), 3) if xs else None}

    names = sorted({k[0] for k in ratios}, key=lambda n: (n != "All systems", n))
    return {
        "systems": [
            {
                "system": n,
                "won": stat(ratios.get((n, "won"), [])),
                "lost": stat(ratios.get((n, "lost"), [])),
            }
            for n in names
        ],
        "note": "Ratio = our quoted rate / the rate-library median for the same item (1.00 = at the median). "
        "Only BOQ lines matched to a library item count.",
    }


def repeat_clients(db: Session, f: Filters) -> dict:
    clients = {c.id: c for c in db.scalars(select(Client).where(Client.is_demo == f.demo))}
    sites_per = dict(
        db.execute(
            select(Site.client_id, func.count())
            .where(Site.client_id.is_not(None))
            .group_by(Site.client_id)
        ).all()
    )
    won_per = dict(
        db.execute(
            select(Tender.client_id, func.count())
            .where(Tender.status == "won")
            .group_by(Tender.client_id)
        ).all()
    )
    repeat = {cid for cid in clients if sites_per.get(cid, 0) >= 2 or won_per.get(cid, 0) >= 2}
    site_client = dict(db.execute(select(Site.id, Site.client_id)).all())
    billed: dict[int, Decimal] = defaultdict(Decimal)
    for site_id, v in db.execute(
        select(MonthlySummary.site_id, func.sum(MonthlySummary.billed))
        .where(
            MonthlySummary.is_demo == f.demo,
            MonthlySummary.month.between(f.date_from.replace(day=1), f.date_to),
        )
        .group_by(MonthlySummary.site_id)
    ):
        cid = site_client.get(site_id)
        if cid in clients:
            billed[cid] += Decimal(v)
    total = sum(billed.values(), ZERO)
    rep = sum((v for k, v in billed.items() if k in repeat), ZERO)
    top = sorted(billed.items(), key=lambda kv: -kv[1])[:10]
    last_lead = dict(
        db.execute(select(Lead.client_id, func.max(Lead.created_at)).group_by(Lead.client_id)).all()
    )
    last_tender = dict(
        db.execute(
            select(
                Tender.client_id,
                func.max(func.coalesce(Tender.received_on, func.date(Tender.created_at))),
            ).group_by(Tender.client_id)
        ).all()
    )
    cutoff = today() - timedelta(days=365)
    quiet = []
    for cid, c in clients.items():
        if not c.is_active or not (sites_per.get(cid) or won_per.get(cid)):
            continue  # only past customers
        dates = [
            d.date() if hasattr(d, "date") and callable(d.date) else d
            for d in (last_lead.get(cid), last_tender.get(cid))
            if d
        ]
        last = max(dates) if dates else None
        if last is None or last < cutoff:
            quiet.append(
                {
                    "client_id": cid,
                    "name": c.name,
                    "type": c.type,
                    "last_enquiry": last,
                    "sites": sites_per.get(cid, 0),
                    "billed": money(billed.get(cid, ZERO)),
                    "link": f"/clients?open={cid}",
                }
            )
    quiet.sort(key=lambda r: (-(r["sites"]), r["name"]))
    return {
        "billed_total": money(total),
        "billed_repeat": money(rep),
        "repeat_share": pct(rep, total),
        "repeat_clients": len(repeat),
        "top": [
            {
                "client_id": k,
                "name": clients[k].name,
                "billed": money(v),
                "repeat": k in repeat,
                "drill": {"kind": "invoices", "filter": "outstanding", "client_id": k},
            }
            for k, v in top
        ],
        "quiet": quiet[:50],
    }


def historic(db: Session) -> dict:
    """What historic data the analytics can draw on (labelled 'historic' on the pages)."""
    return {
        "powerplay_sites": db.scalar(
            select(func.count()).where(Site.source == "powerplay", Site.is_demo.is_(False))
        ),
        "library_lines": db.scalar(select(func.count()).select_from(LibraryLine)),
        "library_files": db.scalar(select(func.count(func.distinct(LibraryLine.file)))),
        "library_items_with_median": db.scalar(
            select(func.count()).where(LibraryItem.median_rate.is_not(None))
        ),
        "tenders": db.scalar(select(func.count()).where(Tender.is_demo.is_(False))),
        "tenders_decided": db.scalar(
            select(func.count()).where(
                Tender.is_demo.is_(False), Tender.status.in_(("won", "lost"))
            )
        ),
        "boq_lines": db.scalar(
            select(func.count())
            .select_from(BoqLine)
            .join(Tender, Tender.id == BoqLine.tender_id)
            .where(Tender.is_demo.is_(False))
        ),
        "note": "Powerplay sites carry progress and dates but no billing; historic BOQs feed the rate-library medians "
        "used by the pricing position, not the funnel (they have no win / loss outcome).",
    }
