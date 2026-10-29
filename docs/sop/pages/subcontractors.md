---
page: /subcontractors
title: Subcontractors
routes: /subcontractors
---
A read-only list of the subcontractors and of the work orders given to them. Subcontractors are vendors with the type **Subcontractor**: they are added and changed in Vendors, not here.

**On the page**
- **Vendors** (link in the header): opens the Vendors page, where subcontractors are added or edited (type: subcontractor).
- The first table lists every subcontractor: **Name** (with the city), **PAN**, **GSTIN**, **Bank**, **TDS** and **Work orders** (how many).
  - **Bank** shows the bank name and only the last 4 digits of the primary account.
  - **TDS** is the default rate from the PAN: 1% when the 4th letter of the PAN is P or H (an individual or HUF), 2% for everyone else, including a missing PAN.
- **Work orders**: every work order on the sites you may see, newest first: **WO**, **Site**, **Subcontractor**, **Value**, **Billable to date** and **Status** (draft, approved, active, completed or closed).
- Click the site code of a work order: opens that site on its **Work orders** tab, where the work order is made, approved and measured.

**Rules**
- Nothing can be changed on this page.
- **Billable to date** is the verified measurements times the work order rates. Measurements waiting for approval are not counted.
- The TDS shown is only the default. The work order can set its own TDS.

**What happens next**
- To give work to a subcontractor, open the site's **Work orders** tab and make the work order there.
- Their bills are entered in Payables.

**Hands off**
- Receives: the subcontractor's details from whoever keeps the vendor list.
- Passes on: nothing from this page. It is a look-up for work orders and bills.

**When it goes wrong**
- "No subcontractors yet.": no vendor has the type **Subcontractor**. Add one in Vendors with that type, or change the type of an existing vendor.
- A work order is missing: it is on a site you are not on. Ask the director or office admin.
- **TDS** looks wrong: check the PAN in Vendors. A missing or mistyped PAN gives 2%.
