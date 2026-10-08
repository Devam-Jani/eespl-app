"""Invented analytics demo data: `python -m app.cli seed-demo-analytics` (and `--purge`).

A separate demo company: every client, supplier, product, site, lead, tender and user it creates
carries is_demo, every number on the dashboards is either demo or real (never both: `demo=true`),
and alerts ignore it. Its codes are its own (DEMO-...), so it never takes a real document number.
Every row it inserts is listed in demo_rows; --purge deletes exactly those rows and nothing else.
"""

import random
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import delete, func, insert, inspect, select, tuple_
from sqlalchemy.orm import Session

from app.analytics.common import add_months, today
from app.analytics.models import DemoRow, KpiSnapshot, MonthlySummary
from app.crm.models import Lead
from app.execution.models import Attendance, Dpr, Labour, SiteBudget, SiteCost
from app.finance.models import (
    ClientContract,
    InvoiceLine,
    RaBill,
    Receipt,
    ReceiptAllocation,
    RetentionRelease,
    TaxInvoice,
    VendorBill,
)
from app.masters.models import Category, Client, LibraryItem, Product, System, Vendor
from app.material.models import FreightEntry, Grn, Indent, PoLine, PurchaseOrder, StockLedger, Store
from app.models import Base, Role, User
from app.portal.models import Snag
from app.sites.models import (
    AreaScope,
    Site,
    SiteMember,
    SiteNode,
    StageTemplate,
    StageTemplateStep,
    Task,
)
from app.tenders.models import BoqLine, Tender, TenderRevision

D = Decimal
STATES = [("Gujarat", 40), ("Maharashtra", 30), ("Rajasthan", 12), ("Karnataka", 10), ("Delhi", 8)]
CITIES = {
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara", "Rajkot"],
    "Maharashtra": ["Mumbai", "Pune", "Nashik"],
    "Rajasthan": ["Jaipur", "Udaipur"],
    "Karnataka": ["Bengaluru", "Mysuru"],
    "Delhi": ["New Delhi"],
}
CLIENT_TYPES = [
    ("builder", 9),
    ("developer", 8),
    ("pmc", 4),
    ("contractor", 5),
    ("government", 2),
    ("other", 2),
]
SOURCES = [
    ("referral", 25),
    ("call", 20),
    ("website", 18),
    ("channel", 15),
    ("exhibition", 8),
    ("walk_in", 6),
    ("other", 8),
]
SYSTEMS = [
    ("PU coating", 380),
    ("Crystalline", 220),
    ("APP membrane", 300),
    ("Cementitious", 150),
    ("Injection grouting", 900),
]
KINDS_OF_FIRM = ["Realty", "Infra", "Builders", "Developers", "Projects"]
COMPETITORS = [
    "DEMO Rival Aqua",
    "DEMO Rival Seal",
    "DEMO Rival Dry",
    "DEMO Rival Shield",
    "DEMO Rival Proof",
]
PRODUCTS = [
    ("PU membrane", "kg", 420),
    ("PU top coat", "kg", 520),
    ("Primer", "ltr", 260),
    ("Crystalline powder", "kg", 140),
    ("APP membrane 4 mm", "sqm", 310),
    ("Bitumen primer", "ltr", 120),
    ("Polymer cement", "kg", 95),
    ("Injection resin", "kg", 980),
    ("Packers", "nos", 35),
    ("Glass fibre mesh", "sqm", 48),
    ("PU sealant", "ltr", 610),
    ("Waterstop tape", "rmt", 180),
]


def money(v) -> Decimal:
    return D(v).quantize(D("0.01"), ROUND_HALF_UP)


class Seeder:
    """Adds rows and records each one in demo_rows."""

    def __init__(self, db: Session):
        self.db, self.pending = db, []

    def add(self, obj):
        self.db.add(obj)
        self.pending.append(obj)
        if len(self.pending) >= 2000:
            self.flush()
        return obj

    def flush(self):
        self.db.flush()
        rows = []
        for obj in self.pending:
            key = inspect(obj).identity
            rows.append({"table_name": obj.__tablename__, "row_key": "|".join(str(k) for k in key)})
        if rows:
            self.db.execute(insert(DemoRow), rows)
        self.pending = []


