# ruff: noqa: E501
"""The project's slip bills, numbering, register, revisions and material check, replayed in the
training company from the billing team's folder (gitignored data/) and check.json beside it:

1. a site with the order's items (rates as billed) and the systems' coverage;
2. the folder read: each bill file's number, dates and version; the old register (Excel) read and
   matched; what was found (numbers missing or used twice, dates out of order or in another year,
   bills missing from the register);
3. the bills before the app (RA 0 to RA 6) kept as imported bills, each with its versions from the
   folder as revisions (one marked sent);
4. the site store's figures for the material check;
5. the slips: each attached, its lines entered as the billing team's sheet has them, mapped to the
   order's items; sent (the signed slip is the client's approval) and billed, numbered by the app
   in order; the 21.10.2026 slip kept as a draft;
6. each slip bill against the billing team's Excel, and the material check of the last one.
"""

import shutil
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.finance import service as svc
from app.measure import bill as mb
from app.measure import excel, register, slip
from app.measure.realcheck import _user, files
from app.timefmt import ist_today

D = Decimal


def _site(db: Session, cfg: dict, user) -> tuple:
    from app.closeout.models import ClientWorkOrder, ClientWorkOrderLine
    from app.finance.models import ClientContract, ContractLine
    from app.masters.models import Client, Product, System, SystemComponent
    from app.measure.demo import reset
    from app.sites.models import Site

    cl = db.scalar(select(Client).where(Client.name == cfg["client"]))
    if cl is None:
        cl = Client(name=cfg["client"], type="other", state="Gujarat", notes="Training: the billing team's real project, replayed")
        db.add(cl)
        db.flush()
    site = db.scalar(select(Site).where(Site.code == cfg["site_code"]))
    if site is None:
        site = Site(code=cfg["site_code"], name=cfg["site"], state="Gujarat", status="active", client_id=cl.id)
        db.add(site)
        db.flush()
    else:
        reset(db, site.id)
        from sqlalchemy import text

        from app.closeout.demo import _purge

        for table in ("register_imports", "stores"):
            ids = list(db.scalars(text(f'select id from "{table}" where site_id = :s'), {"s": site.id}))
            if table == "stores" and ids:
                db.execute(text("delete from stock_ledger where store_id = any(:i)"), {"i": ids})
            _purge(db, table, ids, set())
    systems = {}
    for key, s in cfg["systems"].items():
        p = db.scalar(select(Product).where(Product.name == s["product"]))
        if p is None:
            p = Product(code=f"TRN-{key.upper()}-P"[:30], name=s["product"], unit="kg")
            db.add(p)
            db.flush()
        sy = db.scalar(select(System).where(System.name == s["name"]))
        if sy is None:
            sy = System(code=f"TRN-{key.upper()}"[:30], name=s["name"], unit="sqm")
            db.add(sy)
            db.flush()
            db.add(SystemComponent(system_id=sy.id, product_id=p.id, consumption_per_unit=D(s["coverage"]), wastage_percent=D(0)))
        systems[key] = sy.id
    wo = ClientWorkOrder(code=f"CWO-{cfg['site_code']}", client_ref="Verbal order", site_id=site.id, client_id=cl.id, lines_from="typed", status="accepted")
    for i, it in enumerate(cfg["items"]):
        wo.lines.append(ClientWorkOrderLine(sort_order=i, item_no=it["no"], description=it["description"], unit=it["unit"], qty=D(100000), rate=D(it["rate"]),
                                            system_id=systems.get(it.get("system"))))  # fmt: skip
    db.add(wo)
    db.flush()
    c = ClientContract(site_id=site.id, client_id=cl.id, contract_value=D(0), retention_percent=D(0), place_of_supply="Gujarat", created_by=user.id)
    for w in wo.lines:
        c.lines.append(ContractLine(sort_order=w.sort_order, item_no=w.item_no, description=w.description, unit=w.unit, qty=w.qty, rate=w.rate, wo_line_id=w.id))
    db.add(c)
    db.flush()
    return site, wo, c


