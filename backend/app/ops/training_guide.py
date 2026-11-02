# ruff: noqa: E501
"""The training guide per role: a short PDF (under 12 pages) made from the page help texts (the
office admin's edited ones win over the defaults) and screenshots of the DEMO company, one per
page, taken fresh before each print. Roles, never names.

    python -m app.cli training-guides --screens data/training/screens --out data/training
"""

from html import escape
from pathlib import Path

from sqlalchemy.orm import Session

from app import branding
from app.timefmt import ist_today

# role -> (title, what the job does in the app, its pages in the order of a working day)
GUIDES: dict[str, tuple[str, str, list[str]]] = {
    "sales": ("Sales", "You bring in the work: enquiries, visits, quotations and tenders, and you follow them up until the order.",
              ["/my-work", "/leads", "/quotations", "/tenders", "/field", "/field/claims"]),
    "planning": ("Planning", "You turn won work into sites: the scope, the stages, who works where and when, and that every site is measured and billed.",
                 ["/my-work", "/planning/board", "/sites", "/tenders", "/work-orders", "/billing/checklist"]),
    "site_engineer": ("Site engineer", "You run your sites: the daily report, the measurements, the material you need and the issues, so the work can be billed.",
                      ["/my-work", "/field", "/sites", "/daily-reports", "/measurements", "/indents", "/snags"]),
    "site_supervisor": ("Site supervisor", "You run the day on site: who came, what was done, what arrived, and what is wrong.",
                        ["/my-work", "/field", "/daily-reports", "/attendance", "/deliveries", "/snags"]),
    "billing": ("Billing", "You turn measured work into bills: approved measurements, the billing checklist, the RA bills and their way through the client.",
                ["/my-work", "/measurements", "/billing/checklist", "/bills", "/work-orders", "/guarantees"]),
    "accounts": ("Accounts", "You keep the money right: payments received, vendor bills and payments, payroll and petty cash.",
                 ["/my-work", "/billing/payments", "/payables", "/payroll", "/petty-cash", "/dashboard"]),
    "store_purchase": ("Store and purchase", "You get the material to the sites: indents, purchase orders, receipts at the godown and on site, and the stock.",
                       ["/my-work", "/indents", "/purchase-orders", "/grns", "/stores", "/deliveries"]),
    "director": ("Director", "You see the whole company: the numbers, what is late, what waits for your approval, and who did what.",
                 ["/dashboard", "/my-work", "/planning/board", "/bills", "/issues", "/admin/audit"]),
}
TWO_STEP = {"director", "office_admin", "accounts"}


def slug(page: str) -> str:
    return page.strip("/").replace("/", "-") or "home"


def _help(db: Session, page: str, role: str) -> dict | None:
    from app.ops.routes import _help_for  # noqa: PLC0415

    return _help_for(db, page, [role])


def html(db: Session, role: str, screens: Path | None) -> str:
    title, job, pages = GUIDES[role]
    parts = [f"""<html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 14mm 14mm 16mm; @bottom-left {{ content: "{escape(branding.PRODUCT_NAME)}: {escape(title)}"; font-size: 8pt; color: #64736f; }}
        @bottom-right {{ content: "Page " counter(page) " of " counter(pages); font-size: 8pt; color: #64736f; }} }}
body {{ font-family: DejaVu Sans, sans-serif; font-size: 10pt; color: #1c2b28; line-height: 1.4; }}
h1 {{ font-size: 22pt; margin: 40mm 0 4px; color: #0f6b5c; }} h2 {{ font-size: 14pt; margin: 0 0 6px; border-bottom: 2px solid #0f6b5c; padding-bottom: 3px; }}
.muted {{ color: #64736f; }} .page {{ page-break-before: always; }} ol {{ margin: 4px 0 8px 18px; padding: 0; }} li {{ margin: 3px 0; }}
img {{ width: 100%; border: 1px solid #d5dcda; margin-top: 6px; }} .box {{ background: #eef6f4; padding: 8px 10px; margin: 8px 0; }}
.toc li {{ margin: 2px 0; }}
</style></head><body>
<h1>{escape(title)}</h1>
<p style="font-size:12pt">How to use the {escape(branding.app_title())} in your job</p>
<p>{escape(job)}</p>
<p class="muted">Prepared {ist_today():%d.%m.%Y} from the app's own help texts (the "?" at the top of each page) and the DEMO company.
Names and numbers in the pictures are invented.</p>
<h3>In this guide</h3><ol class="toc"><li>Your first day: signing in</li>"""]
    shown = [(p, _help(db, p, role)) for p in pages]
    shown = [(p, h) for p, h in shown if h]
    parts += [f"<li>{escape(h['title'])}</li>" for _, h in shown]
    parts.append("<li>When you are stuck</li></ol>")
    two = role in TWO_STEP
    parts.append(f"""<div class="page"><h2>Your first day: signing in</h2><ol>
<li>The office admin sends you a one-time link. Open it, choose your password (at least 10 characters, not a common one, not your name or email) and sign in.</li>
<li>{"Turn on two-step sign-in in My account: scan the code with an authenticator app on your phone and type the 6-digit code. After that every sign-in asks for the code." if two else "Two-step sign-in is optional for your role: you can turn it on in My account."}</li>
<li>The menu on the left shows the pages of your job, grouped by what you do. On a phone it opens from the menu button at the top.</li>
<li>After 5 wrong passwords the login waits 15 minutes; after that happens three times, the office admin unlocks you.</li>
<li>You are signed out after a time without use (12 hours on a phone, 8 hours on a computer) and on every device when you change your password.</li>
</ol><div class="box"><b>Practise first.</b> "Practise in the training company" in the menu opens the same app with the DEMO data and your own login.
Try anything there: it is reset every night and nothing reaches the real company.</div></div>""")
    for p, h in shown:
        parts.append(f'<div class="page"><h2>{escape(h["title"])}</h2><p class="muted">In the menu: {escape(_menu_label(p))}</p><ol>')
        parts += [f"<li>{escape(s)}</li>" for s in h["steps"]]
        parts.append("</ol>")
        shot = screens / role / f"{slug(p)}.png" if screens else None
        if shot and shot.exists():
            parts.append(f'<img src="{shot.resolve().as_uri()}">')
        parts.append("</div>")
    parts.append("""<div class="page"><h2>When you are stuck</h2><ol>
<li>Press "?" at the top of the page: the steps for that page, for your role.</li>
<li>My work lists everything waiting for you; a line opens the page where you act on it.</li>
<li>Try it in the training company first when you are not sure.</li>
<li>Ask your manager, or the office admin for logins, passwords, two-step and access to a page.</li>
</ol></div></body></html>""")
    return "".join(parts)


def _menu_label(page: str) -> str:
    from app.ops.roles_report import _menu  # noqa: PLC0415

    for item in _menu():
        if item["to"] == page:
            return f"{item['section']} > {item['label']}"
    return page


def pdf(db: Session, role: str, screens: Path | None) -> tuple[bytes, int]:
    from weasyprint import HTML  # noqa: PLC0415

    doc = HTML(string=html(db, role, screens)).render()
    return doc.write_pdf(), len(doc.pages)


def build_all(db: Session, screens: Path | None, out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for role in GUIDES:
        f = out / f"training-{role.replace('_', '-')}.pdf"
        data, pages = pdf(db, role, screens)
        f.write_bytes(data)
        made.append({"role": role, "file": f.name, "pages": pages, "screens": sum(1 for p in GUIDES[role][2] if screens and (screens / role / f"{slug(p)}.png").exists())})
    return made
