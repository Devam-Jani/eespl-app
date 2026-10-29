---
page: /analytics/labour
title: Labour analytics
routes: /analytics/labour
---
**Labour analytics** shows the man-days worked from the muster roll (attendance), the attendance rate per site and the labour cost per sqm done.

**On the page**
- **From**, **To** (dates), **Region**, **Site status** (filters). Empty dates: the 12 months up to today.
- **Demo company (invented data)** (tick box): shows the training company's invented data. Only shown when demo data exists. {perm: dashboard.company}
- **⤓ Excel**: downloads every table of the page as one Excel file. Written to the audit log. {perm: reports.export}
- **Man-days per month, all sites** (chart).
- **Attendance rate** (chart): man-days / attendance rows marked, per site (present 1, half day 0.5, absent 0).
- **Labour cost per sqm done** (chart): the 15 highest sites. Labour cost is muster-roll wages plus verified subcontract measurements; area is the sqm scopes times their progress.
- **Man-days per site per month** (table): first 15 rows, **Show all n** for the rest. A half day counts 0.5. Own labour and subcontractor labour on the muster roll both count.

**Rules**
- The cost per sqm shows cost. Without tender.margin it stays empty with the note "Needs tender.margin (it shows cost)."

**What happens next**
- Nothing is changed from this page.

**Hands off**
- Receives: attendance marked on site; subcontract measurements verified by billing.
- Passes on: a site with low attendance or a high cost per sqm, to its site engineer and planning.

**When it goes wrong**
- "Missing permission: dashboard.company or dashboard.site": your role cannot open this page.
- "Nothing in this range.": no attendance between the dates.
