---
page: /estimates
title: Material estimates
routes: /estimates, /estimates/:id, /estimates/:id/drawing
mark: New estimate
---
How much of each material a site needs, worked out from the site's measured drawing and the material
library: area × coverage × (1 + wastage) = quantity, then packs, per area and in total. The estimate
is what the site's material requests are checked against. You see the estimates of the sites you
cover.

**On the page: the list**
- Filters: **All**, **Draft** and **Missed areas** (estimates with measured areas that are neither in
  them nor excluded).
- Columns: **Estimate** (its code), **Title**, **Site**, **Status** (draft or issued) and **Missed
  areas** (a red count). Press a row to open the estimate.
- **New estimate**: opens **New material estimate**. Type in **Find the site** (code or name), choose
  the **Site**, give a **Title** (for example "Terrace waterproofing") and the **Upturn (mm)** on the
  walls round each area (300 by default). **Make the estimate** creates it as a draft and brings in
  every area measured on the site's drawing (Measure and bill, or the AutoCAD takeoff). It then opens
  the estimate. {perm: estimate.edit}

**On the page: one estimate**
- The header: code and title, the site, the upturn and the status badge.
- **Excel** and **PDF**: download the estimate.
- **Read an old planning sheet**: choose an .xlsx or .xlsm planning sheet. The app reads it against
  this site's drawing and the library and shows **What <file> says**: each finding, the areas in the
  sheet against the drawing (with the difference), the coverages in the sheet against the library,
  and figures typed as text that no total adds. Nothing is saved or changed.
- **Issue**: issues the estimate (status issued) at once, with no question asked. Its areas and lines
  can then no longer be changed. {perm: estimate.edit}
- The red or yellow box at the top lists the warnings: measured areas not in the estimate, and
  materials with no coverage in the library ("the estimate is not complete").
- **Measured areas not in the estimate** (card, only when there are some): each missed area with its
  sqm, periphery and where it was measured.
- **Add to the estimate** (on a missed area): brings that one area in. {perm: estimate.edit}
- **Exclude…** (on a missed area): opens **Leave out <area>**. Write **Why it is left out** (for
  example the client's own scope, not in this work order) and press **Exclude**. {perm: estimate.edit}
- **Areas** (card): every area of the estimate, with "n in · n excluded". Columns **Code**, **Area**,
  **Floor (sqm)**, **Cut-outs (sqm)**, **Periphery (m)**, **Upturn (mm)**, **Floor**, **Upturn** and
  **In the estimate**. An area lying inside another comes in as "Misc: ... (cut out of ...)" under it:
  its floor is taken off the host's floor and only its upturn counts. Press an area name to see it on
  the drawing.
- **Upturn (mm)** (per area): type a different upturn for that area; it is saved when you leave the
  box. Empty means the estimate's own upturn. {perm: estimate.edit}
- **Floor** and **Upturn** (tick boxes per area): whether the area's floor and its upturn count.
  Saved at once. {perm: estimate.edit}
- **Exclude…** (on an included area): the same **Leave out** form; the area stays listed, greyed, with
  its reason. {perm: estimate.edit}
- **Put back** (on an excluded area): brings it back into the estimate. {perm: estimate.edit}
- **Materials** (card): one card per material line, with its system, where it goes and its areas, and
  the working "sqm × coverage × (1 + wastage %) = quantity → packs". **Show the n area(s)** /
  **Hide the n area(s)** opens the quantity and working per area.
- **Add a material**: opens the line form. **Material** (from the library; its coverages and wastage
  are shown under it), **System** (the coverage for that system, else the product's any-system one),
  **Mix design** (only for a material that is part of a mix: the quantity then comes from the mix at
  the thickness, not from the coverage), **Thickness (mm)** (when a mix is chosen), **Where it goes**
  (**Floor and upturn**, **Floor only**, **Upturn only**), **Note**, and **Areas**: **All the areas in
  the estimate** or **Chosen areas** (tick them). **Save** adds the line. {perm: estimate.edit}
- **Edit** / **Delete** (on a material line): change the line, or remove it after the question
  "Delete <material>?". {perm: estimate.edit}
- **Summary and balance** (card): per material **Needed**, **Packs**, **Requested** (what the site
  asked for, not refused), **Sent** (to the site's store), **Used** and **Left**. Used = sent to the
  site's store − returned − still in stock. Left = needed − used; a negative left is shown in red.

**On the page: the drawing (/estimates/:id/drawing)**
- Opened from an area name in the estimate. It shows the site's measured drawing, read only: drag to
  pan, wheel to zoom, press an area to pick it.
- **Measured areas** (list): every measured area with its sqm and a badge: **In the estimate**, **Left
  out** (with the reason) or **Not in the estimate**.
- **Open in Measure and bill**: shown only to those who can see the site's billing; opens the same
  area in Measure and bill.
- Nothing on this page changes the drawing or the estimate.

**Rules**
- Every measured area must be in the estimate or excluded with a reason (at least 3 characters).
  The estimate cannot be issued while one is missed.
- An estimate with no material line cannot be issued.
- Only a draft can be changed. Once issued, no one can change its areas or lines: make a new estimate.
  The quantities still follow the material library, so a coverage or wastage changed later changes
  them.
- A material with no coverage in the library shows "No coverage in the library for <material>: the
  quantity is not worked out" and the estimate is marked not complete. Planning adds the coverage in
  the Material library.
- The site's material requests use the site's latest issued estimate; if none is issued, the latest
  draft.
- Over-estimate reason: when the site asks for more of a material than the estimate has left (for
  the chosen area, or for the whole site), the request needs a written reason. "Left" is the
  estimate's quantity less everything already asked for and not refused (the approved quantity where
  planning changed it). Asking for exactly what is left, rounded up to a whole unit, is not over.
  Such a request is marked "Over the estimate" for planning, who approves or refuses it.

**What happens next**
- The site can ask for material against the estimate from My site → Ask for material, and the
  **Summary and balance** fills as requests, deliveries and stock come in.
- No one is notified when an estimate is made or issued.

**Hands off**
- Receives: the measured areas from billing (Measure and bill) or the AutoCAD takeoff, and the
  coverages from the Material library.
- Passes on: the estimate to the site engineer and supervisor (their material requests are checked
  against it) and to planning (approving those requests).

**When it goes wrong**
- "Put these measured areas in the estimate or exclude them with a reason first: ...": press **Add to
  the estimate** or **Exclude…** on each area listed, then **Issue** again.
- "Add the materials first": add at least one material line before issuing.
- "<code> is issued: make a new one to change it": the estimate is frozen; make a new estimate.
- "Say why the area is left out": write the reason before pressing **Exclude**.
- "That area is not measured on this site, or is in the estimate already": the page was out of date;
  reload it.
- "A tender's estimate takes its areas typed in (no site drawing yet)": the estimate has no site, so
  there is no drawing to take areas from.
- "That product is not in the mix design": choose a mix the material belongs to, or no mix.
- "This estimate has no site, so no drawing": the drawing page only works for a site's estimate.
- "No drawing read for this site": billing has not uploaded and measured the DWG yet.
- "The file could not be read as a workbook: ...": the old sheet is not a readable .xlsx or .xlsm.
- "No area yet": nothing is measured on the site's drawing; billing measures it first, then press
  **Add to the estimate** on the missed areas.
