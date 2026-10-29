---
page: /vendors
title: Vendors
routes: /vendors
mark: Add vendor
---
The list of everyone the company buys from or pays for work: material suppliers, labour contractors, subcontractors, transporters and others. Each vendor has its contacts, bank accounts and the products it supplies. Purchase orders, rate contracts, work orders and vendor bills all pick their vendor from this list.

**On the page**
- **Search name, city or GSTIN** (field): type and press Enter. The list shows the vendors whose name, city or GSTIN contain the text.
- **Type** (filter): **All types**, **Material supplier**, **Labour contractor**, **Subcontractor**, **Transporter** or **Other**.
- **⤓ Export Excel**: downloads the list with the same search and type filter, as an Excel file (up to the export row limit). The bank columns (account name, number, IFSC, bank) are added only for roles that may see bank details.
- **Add vendor**: opens the vendor form. {perm: vendors.edit}
- The table shows **Name**, **Type**, **City**, **GSTIN**, **Primary contact**, **Products** (how many) and **Status** (**Active** or **Inactive**). Inactive vendors are greyed.
- **Previous** / **Next**: move through the list, 25 vendors at a time.
- Click a row: opens the vendor's card.

**The vendor's card**
- The top line shows the type, the GSTIN, **Pays in n days** (the payment terms) and the city.
- **Edit details**: opens the vendor form for this vendor. {perm: vendors.edit}
- The contacts are shown as chips under the top line.
- **Products supplied (n)** (tab): each product with its **Unit**, **Last rate** and **Lead time**.
- **Edit products supplied**: turns the tab into an editable list. {perm: vendors.edit}
  - **Product** (pick from the active products), **Last rate (₹)**, **Lead time (days)**, **×** to drop a row, **+ Add product** for a new row.
  - **Save** replaces the whole list with what is on screen. **Cancel** drops the changes.
- **Bank accounts (n)** (tab): **Account name**, **Account number**, **IFSC**, **Bank / branch**. The account number and IFSC show as **hidden** unless your role may see bank details.
- **+ Add bank account**, and **Edit** / **Remove** on each account: only for a role that may both edit vendors and see company or finance settings. Others see "Bank details can be added by someone with access to company or finance settings." {perm: vendors.edit}
  - The bank form has **Account name**, **Account number**, **IFSC**, **Bank** and **Primary account**. **Save** keeps it; **Cancel** closes it.
  - **Remove** asks "Remove the ... account?" first.

**The vendor form** (Add vendor / Edit details) {perm: vendors.edit}
- **Name** (required), **Type**, **GSTIN**, **PAN**, **City**, **State**, **Payment terms (days)**, **Address**, **Notes**, **Active** (tick box). {perm: vendors.edit}
- **Contacts**: a row each with **Name**, **Designation**, **Phone**, **Email** and **Primary** (only one can be primary). **×** drops a row; **+ Add contact** adds one. A row without a name is not saved. {perm: vendors.edit}
- **Save**: creates or updates the vendor and opens its card. Saving replaces all the contacts with the rows on screen. {perm: vendors.edit}
- **Cancel**: closes the form without saving. {perm: vendors.edit}
- **Delete** (only when editing): asks "Delete vendor ... with its contacts and bank accounts?" and then removes the vendor. {perm: vendors.edit}

**Rules**
- To stop using a vendor, untick **Active** instead of deleting it. A vendor already used on a purchase order, rate contract, work order or bill cannot be deleted. {perm: vendors.edit}
- GSTIN and PAN are checked: the GSTIN must be 15 characters with the right check digit, the PAN 10 characters, and the PAN must match the PAN inside the GSTIN. {perm: vendors.edit}
- Payment terms are 0 to 365 days. They set the due date of this vendor's bills in Payables (30 days when left empty) and fill the payment terms of a new purchase order. {perm: vendors.edit}
- The first bank account added becomes the primary one. Ticking **Primary account** on another one makes it the only primary. {perm: settings.company, finance.view}
- A product can be on the list only once.
- Subcontractors are kept here with the type **Subcontractor**; the Subcontractors page only lists them.
- Every add, change and delete is kept in the audit log with who made it.

**What happens next**
- A new vendor can at once be picked on RFQs, purchase orders, rate contracts, work orders and vendor bills.
- The products supplied help pick vendors for an RFQ; the last rate is a reference only.

**Hands off**
- Receives: new vendor details from store / purchase (suppliers, transporters) and from the site and billing side (labour contractors, subcontractors).
- Passes on: the vendor to store / purchase (RFQs, purchase orders), to the director or office admin (work orders) and to accounts (bills, payments by bank).

**When it goes wrong**
- "GSTIN must look like 27AAPFU0939F1ZV (15 characters)" or "GSTIN check digit is wrong; please re-check the number": copy the GSTIN again from the vendor's invoice.
- "PAN must look like AAPFU0939F (10 characters)" or "PAN does not match the PAN inside the GSTIN": letters 3 to 12 of the GSTIN are the PAN. Fix whichever is wrong.
- "Only one contact can be primary": keep one **Primary** ticked.
- "IFSC must look like HDFC0001234 (4 letters, 0, then 6 letters/digits)" or "Account number must be 6 to 18 digits": copy them from a cancelled cheque or the vendor's letterhead.
- "A product can appear only once": remove the second row of that product.
- "Missing permission: one of settings.company, finance.view (bank details)": your role cannot change bank details. Ask accounts or the office admin.
- "It refers to a record that does not exist or was removed. Pick it from the list again." after **Delete**: the vendor is used on a purchase order, bill or work order and cannot be deleted. Edit it and untick **Active** instead.
- After **Delete** the vendor may still show in the list: reload the page.