def _old_bills(db: Session, site, c, imp, first_app_ra: int, user, base: Path) -> list[dict]:
    """The bills before the app, as imported bills (their basic as billed), each with its versions
    from the folder as revisions: oldest first, the bill's own file (not "not for invoice") sent."""
    from app.finance.models import RaBill

    fs = imp.files
    regs = {r.get("ra"): r for r in imp.rows if r.get("ra") is not None}
    out = []
    mains = sorted((f for f in fs if f["kind"] == "xlsx" and f.get("basic") and f["version"] != "not for invoice" and (f["ra"] if f["ra"] is not None else f["folder_ra"]) is not None
                    and (f["ra"] if f["ra"] is not None else f["folder_ra"]) < first_app_ra), key=lambda f: f["ra"])  # fmt: skip
    for f in mains:
        n = f["ra"] if f["ra"] is not None else f["folder_ra"]
        reg = regs.get(n)
        made = date.fromisoformat(f["bill_date"]) if f.get("bill_date") else date.fromisoformat(f["name_date"]) if f.get("name_date") else None
        b = RaBill(code=f"RA-{site.code}-{n:02d}", contract_id=c.id, site_id=site.id, seq=n, period_to=made or ist_today(), status="invoiced" if reg and "TAX" in (reg.get("status") or "").upper() else "submitted",
                   gross=D(f["basic"]), certified_gross=D(f["basic"]), net=D(f["basic"]), imported=True, remark=f"Imported from {Path(f['file']).name}", created_by=user.id)  # fmt: skip
        db.add(b)
        db.flush()
        subj = f["subject"]
        versions = [v for v in fs if v["kind"] == "xlsx" and v.get("basic") and v["subject"] and v["subject"] == subj]  # the same bill: the same subject
        versions.sort(key=lambda v: (v.get("bill_date") or v.get("name_date") or "", v["file"] == f["file"]))
        sent = None
        for v in versions:
            rows = _lines(base / v["file"])
            r = register.add_revision(db, b, label=f"{v['version'] or 'version'}: {Path(v['file']).name}"[:200], source=v["file"][:300],
                                      made_on=date.fromisoformat(v["bill_date"]) if v.get("bill_date") else None, user_id=user.id, lines=rows,
                                      basic=D(v["basic"]), gst=svc.money(D(v["basic"]) * D("0.18")), total=D(v["grand"] or 0))  # fmt: skip
            if v["file"] == f["file"]:
                sent = r
        if reg and all(abs(D(reg["basic"]) - D(v["basic"])) > 1 for v in versions):
            register.add_revision(db, b, label="as listed in the old register", source="the old register", made_on=date.fromisoformat(reg["date"]) if reg.get("date") else None,
                                  user_id=user.id, lines=[], basic=D(reg["basic"]), gst=D(reg["total"] or 0) - D(reg["basic"]) if reg.get("total") else D(0), total=D(reg["total"] or 0))  # fmt: skip
        if sent is not None:
            register.mark_sent(db, b, sent)
        out.append({"ra": n, "code": b.code, "basic": D(f["basic"]), "versions": len(versions) + (1 if reg and all(abs(D(reg["basic"]) - D(v["basic"])) > 1 for v in versions) else 0),
                    "in_old_register": reg is not None})  # fmt: skip
    return out


def _lines(path: Path) -> list[dict]:
    try:
        pro = excel.read_proforma(path.read_bytes())
    except (ValueError, OSError):
        return []
    return [{"item_no": k, "description": (v.get("description") or "")[:120], "unit": v.get("unit"), "qty": str(v["qty"]), "rate": str(v["rate"]), "amount": str(v.get("amount") or 0)}
            for k, v in pro["items"].items()]  # fmt: skip


def _stores(db: Session, site, cfg: dict) -> None:
    from app.masters.models import Product
    from app.material.models import StockLedger, Store

    s = cfg["stores"]
    store = Store(name=f"{site.code} site store", kind="site", site_id=site.id)
    db.add(store)
    db.flush()
    p = db.scalar(select(Product).where(Product.name == s["product"]))
    at = datetime.combine(date.fromisoformat(s["on"]), time(12)).astimezone()
    for ref, q in (("transfer_in", D(s["sent"])), ("transfer_out", -D(s["returned"])), ("issue", -D(s["used"]))):
        db.add(StockLedger(store_id=store.id, product_id=p.id, qty=q, unit=s["unit"], rate=D(0), value=D(0), ref_type=ref, note="Training: as on the billing team's reconciliation sheet", at=at))
    db.flush()


