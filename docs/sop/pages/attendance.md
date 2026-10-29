---
page: /attendance
title: Attendance
routes: /attendance
---
Labour attendance across your sites. **By site** shows, for one day, how many workers are posted
at each site and how many are marked present, half day or absent. **Muster roll** shows the month,
worker by worker, with the wage due. Marking itself is done on the site's labour tab.

**On the page**
- **By site** (tab): the day view. It lists the active and planned sites you can see that have
  workers posted or attendance marked.
- **Day** (field): the day to show. Today by default; future days cannot be picked.
- The table: **Site**, **Posted** (active workers posted to the site), **Present**, **Half day**,
  **Absent**, **Not marked** (posted minus marked; shown in orange when above 0). The **Total**
  row adds up the sites. If you have none: "No labour at your sites."
- Tap a site code to open that site's labour tab, where today's attendance is marked
  (**Quick mark**).
- **Muster roll** (tab): the month view for all your sites.
- **Month** (field): the month to show. This month by default.
- **Excel**: downloads the muster roll of the month as a spreadsheet: one column per day with
  P (present), H (half day) or A (absent), then days, half days, OT hours, wage and wage due.
- The muster table: **Site**, **Worker** (with the trade, or "subcontractor"), **Days** (a half
  day counts as 0.5), **Half days**, **OT h**, **Wage**, **Due**. The last row,
  **Wage due**, is the total due for the month.

**Rules**
- You only see the sites you are posted to, unless you hold labour for every site.
- Marking attendance (on the site's labour tab) needs the right to keep the labour list or to
  manage site attendance, on that site. Without either the save is refused with "Missing
  permission: labour.edit on <site code>".
- Attendance cannot be marked for a future day.
- A worker can be marked at one site only on a day.
- No overtime on an absent day.
- **Due** = days worked x the daily wage + OT hours x the OT rate. The wage and OT rate are taken
  from the worker when the day is marked, so a later wage change does not alter days already
  marked.
- A correction after the day is allowed and is kept in the audit log with who made it.

**What happens next**
- Attendance feeds the muster roll, the labour bills of attendance-paid contractors and payroll.
- A site with no attendance marked today shows "Attendance, <site>: Not marked today" on the site
  supervisor's My work, and step **1. Attendance** stays "To do" on **My site today**.

**Hands off**
- Receives: the worker list from whoever keeps **Labour** (office or site supervisor).
- Passes on: the muster roll to accounts for wages and labour bills.

**When it goes wrong**
- "Attendance cannot be marked for a future day": check the date on the phone.
- "<worker> is already marked at <site code> on <date>": the worker was marked at another site
  that day. Ask that site to correct its mark first.
- "<worker>: no overtime on an absent day": clear the OT hours or mark the worker present.
- "Mark the attendance first": a photo was added before anyone was marked for the day.
- "Missing permission: labour.edit on <site code>": you can see the site but not mark it. Ask
  the site supervisor to mark it.
- "Site not found": the site is not one of yours.
