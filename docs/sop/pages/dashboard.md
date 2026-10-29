---
page: /dashboard
title: Dashboard
routes: /dashboard, /dashboard/details, /drill
---
The dashboard greets you by role and shows four key numbers for your work, a six-month chart of the
chosen number, a site's building in 3D, what needs you today and your active sites. **More
numbers** opens the detailed dashboards (Management, Sales, My sites, Accounts, Store and purchase:
the ones your role has). Every number there opens the list of records behind it.

**On the page**
- The date at the top; "· DEMO data" is added when the numbers come from the invented DEMO company
  (the training company, or a company that has only DEMO sites yet).
- The four key numbers. Press one to show its last six months in the chart below.
  - Management: **Order book (active contracts)**, **Billed in <month> (net of GST)**, **Overdue over 60 days**, **Sites on track** ("n of m"). {perm: dashboard.company}
  - Site roles: **My active sites**, **Average progress**, **Daily reports not sent today** ("Send them before 8 pm"), **Open snags**. These numbers have no month history. {perm: dashboard.site}
  - Other dashboards: the first four tiles of your own dashboard. {perm: dashboard.sales, dashboard.finance, dashboard.purchase}
- The chart card: "Last 6 months · tap a number above to switch". **More numbers** opens the
  detailed dashboards. A number without history shows "This number has no month-by-month history."
- **Live building · <site>**: the 3D building of a site with its progress.
  - **Site shown in 3D** (field): shown when more than one of your sites has a 3D building.
  - **Rooms first**: shows the rooms before the outer shell; press again to switch back.
  - **Open the site →**: opens the site on its 3D tab.
  - "No building in 3D yet": the site's building has not been made from its drawing (Site > 3D
    building).
- **Needs you today** with "n open": up to six quick decisions.
  - Labour claim above measured: **Pay measured** or **Pay claimed**. {perm: closeout.claim_approve}
  - Payment overdue on a bill: **Follow up** opens the bill's follow-up tab. {perm: closeout.billing, closeout.payments}
  - Quotation follow-up overdue: **Open** opens the quotation. {perm: quotation.view}
  - **Later**: hides the line for the rest of today in this browser.
  - Press the title of a line to open its page.
  - "Nothing waits on you" with the link "Everything on your list is under Approvals" (My work).
- **Active sites**: your active sites. Filters **All**, **Late**, **Billing due**. Columns **Site**,
  **Work done** (bar and %), **Status**, **Billed of order** (only for roles that see amounts) and
  **Next step**. Press a row to open the site.

**More numbers (/dashboard/details)**
- The title is the dashboard shown. "Summary tables as of <time> · the worker refreshes them every
  night".
- One tab per dashboard your role has, when you have more than one.
- **Demo company** (tick box): switches every number to the invented DEMO company; a "DEMO company: invented data" badge shows. {perm: dashboard.company}
- **↻ Refresh**: rebuilds the summary tables now ("Refreshed as of <time>."). Use it after big
  changes during the day; the worker also does it every night.
- **⤓ Excel**: downloads the dashboard shown as a spreadsheet. {perm: reports.export}
- **⤓ PDF summary**: on the Management dashboard only, downloads the management summary as a PDF. {perm: reports.export}
- Each tile: its value, the change against the previous period ("▲ / ▼ ... vs <period>"), "On
  target" / "Below target" when a target is set, and its "as of" time. Press a tile to open the
  records behind it.
- The small **⤓** on a tile downloads those records. {perm: reports.export}
- **Management**: **Delays: the client's and ours** (per site; press a site for its handover tab), **Sites in 3D**, then the sections **Order book**, **Receivables**, **Payables**, **Sites** and **Site control**, and the **Alerts** list on the side (**All alerts →**). {perm: dashboard.company}
- **Margin**: the margin tiles and "The five sites with the lowest margin"; press a bar to open the site. Staff salary is included only for roles that see payroll. {perm: tender.margin}
- **Sales**: the sales tiles, **My quotation follow-ups** (or **Quotation follow-ups** for the whole team) due this week with the overdue ones marked, **All quotations →**, and **My pipeline by stage** (or **Pipeline by stage**): press a bar for its leads or tenders. **Funnel and win / loss →** opens Strategy. {perm: dashboard.sales}
- **My sites**: one card per active site with its to-dos: ✓ done, ! still to do (DPR today, attendance marked, steps waiting for inspection, open snags, indents awaiting delivery). Press a to-do to open it. {perm: dashboard.site}
- **Accounts**: the accounts tiles and **Receivables ageing (due part, retention excluded)**: press a bar for the invoices in it. **Cash flow, DSO and outstanding by client →** opens Finance analytics. {perm: dashboard.finance}
- **Store and purchase**: the purchase tiles, **POs awaiting delivery** (a **late** badge when past the expected date) and **Below reorder level**. {perm: dashboard.purchase}

**The records behind a number (/drill)**
- **← Back** returns to the dashboard. The title names the list; "n record(s)" below it.
- **⤓ Excel**: downloads the list. {perm: reports.export}

**Rules**
- Each dashboard needs its own right. Sales people see their own numbers only; site roles see only
  their sites.
- Cost and margin numbers are shown only to roles that see margins.
- The numbers come from summary tables refreshed every night and by **↻ Refresh**. The key
  numbers on the first page are read live.
- **Pay measured** / **Pay claimed** wait 6 seconds with an **Undo** button before they are sent. Press **Undo** to cancel. {perm: closeout.claim_approve}
- **Pay measured** pays the measured quantity; **Pay claimed** approves the higher claimed quantity. Either decides the claim; the reason is recorded as "decided from the dashboard". {perm: closeout.claim_approve}
- **Later** is only for this browser and today. Tomorrow the line comes back if it is still open.

**What happens next**
- A decided labour claim leaves **Needs you today**, its pay quantity is fixed for billing, and the director's "Approve or refuse" to-do on My work closes. {perm: closeout.claim_approve}
- Red and late items are also in Alerts and on My work.

**Hands off**
- Receives: the figures every other role's work produces (bills, receipts, reports, POs, claims).
- Passes on: your decisions from **Needs you today** to billing (labour claims) and the follow-up on
  bills.

**When it goes wrong**
- "The dashboard could not be loaded.": the server did not answer. Reload the page.
- "Missing permission: reports.export": your role cannot download. Ask for the export from a role
  that can.
- "Cost and margin need tender.margin": the list shows cost or margin, which your role does not see.
- "Unknown list": the link to the records is old. Go back and press the tile again.
- A number looks old: press **↻ Refresh** on More numbers and check the "as of" time.
- "Claim #n is not waiting for the director": it was already decided (perhaps from the site's
  labour claims page). Reload the dashboard.
- A **Pay measured** / **Pay claimed** failed: the error shows as a message and the line comes back. Open the site's labour claims page to decide it there. {perm: closeout.claim_approve}