def run(db: Session, folder: Path) -> dict:
    from app.config import settings
    from app.finance.models import RaBill

    _, _, root = files(folder)
    cfg = root["billing"]
    base = folder / root.get("folder", ".")
    user = _user(db)
    site, wo, c = _site(db, cfg, user)
    wl = {w.item_no: w for w in wo.lines}
    reg_file = next(iter(sorted(base.glob(cfg["register_glob"]))), None)
    imp = register.import_folder(db, site, base, reg_file, user.id)
    old = _old_bills(db, site, c, imp, cfg["first_app_ra"], user, base)
    _stores(db, site, cfg)
    db.commit()
    slips = []
    for sp in cfg["slips"]:
        f = next(iter(sorted(base.glob(sp["file_glob"]))), None)
        s = slip.new(db, site, measured_on=date.fromisoformat(sp["measured_on"]), title=sp["title"], slip_path=None, slip_name=f.name if f else None,
                     slip_on=date.fromisoformat(sp["slip_on"]), signed_by=sp["signed_by"], signed_on=date.fromisoformat(sp["signed_on"]), user_id=user.id)  # fmt: skip
        if f is not None:
            rel = f"sites/{site.id}/slips/{s.code}{f.suffix.lower()}"
            dst = Path(settings.media_dir) / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dst)
            s.slip_path = rel
        for p, no, length, width, item in sp["lines"]:
            slip.add_line(db, s, particulars=p, no=no, length=length, width=width, wo_line_id=wl[item].id if item else None)
        db.commit()
        row = {"key": sp["key"], "sheet": s.code, "sheet_id": s.id, "unbilled": slip.unmapped(db, s), "lines": len(sp["lines"])}
        if sp["do"] == "bill":
            mb.send(db, s, user)
            b, warns = mb.bill_from_sheet(db, s, user, proforma_on=date.fromisoformat(sp["proforma_on"]), basis="verbal", verbal_by=sp["signed_by"], verbal_on=date.fromisoformat(sp["signed_on"]))
            old = register.old_number(sp["key"])
            if old is not None and old != b.seq:  # the folder's RA 16 is the app's RA 8: the old number stays with it
                b.old_no = f"RA {old}"
            register.mark_sent(db, b, register.add_revision(db, b, label="made from the slip", source="the app", made_on=b.proforma_on, user_id=user.id))
            checks = mb.checklist(db, b)
            if all(x["ok"] for x in checks):
                b.status, b.submitted_at = "submitted", svc.now()  # sent: the next slip's bill can follow
            p = mb.proforma(db, b)
            row |= {"ra": b.seq, "code": b.code, "proforma": b.proforma_no, "checklist_ok": all(x["ok"] for x in checks),
                    "lines": {ln["item_no"]: ln["this"] for ln in p["lines"]}, "basic": D(p["tax"]["taxable"]), "grand": D(p["tax"]["total"]), "their": sp.get("their"), "warnings": warns}  # fmt: skip
            # the billing team's Excel, read back: its quantities and amounts
            xl = next(iter(sorted(base.glob(sp["excel_glob"]))), None)
            if xl is not None:
                pro = excel.read_proforma(xl.read_bytes())
                row["excel"] = {"items": {k: str(v["qty"]) for k, v in pro["items"].items()}, "basic": svc.money(pro["basic"]) if pro["basic"] is not None else None,
                                "grand": svc.money(pro["grand"]) if pro["grand"] is not None else None}  # fmt: skip
        db.commit()
        slips.append(row)
    last = db.scalar(select(RaBill).where(RaBill.site_id == site.id, RaBill.imported.is_(False)).order_by(RaBill.seq.desc()).limit(1))
    material = register.material_check(db, last) if last else None
    db.commit()
    return {"site_id": site.id, "register": imp.id, "findings": imp.findings, "old_register": imp.rows, "old_bills": old, "slips": slips, "material": material,
            "app_register": register.site_register(db, site.id)["bills"]}
