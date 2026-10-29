---
page: /labour
title: Labour
routes: /labour
mark: Add worker
---
The list of active workers (own labour and subcontractor labour) at your sites: trade, where they
are posted, daily wage, overtime rate and the last 4 digits of the Aadhaar number. Attendance and
wages are worked out from these details.

**On the page**
- **Search name or phone** (field): filters the list as you type.
- The table: **Name** (with the phone), **Trade**, **Type** ("Own", or the subcontractor's name),
  **Posted at** (the site code, or "—"), **Wage**, **OT / h**, **Aadhaar** (••••1234, or "—").
  Only active workers are listed.
- **Add worker**: opens **Add a worker**. {perm: labour.edit}
- Tap a worker's row: opens **Edit <name>** with the same fields. {perm: labour.edit}

**The worker form** {perm: labour.edit}
- **Name \***: required. {perm: labour.edit}
- **Phone**. {perm: labour.edit}
- **Trade**: applicator, helper, mason, supervisor or other. {perm: labour.edit}
- **Type**: **Own labour** or **From a subcontractor**. {perm: labour.edit}
- **Subcontractor \***: shown for **From a subcontractor**; pick the subcontractor. {perm: labour.edit}
- **Posted at**: the site the worker works at, from the sites you keep labour for, or "— not posted —". {perm: labour.edit}
- **Daily wage (₹)** and **OT rate per hour (₹)**: empty counts as 0. {perm: labour.edit}
- **Aadhaar (last 4 digits)**: type the number or its last 4 digits; only the last 4 are kept. When editing, the label shows the ones kept now; leave it empty to keep them. {perm: labour.edit}
- **Save**: saves the worker. **Cancel**: closes without saving. {perm: labour.edit}

**Rules**
- A worker saved with "— not posted —" is posted to no site ("Posted at" shows "—"). On the site's
  labour tab (**Workers** view) the form has no site field: the worker goes to that site.
- Roles that keep labour only for their own sites must pick one of their sites in **Posted at**:
  without it the save is refused with "Post the worker to one of your sites". {perm: labour.edit}
- The full Aadhaar number is never stored, not even in the audit log.
- A wage change counts from the next day marked; days already marked keep their wage.
- Changes are kept in the audit log.

**What happens next**
- A worker posted to a site appears in that site's **Quick mark** and is counted in **Posted** on
  **Attendance**.

**Hands off**
- Receives: new workers from the site supervisor or the subcontractor.
- Passes on: the worker list for daily attendance; wages to the muster roll, labour bills and
  payroll.

**When it goes wrong**
- "Pick the subcontractor this worker comes from": **From a subcontractor** is chosen but no
  subcontractor is picked. {perm: labour.edit}
- "Own labour has no subcontractor": the type is own labour but a subcontractor is set. {perm: labour.edit}
- The Aadhaar field asks for "at least the last 4 digits of the Aadhaar number": fewer than 4 digits were typed. {perm: labour.edit}
- "Post the worker to one of your sites": you keep labour only for your sites. Add the worker from the site's labour tab instead. {perm: labour.edit}
- "Worker not found": the worker is not at one of your sites.
