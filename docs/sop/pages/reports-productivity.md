---
page: /reports/productivity
title: Labour productivity
routes: /reports/productivity
mark: ⤓ Excel
---
**Labour productivity** compares the man-days from attendance with the sqm the contractor's work measured, per site, contractor and month, against the expected sqm per man-day of the system. Below the table are the expected figures per system.

**On the page**
- **⤓ Excel**: downloads the table as an Excel file ("labour-productivity").
- The table: **Site**, **Contractor**, **Month**, **Man-days**, **Sqm done**, **Sqm / man-day**, **Expected**, **Check**. A row with a low check is shown in red.
- **Check** shows "productivity low" (red), "ok" (green), "to be set" (no expected figure for the system yet) or "no attendance" (sqm measured but no man-days marked).
- **Expected sqm per man-day** (list): one box per active system, showing the sqm one man-day should do. "to be set" when empty.
- Typing a figure in a box and leaving it saves it for that system. Emptying the box clears it. The change is written to the audit log. {perm: settings.company}
- For other roles the boxes are greyed out and cannot be changed.

**Rules**
- A row is "productivity low" when the sqm per man-day is more than the productivity drop % (20 % by default, in the site control settings) below the expected figure.
- A subcontractor bill flagged "productivity low" needs an override with a note (at least 5 characters) before it can be approved. Billing is asked to check the bill; the director is asked to decide when it is flagged.
- Rejected measurements are not counted.
- The table lists the measured work of the sites you may open: every site for roles that see all sites, your own sites otherwise.

**What happens next**
- A figure set here is used for every later check of that system, on this page and on the subcontractor bills.

**Hands off**
- Receives: attendance from the site supervisors, measured work from billing.
- Passes on: low-productivity bills to billing and the director (decision on the bill, in payables).

**When it goes wrong**
- "No measured work yet.": no work order measurement exists yet.
- "Missing permission: settings.company": only management can set the expected figures.
- A figure of 0 or less is refused: give a positive number, or leave the box empty.
