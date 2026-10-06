"""Writes small invented Powerplay-style exports to tests/fixtures/powerplay/ (no real data).
Layouts follow what Powerplay's screens show (Material Name / Additional Specification,
Vendor / Category, Member / Role), with a title block above the header row.

Run from backend/:  python tests/fixtures/make_powerplay_fixtures.py
"""

from pathlib import Path

from openpyxl import Workbook

HERE = Path(__file__).parent / "powerplay"

MATERIALS = [
    ["Material list"],
    [],
    ["Material Name", "Category", "UOM", "Additional Specification", "In Stock"],
    ["SIKA EMACO S348", "SIKA", "kg", None, 0],
    ["MASTER SEAL M645", "MASTERSEAL", "KGS", "Brand: MASTERSEAL", 0],
    ["Non Woven Geotextile - 120 GSM", "OTHERS", "SQM", None, 0],
    ["master seal  m645", "MASTERSEAL", "kg", None, 5],  # duplicate (case, spacing)
    ["Breaker Panu", None, "nos", None, 0],
    ["Test Bundle Item", "OTHERS", "bundle", None, 0],  # unknown unit
    [None, "OTHERS", "kg", None, 0],  # no name
    ["Zz Soft Wiper", "CONSUMABLE", "Nos", "Brand: 3M, Colour: white", 0],
    ["Acme Primer", None, "Ltr", "Category: Primer; Brand: Acme Coatings", 0],
]

VENDORS = [
    ["Vendor list", None, "exported"],
    ["Vendor", "Category", "GSTIN", "Contact Person", "Phone", "Email", "City",
     "Account Number", "IFSC", "Bank Name"],
    ["Ramesh Traders", "Material", "27AAPFU0939F1ZV", "Ramesh", 9800000001,
     "ramesh@example.com", "Ahmedabad", "123456789012", "HDFC0001234", "HDFC Bank"],
    ["ramesh  traders", "Material", None, None, None, None, None, None, None, None],
    ["Sample Waterproofing Contractor", "Labour", "27ABC", "Suresh", 9800000002, None,
     "Surat", None, None, None],
    ["Swift Transport", "Transporter", None, "Mahesh", 9800000003, "not-an-email", "Vadodara",
     "987654321", "HDFC1234", "HDFC Bank"],
    [None, "Material", None, None, None, None, None, None, None, None],
]  # fmt: skip

TEAM = [
    ["Member", "Phone", "Email", "Invitation Status", "Role"],
    ["Powerplay Support", 8000000000, "support@getpowerplay.in", "Accepted", "Admin"],
    ["Asha Patel", 9000000001, "Asha.Patel@example.com", "Accepted", "Project Manager"],
    ["Ravi Kumar", 9000000002, None, "Accepted", "Sr. Supervisor - Site"],
    ["ASHA PATEL", 9000000001, "asha.patel@example.com", "Accepted", "Project Manager"],
    ["Neha Shah", 9000000003, "not-an-email", "Pending", "Jr. Engineer - Billing"],
    [None, None, None, None, None],
]


def write(name: str, rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = name.title()
    for row in rows:
        ws.append(row)
    wb.save(HERE / f"{name}.xlsx")


def main() -> None:
    HERE.mkdir(exist_ok=True)
    write("materials", MATERIALS)
    write("vendors", VENDORS)
    write("team", TEAM)


if __name__ == "__main__":
    main()