def exists(db: Session) -> bool:
    return bool(db.scalar(select(func.count()).select_from(DemoRow)))


def seed(db: Session, sites: int = 60, leads: int = 400, seed_value: int = 2026) -> dict:
    """Create the demo company (refuses when it already exists: purge first)."""
    if exists(db):
        raise ValueError("Demo data already exists: run with --purge first")
    rng = random.Random(seed_value)
    s = Seeder(db)
    day = today()
    start = add_months(day.replace(day=1), -23)

    def pick(weighted):
        return rng.choices([x for x, _ in weighted], weights=[w for _, w in weighted])[0]

    def at(d: date, hour: int = 11) -> datetime:
        return datetime.combine(d, time(hour, rng.randint(0, 59)), tzinfo=UTC)

    # people
    sales_role = db.scalar(select(Role).where(Role.code == "sales"))
    sup_role = db.scalar(select(Role).where(Role.code == "site_supervisor"))
    sales = [
        s.add(
            User(
                email=f"demo-sales-{c}@demo.invalid",
                full_name=f"DEMO Sales {n}",
                is_active=False,
                is_demo=True,
                roles=[sales_role] if sales_role else [],
            )
        )
        for c, n in zip("abcd", ("Asha", "Bharat", "Chetan", "Divya"), strict=True)
    ]
    sups = [
        s.add(
            User(
                email=f"demo-supervisor-{i}@demo.invalid",
                full_name=f"DEMO Supervisor {i}",
                is_active=False,
                is_demo=True,
                roles=[sup_role] if sup_role else [],
            )
        )
        for i in range(1, 4)
    ]
    # masters
    clients = []
    for i in range(1, 31):
        state = pick(STATES)
        clients.append(
            s.add(
                Client(
                    name=f"DEMO Client {i:02d} {rng.choice(KINDS_OF_FIRM)}",
                    type=pick(CLIENT_TYPES),
                    state=state,
                    city=rng.choice(CITIES[state]),
                    is_demo=True,
                )
            )
        )
    vendors = [
        s.add(
            Vendor(
                name=f"DEMO Supplier {i:02d}",
                type="material_supplier",
                state="Gujarat",
                is_demo=True,
                payment_terms_days=30,
            )
        )
        for i in range(1, 11)
    ]
    cats = list(db.scalars(select(Category.id).where(Category.kind == "material")))
    products = []
    for i, (name, unit, _rate) in enumerate(PRODUCTS, 1):
        products.append(
            s.add(
                Product(
                    code=f"DEMO-P{i:03d}",
                    name=f"DEMO {name}",
                    unit=unit,
                    gst_percent=18,
                    is_demo=True,
                    category_id=cats[i % len(cats)] if cats else None,
                    reorder_level=D(rng.choice([200, 300, 500])) if i % 2 else None,
                )
            )
        )
    systems = [
        s.add(
            System(
                code=f"DEMO-SYS-{i}",
                name=f"DEMO {name}",
                unit="sqm",
                labour_rate=D(base) * D("0.25"),
            )
        )
        for i, (name, base) in enumerate(SYSTEMS, 1)
    ]
    s.flush()
    library = list(
        db.scalars(
            select(LibraryItem)
            .where(
                LibraryItem.median_rate.between(150, 1500),
                LibraryItem.is_excluded.is_(False),
                LibraryItem.unit == "sqm",
            )
            .limit(60)
        )
    )

    # leads -> tenders
    def when(i: int, n: int) -> date:
        """Spread over 24 months, busier lately."""
        f = (i / n) ** 0.8
        return start + timedelta(days=int(f * ((day - start).days - 3)))

    tender_no = 0
    tenders: list[tuple[Tender, float]] = []

    def make_tender(client: Client, owner: User, received: date) -> Tender:
        nonlocal tender_no
        tender_no += 1
        factor = max(0.75, rng.gauss(1.02, 0.12))  # our price against the library median
        t = s.add(
            Tender(
                code=f"DEMO-T-{tender_no:04d}",
                name=f"DEMO waterproofing {client.city} {tender_no}",
                client_id=client.id,
                site_city=client.city,
                site_state=client.state,
                received_on=received,
                due_on=received + timedelta(days=rng.randint(7, 21)),
                owner_id=owner.id,
                status="draft",
                is_demo=True,
                created_at=at(received),
            )
        )
        s.flush()
        total = D(0)
        for k in range(rng.randint(2, 5)):
            si = rng.randrange(len(systems))
            item = rng.choice(library) if library else None
            qty = D(rng.randint(300, 6000))
            base = D(item.median_rate) if item else D(SYSTEMS[si][1])
            rate = money(base * D(str(round(factor * rng.uniform(0.95, 1.05), 3))))
            cost = money(rate / D(str(round(rng.uniform(1.12, 1.4), 3))))
            amount = money(rate * qty)
            total += amount
            s.add(
                BoqLine(
                    tender_id=t.id,
                    sort_order=k + 1,
                    description=f"{systems[si].name} to terrace / basement",
                    unit="sqm",
                    qty=qty,
                    system_id=systems[si].id,
                    library_item_id=item.id if item else None,
                    cost_rate=cost,
                    rate=rate,
                    amount=amount,
                    status="priced",
                    source="system",
                )
            )
        t.quoted_total = total
        tenders.append((t, factor))
        return t

    lead_rows = []
    for i in range(leads):
        created = when(i, leads)
        client = rng.choice(clients)
        owner = rng.choice(sales)
        age = (day - created).days
        status = "new"
        if age > 45:
            status = rng.choices(["quoted", "lost", "junk", "contacted"], weights=[62, 20, 8, 10])[
                0
            ]
        elif age > 10:
            status = rng.choices(
                ["contacted", "site_visit", "quoted", "lost"], weights=[30, 25, 40, 5]
            )[0]
        value = D(rng.randint(5, 250)) * 100000
        lead = s.add(
            Lead(
                code=f"DEMO-L-{i + 1:04d}",
                contact_name=f"DEMO Contact {i + 1}",
                phone=f"+9190000{i:05d}",
                company=client.name,
                city=client.city,
                state=client.state,
                lead_source=pick(SOURCES),
                client_id=client.id,
                est_value=value,
                status=status,
                owner_id=owner.id,
                is_demo=True,
                kylas_sync_status="failed" if i % 97 == 5 else "disabled",
                kylas_last_error="DEMO: HTTP 401 from Kylas" if i % 97 == 5 else None,
                created_at=at(created),
            )
        )
        if status == "lost":
            lead.lost_reason = rng.choices(
                ["price", "competitor", "timing", "spec", "relationship", "other"],
                [35, 25, 15, 10, 8, 7],
            )[0]
            lead.lost_to = (
                rng.choice(COMPETITORS) if lead.lost_reason in ("price", "competitor") else None
            )
        if status in ("new", "contacted", "site_visit", "quoted"):
            lead.next_follow_up = day + timedelta(
                days=rng.choice([-9, -5, -2, -1, 0, 0, 1, 3, 7, 14])
            )
        lead_rows.append((lead, created))
    s.flush()
    for lead, created in lead_rows:
        if lead.status == "quoted":
            t = make_tender(
                db.get(Client, lead.client_id),
                db.get(User, lead.owner_id),
                created + timedelta(days=rng.randint(2, 10)),
            )
            lead.tender_id = t.id
    for _ in range(max(10, leads // 10)):  # tenders that came without a lead
        make_tender(rng.choice(clients), rng.choice(sales), when(rng.randint(0, 99), 100))
    s.flush()

    # tender outcomes
    won: list[Tender] = []
    for t, factor in tenders:
        if t.due_on > day:
            continue
        s.add(
            TenderRevision(
                tender_id=t.id,
                rev_no=1,
                snapshot={"demo": True},
                submitted_at=at(t.due_on - timedelta(days=1)),
            )
        )
        t.status, t.revision = "submitted", 1
        decided = t.due_on + timedelta(days=rng.randint(10, 45))
        if decided > day:
            continue
        p_win = min(0.75, max(0.08, 0.45 - (factor - 1) * 2.2))
        roll = rng.random()
        if roll < p_win:
            t.status = "won"
            won.append(t)
        elif roll < 0.96:
            t.status = "lost"
            t.lost_reason = (
                "price"
                if factor > 1.08 and rng.random() < 0.7
                else rng.choice(["competitor", "timing", "spec", "relationship", "other"])
            )
            t.lost_to = (
                rng.choice(COMPETITORS) if t.lost_reason in ("price", "competitor") else None
            )
        else:
            t.status, t.lost_reason = "dropped", "timing"
        t.decided_at = at(decided, 16)
    s.flush()

    # sites
    templates = list(db.scalars(select(StageTemplate).where(StageTemplate.is_active).limit(3)))
    steps = (
        list(
            db.scalars(
                select(StageTemplateStep).where(StageTemplateStep.template_id == templates[0].id)
            )
        )
        if templates
        else []
    )
    made = []
    for n, t in enumerate(sorted(won, key=lambda x: x.decided_at)[-sites:], 1):
        client = db.get(Client, t.client_id)
        begin = t.decided_at.date() + timedelta(days=rng.randint(10, 35))
        duration = rng.randint(100, 320)
        target = begin + timedelta(days=duration)
        elapsed = (day - begin).days / duration
        if begin > day:
            status, progress = "planned", D(0)
        elif elapsed >= 1.25:
            status, progress = rng.choice(["completed", "closed"]), D(100)
        elif n % 23 == 7:
            status, progress = "on_hold", D(str(round(min(95, elapsed * 70), 2)))
        else:
            lag = rng.choice([0, 0, 0, 5, 10, 25, 35]) if n % 4 else 0
            status = "active"
            progress = D(str(round(max(2, min(99, elapsed * 100 - lag + rng.uniform(-4, 4))), 2)))
        site = s.add(
            Site(
                code=f"DEMO-S-{n:03d}",
                name=f"DEMO {client.name.split(' ', 3)[-1]} site {n}",
                client_id=client.id,
                tender_id=t.id,
                state=client.state,
                city=client.city,
                start_date=begin,
                target_date=target,
                status=status,
                progress_percent=progress,
                site_incharge_id=rng.choice(sups).id,
                is_demo=True,
                created_at=at(begin),
            )
        )
        made.append((site, t, begin, target))
    s.flush()
    store = s.add(Store(name="DEMO Store", kind="site", site_id=made[0][0].id)) if made else None
    s.flush()

    # per site: structure, scope, tasks, contract, billing, cost, labour
    inv_no = rec_no = cn_no = ra_no = 0
    labour_rows = []
    attendance = []
    for n, (site, t, begin, target) in enumerate(made, 1):
        s.add(SiteMember(site_id=site.id, user_id=site.site_incharge_id, role_on_site="incharge"))
        s.add(SiteMember(site_id=site.id, user_id=t.owner_id, role_on_site="sales"))
        node = s.add(
            SiteNode(
                site_id=site.id,
                kind="terrace",
                name="Terrace",
                progress_percent=site.progress_percent,
            )
        )
        s.flush()
        area = sum(
            (D(x.qty) for x in db.scalars(select(BoqLine).where(BoqLine.tender_id == t.id))), D(0)
        )
        if templates:
            s.add(
                AreaScope(
                    site_id=site.id,
                    node_id=node.id,
                    stage_template_id=templates[0].id,
                    qty=area,
                    unit="sqm",
                    progress_percent=site.progress_percent,
                )
            )
        if site.status == "active" and steps:
            for k, st in enumerate(steps[:3]):
                status = ["done", "in_progress", "blocked"][k]
                s.add(
                    Task(
                        site_id=site.id,
                        node_id=node.id,
                        step_id=st.id,
                        name=st.name,
                        sort_order=k,
                        status=status,
                        actual_start=day - timedelta(days=rng.randint(3, 70)),
                        planned_end=day + timedelta(days=rng.randint(-20, 30)),
                    )
                )
        value = money(D(t.quoted_total) * D(str(round(rng.uniform(1.0, 1.06), 3))))
        contract = s.add(
            ClientContract(
                site_id=site.id,
                tender_id=t.id,
                client_id=site.client_id,
                contract_value=value,
                retention_percent=5,
                gst_percent=18,
            )
        )
        s.flush()
        cost_ratio = D(
            str(round(rng.uniform(0.66, 0.9) if n % 9 else rng.uniform(1.0, 1.12), 3))
        )  # a few over cost
        material_budget = money(value * D("0.5"))
        s.add(SiteBudget(site_id=site.id, head="material", amount=material_budget, source="manual"))
        s.add(
            SiteBudget(
                site_id=site.id, head="labour", amount=money(value * D("0.2")), source="manual"
            )
        )
        # monthly billing and cost up to today
        if site.status == "planned":
            continue
        end = (
            min(day, target + timedelta(days=30)) if site.status in ("completed", "closed") else day
        )
        billed = D(0)
        m = add_months(begin.replace(day=1), 1)
        slow = rng.random() < 0.2
        own_labour = site.status == "active"
        while m <= end:
            share = min(D(1), D((m - begin).days) / D(max(1, (target - begin).days)))
            target_bill = money(
                value
                * D("0.95")
                * min(share, D(site.progress_percent) / 100 if site.status == "active" else D(1))
            )
            inc = target_bill - billed
            inv_date = m + timedelta(days=rng.randint(0, 6))
            if inc > value * D("0.01") and inv_date <= day:
                inv_no += 1
                taxable = inc
                gst = money(taxable * D("0.09"))
                inv = s.add(
                    TaxInvoice(
                        number=f"DEMO/INV/{inv_no:05d}",
                        kind="invoice",
                        status="issued",
                        invoice_date=inv_date,
                        due_date=inv_date + timedelta(days=30),
                        site_id=site.id,
                        contract_id=contract.id,
                        client_id=site.client_id,
                        interstate=False,
                        taxable=taxable,
                        cgst=gst,
                        sgst=gst,
                        total=taxable + 2 * gst,
                        retention=money(taxable * D("0.05")),
                    )
                )
                s.flush()
                s.add(
                    InvoiceLine(
                        invoice_id=inv.id,
                        description=f"RA bill for {m:%b %Y}",
                        amount=taxable,
                        gst_percent=18,
                    )
                )
                billed += inc
                pay_after = rng.randint(90, 160) if slow else rng.randint(20, 75)
                paid_on = inv_date + timedelta(days=pay_after)
                if paid_on <= day and rng.random() < 0.95:
                    rec_no += 1
                    tds = money(taxable * D("0.02"))
                    settle = D(inv.total) - D(inv.retention)
                    rec = s.add(
                        Receipt(
                            number=f"DEMO-R-{rec_no:05d}",
                            client_id=site.client_id,
                            site_id=site.id,
                            on_date=paid_on,
                            mode="neft",
                            ref_no=f"DEMO-UTR-{rec_no}",
                            amount=settle - tds,
                            tds_amount=tds,
                        )
                    )
                    s.flush()
                    s.add(ReceiptAllocation(receipt_id=rec.id, invoice_id=inv.id, amount=settle))
                if inv_no % 41 == 0:
                    cn_no += 1
                    cn_tax = money(taxable * D("0.05"))
                    cn_gst = money(cn_tax * D("0.09"))
                    s.add(
                        TaxInvoice(
                            number=f"DEMO/CN/{cn_no:05d}",
                            kind="credit_note",
                            status="issued",
                            invoice_date=inv_date + timedelta(days=12),
                            site_id=site.id,
                            contract_id=contract.id,
                            client_id=site.client_id,
                            against_id=inv.id,
                            taxable=cn_tax,
                            cgst=cn_gst,
                            sgst=cn_gst,
                            total=cn_tax + 2 * cn_gst,
                        )
                    )
            # cost of the month: a share of what was billed, by head
            month_cost = money(max(inc, value * D("0.005")) * cost_ratio)
            heads = {
                "material": D("0.5"),
                "subcontract": D("0.18"),
                "equipment": D("0.05"),
                "other": D("0.07"),
            }
            if not own_labour or m < day.replace(day=1) - timedelta(days=120):
                heads["labour"] = D("0.2")
            for head, part in heads.items():
                s.add(
                    SiteCost(
                        site_id=site.id,
                        head=head,
                        on_date=min(day, m + timedelta(days=20)),
                        amount=money(month_cost * part),
                        description=f"DEMO {head} {m:%b %Y}",
                    )
                )
            s.add(
                FreightEntry(
                    source="bill",
                    direction="inbound",
                    site_id=site.id,
                    on_date=min(day, m + timedelta(days=10)),
                    amount=money(month_cost * D("0.5") * D(str(round(rng.uniform(0.02, 0.07), 3)))),
                    transporter="DEMO Transport",
                )
            )
            m = add_months(m, 1)
        if site.status == "closed" and billed:
            s.add(
                RetentionRelease(
                    site_id=site.id,
                    on_date=min(day, target + timedelta(days=60)),
                    amount=money(billed * D("0.025")),
                )
            )
        if site.status == "active" and n % 6 == 0 and billed:
            ra_no += 1
            gross = money(value * D("0.06"))
            s.add(
                RaBill(
                    code=f"DEMO-RA-{ra_no:03d}",
                    contract_id=contract.id,
                    site_id=site.id,
                    seq=1,
                    period_to=day - timedelta(days=5),
                    status="certified",
                    gross=gross,
                    certified_gross=gross,
                    net=gross,
                    certified_at=at(day - timedelta(days=3)),
                )
            )
        # own labour on active sites: the last 120 days of attendance
        if own_labour:
            crew = [
                s.add(
                    Labour(
                        name=f"DEMO Worker {site.code}-{k}",
                        trade=rng.choice(["applicator", "helper", "mason"]),
                        type="own",
                        site_id=site.id,
                        daily_wage=D(rng.choice([650, 720, 800, 900])),
                    )
                )
                for k in range(1, rng.randint(4, 8))
            ]
            labour_rows.extend(crew)
            s.flush()
            first = max(begin, day - timedelta(days=120))
            d = first
            while d < day:
                if d.weekday() != 6:
                    for w in crew:
                        st = rng.choices(["present", "half_day", "absent"], [86, 5, 9])[0]
                        attendance.append(
                            {
                                "labour_id": w.id,
                                "site_id": site.id,
                                "on_date": d,
                                "status": st,
                                "daily_wage": w.daily_wage,
                                "ot_rate_per_hour": 0,
                                "ot_hours": 0,
                            }
                        )
                d += timedelta(days=1)
        # snags, today's DPR
        if site.status in ("active", "completed"):
            for k in range(rng.randint(0, 4)):
                opened = max(begin, day - timedelta(days=rng.randint(5, 150)))
                st = rng.choice(["open", "in_progress", "fixed", "verified", "closed"])
                sn = Snag(
                    code=f"DEMO-SNG-{site.id}-{k}",
                    site_id=site.id,
                    title=rng.choice(
                        [
                            "Damp patch below slab",
                            "Blistering at the edge",
                            "Joint not sealed",
                            "Leak at outlet",
                        ]
                    ),
                    raised_by_side=rng.choice(["client", "staff"]),
                    status=st,
                    created_at=at(opened),
                )
                if st in ("verified", "closed"):
                    sn.fixed_at = at(opened + timedelta(days=rng.randint(2, 12)))
                    sn.verified_at = sn.fixed_at + timedelta(days=rng.randint(1, 6))
                s.add(sn)
        if site.status == "active" and rng.random() < 0.6:
            s.add(
                Dpr(
                    site_id=site.id,
                    on_date=day,
                    status="submitted",
                    work_done="DEMO: primer and first coat on the terrace",
                )
            )
        # progress history for the forecast (weekly, the last 9 weeks)
        if site.status == "active":
            from app.analytics.models import ProgressSnapshot

            for w in range(9, 0, -1):
                d = day - timedelta(weeks=w)
                if d <= begin:
                    continue
                f = D((d - begin).days) / D(max(1, (day - begin).days))
                s.add(
                    ProgressSnapshot(
                        site_id=site.id,
                        on_date=d,
                        percent=money(
                            D(site.progress_percent) * f * D(str(round(rng.uniform(0.97, 1.0), 3)))
                        ),
                    )
                )
    s.flush()
    if attendance:
        ids = db.execute(insert(Attendance).returning(Attendance.id), attendance).scalars().all()
        db.execute(insert(DemoRow), [{"table_name": "attendance", "row_key": str(i)} for i in ids])

    # purchase: POs with a rate trend, some late; indents and GRNs waiting; supplier bills
    if store is not None:
        base_rate = {p.id: D(row[2]) for p, row in zip(products, PRODUCTS, strict=True)}
        for k in range(1, max(40, sites * 5) + 1):
            po_date = start + timedelta(
                days=int(((day - start).days - 2) * (k / max(40, sites * 5)))
            )
            months_in = (po_date - start).days / 30
            age = (day - po_date).days
            status = (
                "closed"
                if age > 45
                else rng.choice(["sent", "approved", "partly_received", "received"])
            )
            po = s.add(
                PurchaseOrder(
                    code=f"DEMO-PO-{k:04d}",
                    vendor_id=rng.choice(vendors).id,
                    store_id=store.id,
                    po_date=po_date,
                    expected_delivery=po_date + timedelta(days=rng.randint(5, 21)),
                    status=status,
                )
            )
            s.flush()
            subtotal = D(0)
            for p in rng.sample(products, rng.randint(1, 4)):
                rate = money(
                    base_rate[p.id]
                    * D(str(round((1 + 0.004 * months_in) * rng.uniform(0.95, 1.05), 4)))
                )
                qty = D(rng.randint(20, 400))
                amount = money(qty * rate)
                subtotal += amount
                s.add(
                    PoLine(
                        po_id=po.id,
                        product_id=p.id,
                        qty=qty,
                        unit=p.unit,
                        base_qty=qty,
                        rate=rate,
                        gst_percent=18,
                        amount=amount,
                        received_qty=qty if status in ("received", "closed") else D(0),
                    )
                )
            gst = money(subtotal * D("0.09"))
            po.subtotal, po.taxable, po.cgst, po.sgst, po.grand_total = (
                subtotal,
                subtotal,
                gst,
                gst,
                subtotal + 2 * gst,
            )
        for p in products:
            qty = D(rng.choice([80, 150, 260, 600, 900]))
            s.add(
                StockLedger(
                    store_id=store.id,
                    product_id=p.id,
                    qty=qty,
                    unit=p.unit,
                    rate=base_rate[p.id],
                    value=money(qty * base_rate[p.id]),
                    ref_type="opening",
                    at=at(start),
                )
            )
        active = [x[0] for x in made if x[0].status == "active"]
        for k, site in enumerate(active[:6], 1):
            s.add(
                Indent(
                    code=f"DEMO-IND-{k:03d}",
                    site_id=site.id,
                    store_id=store.id,
                    status="approved",
                    required_by=day + timedelta(days=k),
                )
            )
        for k in range(1, 5):
            s.add(
                Grn(
                    code=f"DEMO-GRN-{k:03d}",
                    store_id=store.id,
                    vendor_id=rng.choice(vendors).id,
                    received_at=day - timedelta(days=k),
                    status="submitted",
                )
            )
        for k in range(1, 21):
            taxable = money(D(rng.randint(20, 400)) * 1000)
            gst = money(taxable * D("0.09"))
            due = day + timedelta(days=rng.randint(-25, 20))
            s.add(
                VendorBill(
                    number=f"DEMO-VB-{k:04d}",
                    kind="material",
                    vendor_id=rng.choice(vendors).id,
                    bill_no=f"DEMO/{k}",
                    bill_date=due - timedelta(days=30),
                    due_date=due,
                    taxable=taxable,
                    cgst=gst,
                    sgst=gst,
                    total=taxable + 2 * gst,
                    payable=taxable + 2 * gst,
                    status="approved",
                )
            )
    s.flush()
    db.commit()
    from app.analytics import summary

    summary.refresh(db)
    return counts(db)


def counts(db: Session) -> dict[str, int]:
    return dict(
        db.execute(
            select(DemoRow.table_name, func.count())
            .group_by(DemoRow.table_name)
            .order_by(DemoRow.table_name)
        ).all()
    )


# children first, so each delete only meets rows already gone
PURGE_ORDER = [
    "attendance",
    "labour",
    "dprs",
    "snags",
    "tasks",
    "area_scopes",
    "site_nodes",
    "progress_snapshots",
    "freight_entries",
    "site_costs",
    "site_budgets",
    "receipt_allocations",
    "receipts",
    "retention_releases",
    "invoice_lines",
    "tax_invoices",
    "ra_bills",
    "client_contracts",
    "grns",
    "indents",
    "po_lines",
    "purchase_orders",
    "stock_ledger",
    "vendor_bills",
    "site_members",
    "stores",
    "sites",
    "tender_revisions",
    "boq_lines",
    "leads",
    "tenders",
    "systems",
    "products",
    "vendors",
    "clients",
    "users",
]


def purge(db: Session) -> dict[str, int]:
    """Delete every row the seed inserted (and the summary rows about them).
    Returns {table: rows}."""
    done: dict[str, int] = defaultdict(int)
    keys: dict[str, list[str]] = defaultdict(list)
    for table, key in db.execute(select(DemoRow.table_name, DemoRow.row_key)):
        keys[table].append(key)
    unknown = set(keys) - set(PURGE_ORDER)
    if unknown:
        raise RuntimeError(f"Demo rows in tables the purge does not know: {sorted(unknown)}")
    db.execute(delete(MonthlySummary).where(MonthlySummary.is_demo))
    db.execute(delete(KpiSnapshot).where(KpiSnapshot.is_demo))
    for table_name in PURGE_ORDER:
        if table_name not in keys:
            continue
        if table_name == "tax_invoices":  # credit notes before the invoices they credit
            table = Base.metadata.tables[table_name]
            ids = [int(k) for k in keys[table_name]]
            q = delete(table).where(table.c.id.in_(ids), table.c.against_id.is_not(None))
            done[table_name] += db.execute(q).rowcount
        done[table_name] += _delete(db, table_name, keys[table_name])
    db.execute(delete(DemoRow))
    db.commit()
    from app.analytics import summary

    summary.refresh(db)
    return dict(done)


def _delete(db: Session, table_name: str, keys: list[str]) -> int:
    table = Base.metadata.tables[table_name]
    pk = list(table.primary_key.columns)
    total = 0
    for i in range(0, len(keys), 5000):
        chunk = keys[i : i + 5000]
        if len(pk) == 1:
            values = [_convert(pk[0], k) for k in chunk]
            total += db.execute(delete(table).where(pk[0].in_(values))).rowcount
        else:
            values = [
                tuple(_convert(c, part) for c, part in zip(pk, k.split("|"), strict=True))
                for k in chunk
            ]
            total += db.execute(delete(table).where(tuple_(*pk).in_(values))).rowcount
    return total


def _convert(column, raw: str):
    t = column.type.python_type
    if t is uuid.UUID:
        return uuid.UUID(raw)
    if t is date:
        return date.fromisoformat(raw)
    return t(raw)
