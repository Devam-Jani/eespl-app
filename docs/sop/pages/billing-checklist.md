---
page: /billing/checklist
title: Billing checklist
routes: /billing/checklist, /sites/:id/billing-checklist
---
The billing checklist shows, for one tower or wing of a site, every flat (rows) by area (columns), with the state of each cell: not ours, waiting for handover, to start, in progress, done, measured, approved or billed. Nothing is typed here: each cell is filled from the RFI zones, the handover, the stages, the measurement book and the bills. It is the sheet the client's billing team asks for.

**On the page (the site list)**
- The list of your sites (code and name). Click one to open its checklist. The site page's **Billing checklist** opens the same.

**A site's checklist**
- **Tower** (filter): the tower or wing. The first one is shown when you open the page.
- **Bill month** (filter): **All bills**, or "billed in <month>" to see only what the bills of that month took.
- **Excel**: downloads the checklist as it is filtered.
- The counts row: how many cells are in each state.
- The grid: **Flat**, then one column per area. Each cell shows its state:
  - "not ours (<applicator>)": the area is in an RFI zone handed to another applicator;
  - "waiting for handover": the client has not handed the area over;
  - "handed over, to start": handed over, no work yet;
  - "in progress" / "done": from the stages' progress;
  - "measured": a measurement line exists, not approved yet;
  - "approved": an approved measurement, not billed;
  - "billed in <RA bill>": taken by that bill.

**Rules**
- A cell is "not ours" only when the site has RFI zones marked; a site with no zones counts every area as ours.
- With a **Bill month** picked, an area billed in another month shows as approved.
- The cells change only when the work, the book or the bills change.

**What happens next**
- Send the Excel to the client's billing team with the RA bill, or use it to find what is approved and not billed yet.

**Hands off**
- Receives: RFI zones and handover from the site team; stages from the site; the measurement book and the bills from billing.
- Passes on: the checklist to the client's billing team.

**When it goes wrong**
- "This site has no towers or wings yet, so there is nothing to check. Add them in the site's Structure tab.": the site's places have no tower or wing. The link opens the site's **Structure** tab, where they are added.
- An area shows "billed in" a bill that was cancelled: the cancelled bill still holds its measurements. Tell the office admin.
- An area you measured shows "measured", not "approved": the client has not approved the line yet (see Measurement book).
