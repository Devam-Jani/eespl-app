# ruff: noqa: E501
"""Settings > Roles report: for each role, every page in its menu and every action it may take, in
plain words with how far it reaches (all sites, their sites, their own), and what the role never
sees (costs and margins, salaries, other people's routes ...). Exported to PDF for the director to
sign off before go-live. The pages come from the app's menu (menu.json, kept equal to the
frontend's menu by its test)."""

import json
from datetime import date
from html import escape
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Permission, Role

MENU = Path(__file__).with_name("menu.json")
SCOPE = {"all": "all sites / everyone", "assigned": "their own sites", "own": "only their own"}
# what a role may never see unless it holds one of these
NEVER = [
    ("Costs, purchase rates and margins", ("tender.margin", "knowledge.cost")),
    ("Salaries, wages and payroll", ("payroll.view", "payroll.edit")),
    ("Vendor bills and payments", ("payables.view", "payables.edit")),
    ("Company accounts: invoices, receipts, Tally", ("finance.view", "finance.export")),
    ("Other people's routes and travel claims", ("field.team", "field.claims_approve")),
    ("Site budgets against actuals", ("budget.view",)),
    ("The audit log", ("audit.view",)),
    ("Users, roles and permissions", ("admin.users", "admin.roles")),
    ("Backups, storage and the server's health", ("system.ops",)),
]
ORDER = ["director", "office_admin", "planning", "sales", "estimator", "site_engineer", "site_supervisor", "billing", "accounts", "store_purchase", "site_receiver", "super_admin", "client"]


def _menu() -> list[dict]:
    return json.loads(MENU.read_text(encoding="utf-8")) if MENU.exists() else []


def _holder(have: dict[str, str]):
    return lambda *codes: any(c in have for c in codes)


def report(db: Session) -> list[dict]:
    perms = {p.code: p for p in db.scalars(select(Permission))}
    menu = _menu()
    out = []
    roles = sorted(db.scalars(select(Role)), key=lambda r: ORDER.index(r.code) if r.code in ORDER else 99)
    for r in roles:
        have = {rp.permission_code: rp.scope for rp in r.permissions}
        can = _holder(have)
        groups: dict[str, list[str]] = {}
        for item in menu:
            if can(*item["perms"]) and all(c in have for c in item.get("all", [])) and not any(c in have for c in item.get("none", [])):
                groups.setdefault(item["section"], []).append(item["label"])
        actions: dict[str, list[dict]] = {}
        for code, scope in sorted(have.items()):
            p = perms.get(code)
            actions.setdefault(p.module if p else "other", []).append({"code": code, "what": p.description if p else code, "reach": SCOPE.get(scope, scope)})
        never = [label for label, codes in NEVER if not can(*codes)]
        out.append({"code": r.code, "name": r.name, "pages": groups, "actions": actions, "never": never, "count": len(have)})
    return out


def html(db: Session) -> str:
    rows = report(db)
    parts = [f"""<html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 16mm 14mm; @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font-size: 8pt; color: #666; }} }}
body {{ font-family: DejaVu Sans, sans-serif; font-size: 9pt; color: #1c2b28; }}
h1 {{ font-size: 16pt; margin: 0 0 4px; }} h2 {{ font-size: 12pt; margin: 14px 0 4px; border-bottom: 2px solid #0f6b5c; padding-bottom: 2px; page-break-after: avoid; }}
h3 {{ font-size: 9.5pt; margin: 8px 0 2px; color: #0f6b5c; }} .muted {{ color: #64736f; }} table {{ width: 100%; border-collapse: collapse; }}
td {{ border-bottom: 1px solid #e1e6e4; padding: 2px 4px; vertical-align: top; }} .never {{ background: #fff4d6; padding: 4px 6px; margin: 4px 0; }}
.role {{ page-break-inside: auto; }} .sign {{ margin-top: 30px; }} .sign td {{ border: 0; padding-top: 34px; }}
</style></head><body>
<h1>Who sees what: roles for go-live</h1>
<p class="muted">Every role's pages and actions in the EESPL App, and what each role never sees. Prepared {date.today():%d.%m.%Y} for the director's sign-off.
People get roles in Users; one person may hold more than one role (they then see what each role gives). A client login sees only the client portal of its own sites.</p>"""]
    for r in rows:
        parts.append(f'<div class="role"><h2>{escape(r["name"])} <span class="muted">({escape(r["code"])}, {r["count"]} permissions)</span></h2>')
        if r["never"]:
            parts.append('<div class="never"><b>Never sees:</b> ' + escape("; ".join(r["never"])) + "</div>")
        if r["pages"]:
            parts.append("<h3>Pages in the menu</h3><table>" + "".join(f"<tr><td style='width:22%'><b>{escape(g)}</b></td><td>{escape(', '.join(items))}</td></tr>" for g, items in r["pages"].items()) + "</table>")
        elif r["code"] == "client":
            parts.append("<p>No staff pages: the client portal only (its own sites, as its client role allows).</p>")
        parts.append("<h3>What the role may do</h3><table>")
        for module, acts in sorted(r["actions"].items()):
            parts.append("".join(f"<tr><td style='width:22%' class='muted'>{escape(module)}</td><td>{escape(a['what'])}</td><td style='width:20%' class='muted'>{escape(a['reach'])}</td></tr>" for a in acts))
        parts.append("</table></div>")
    parts.append("""<table class="sign"><tr><td>Approved for go-live by the director:<br><br>____________________________</td>
<td>Date:<br><br>______________</td><td>Office admin:<br><br>____________________________</td></tr></table></body></html>""")
    return "".join(parts)


def pdf(db: Session) -> bytes:
    from weasyprint import HTML  # noqa: PLC0415

    return HTML(string=html(db)).write_pdf()
