# ruff: noqa: E501
"""Prompt 39, Part 1: we have not built an ERP. The word never reaches a person: no string in the
backend (PDFs, Excel, emails, help texts), no SOP or doc, and the name and tag come from one place
(app/branding.py) through /api/ops/mode and the home-screen manifest."""

import re
from pathlib import Path

from app import branding
from app.ops import help as help_texts
from app.ops import sop

ERP = re.compile(r"\bERP\b", re.I)
APP = Path(__file__).parents[1] / "app"


def test_no_backend_string_says_erp():
    found = [
        f"{p.relative_to(APP)}:{i}"
        for p in APP.rglob("*.py")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if ERP.search(line)
    ]
    assert found == []


def test_no_help_text_or_sop_says_erp():
    assert [k for k, v in help_texts.DEFAULTS.items() if ERP.search(str(v))] == []
    docs = sop.sop_dir()
    assert [
        str(p.name) for p in docs.rglob("*.md") if ERP.search(p.read_text(encoding="utf-8"))
    ] == []
    repo = APP.parents[1]
    for extra in (repo / "README.md", repo / "docs"):
        if extra.exists():  # the repo checkout (CI); the dev container mounts backend only
            files = [extra] if extra.is_file() else list(extra.rglob("*.md"))
            assert [str(p) for p in files if ERP.search(p.read_text(encoding="utf-8"))] == []


def test_the_name_and_tag_come_from_one_place(client):
    m = client.get("/api/ops/mode").json()
    assert m["product_name"] == branding.PRODUCT_NAME and m["product_tag"] == branding.PRODUCT_TAG
    assert not ERP.search(m["product_tag"]) and "Site & Tender app" in m["product_tag"]
    man = client.get("/api/manifest.webmanifest")
    assert man.status_code == 200 and man.headers["content-type"].startswith(
        "application/manifest+json"
    )
    j = man.json()
    assert (
        j["short_name"] == branding.PRODUCT_NAME
        and j["description"] == branding.PRODUCT_TAG
        and not ERP.search(str(j))
    )
    assert client.get("/api/app-icon.svg").headers["content-type"].startswith("image/svg+xml")


def test_pdfs_and_excel_carry_the_company_line():
    from app.execution.pdf import CSS
    from app.export import xlsx_bytes

    assert branding.COMPANY_LINE in CSS and "ISO 9001:2015" in branding.COMPANY_LINE
    import io

    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes("x", ["A"], [[1]])))
    assert branding.COMPANY_LINE in wb.active.oddFooter.left.text
