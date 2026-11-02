# ruff: noqa: E501
"""The product's name and tag line, and the company line: the ONE place they are written. The
sidebar, the login page, the browser tab, the phone's home-screen app (manifest), PDF and Excel
footers, emails and the SOPs all read them from here (the frontend through GET /api/ops/mode), so
a rename is a change of one line. The company details are public facts only (no address, GSTIN
or bank: those are the Company settings)."""

PRODUCT_NAME = "EESPL"
PRODUCT_TAG = "Ethios Enviro Solutions · Site & Tender app"
COMPANY_LINE = "Ethios Group · construction chemicals and waterproofing · Bronco, Durowhite, Damshield · ISO 9001:2015"


def app_title() -> str:
    """'EESPL Site & Tender app': the product as one phrase, for emails and documents."""
    return f"{PRODUCT_NAME} {PRODUCT_TAG.split(' · ')[-1]}"


def as_dict() -> dict:
    return {
        "product_name": PRODUCT_NAME,
        "product_tag": PRODUCT_TAG,
        "company_line": COMPANY_LINE,
        "app_title": app_title(),
    }


def pdf_footer_css() -> str:
    """Added after a PDF's own CSS: the company line bottom left, the page number moved right."""
    line = COMPANY_LINE.replace('"', "'")
    return (
        f'\n@page {{ @bottom-left {{ content: "{line}"; font-family: "DejaVu Sans"; font-size: 6.5pt; color: #777; }}'
        " @bottom-center { content: none; }"
        ' @bottom-right { content: "Page " counter(page) " of " counter(pages); font-family: "DejaVu Sans"; font-size: 7.5pt; color: #555; } }\n'
    )
