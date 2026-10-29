---
page: /measurements
title: Measurement book
routes: /measurements, /sites/:id/measurements, /sites/:id/measure, /sites/:id/reconciliation, /sites/:id/work-completions
mark: Add to the book
---
The measurement book holds every billable quantity of a site: what was measured, where, how (laser, manual, camera, AutoCAD, client certified), when and by whom. RA bills take their quantities only from here, and only the approved lines. On a site where the client approves measurements, a line is a draft until the client approves it; elsewhere a line is approved when it is written. The same section covers the site's measuring screens: **Measure** (on site, with sizes and photos), **Measure and bill** (from the drawing), **Material reconciliation** and **Work completion certificates**. Open them from the site page's tools.

**On the page (Measurement book)**
- **Site** (filter): the site whose book you see. Only your sites are listed. The first one is picked when you open the page.
- **Measure on site (L × B, ft + in, photos, sets for the client) →**: opens **Measure** for this site. {perm: closeout.billing}
- The table of contract lines: **Contract line**, **Contract** (the contract quantity), **Measured** (the approved quantity in the book), **Billed** (taken by RA bills that are submitted, certified or invoiced) and **To bill** (measured less billed, in orange when above zero).
- "No client contract on this site yet.": the site has no client contract, so there is nothing to measure against. Billing makes the contract under Client billing.
- **Add a measurement**: the form under the table, shown when the site has a contract. {perm: measurement.edit}
  - **Contract line**: the item measured. {perm: measurement.edit}
  - **Quantity**: in the line's unit. {perm: measurement.edit}
  - **Source**: **Laser**, **Manual**, **Camera**, **Client certified** or **AutoCAD**. {perm: measurement.edit}
  - **Measured on**: the date; empty means today. {perm: measurement.edit}
  - **Note**: free text. {perm: measurement.edit}
  - **Add to the book**: saves the line. It is a draft on a site where the client approves measurements, else approved at once. {perm: measurement.edit}
- **Entries**: every line, newest first: **Date**, **Item** (with its note), **Place**, **Qty**, **Source** (Camera in orange, Client certified in green) and **Measured by**.

**Measure (site page > Measure)** {perm: closeout.billing}
- The line under the title says how the site works: "Each line goes to the client for approval; bills take only approved lines." or "Lines are approved when written on this site." {perm: closeout.billing}
- **Item (its unit is the work order's)**: pick the contract line. The hint under it says how it is measured (per sqm: L x B or perimeter x height; per rmt: the running length; others: the quantity). {perm: closeout.billing}
- **Tower / block**, **Floor or flat**, **Flat or area**, **Area**: pick the place, one level at a time. {perm: closeout.billing}
- **Or the drawing's area**: shown when the site has a read drawing. Picks a traced area of the drawing (with its sqm on the drawing) and its place. {perm: closeout.billing}
- **L × B** / **Perimeter × height**: how an area item is measured. Hidden for running-metre items, which take a **Running length**. {perm: closeout.billing}
- **Length**, **Breadth**, **Perimeter**, **Height**, **Running length**: each size in **m** or **ft + in** (feet and inches are shown converted to metres under the boxes). {perm: closeout.billing}
- **Deductions (sqm)** (or **(m)** for running items): taken off the quantity. {perm: closeout.billing}
- **Quantity**: the live result in the item's unit (sqm, sqft, rmt or rft). {perm: closeout.billing}
- **Note (optional)**: added to the line's description. {perm: closeout.billing}
- **Reason, if this place is outside our RFI zones**: needed when the place is not in a zone handed to us. {perm: closeout.billing}
- **Photos (n)**: takes or picks photos; they are uploaded with the line. {perm: closeout.billing}
- **Save the line**: saves it. Greyed until an item is picked and the sizes give a quantity. A green note shows "Saved: <place> <qty> <unit>", with the zone warning if any. {perm: closeout.billing}
- **Lines (n)**: every line of the site, with its status badge (draft, sent, approved, disputed), sizes, quantity, photos, the zone reason, the client's corrections (old value struck out, new value, by whom, status) and "approved by ... (recorded by staff) · billed in <RA bill>". {perm: closeout.billing}
- Tick box on a draft or disputed line: picks it to send. {perm: closeout.billing}
- **Send n to the client**: sends the ticked lines as one set (MB-<site>-01, 02 ...). Greyed until a line is ticked. {perm: closeout.billing}
- **Pick all unsent**: ticks every draft and disputed line. {perm: closeout.billing}
- **Excel** / **PDF**: the measurement sheet of the site, with sizes, status, who approved and every correction. {perm: closeout.billing}

**Measure and bill (site page > Measure and bill, from the drawing)** {perm: billing.view}
- Needs a drawing read by AutoCAD takeoff. Without one: "No drawing read for this site". {perm: billing.view}
- **Click an area**: then click inside an outline on the drawing; its true area and periphery are taken. **Name this area** asks **Letter on the drawing**, **Name** and **Kind** (**Floor with walls (pool, tank, sunk area)** or **Slope**); **Measure it** saves it. {perm: billing.edit}
- **Trace an outline**: click the corners, then the first corner again (or double-click) to close it, then name it. {perm: billing.edit}
- **3D** / **Drawing**: switches between the drawing and a 3D view of the areas. {perm: billing.view}
- **Register**: opens the site's bill register (every RA bill in order, beside the old Excel register). **Read an old register** compares an Excel register and lists what was found (number missing, clash, out of order, wrong year, date differs). {perm: billing.view}
- **Areas** tab: each area with its area, periphery, height or slope, wall top and what is inside. Under each area not yet billed: **Pick the height on a section** (click two levels, then **Use it**), **Add numbers**, **A line's length**, **Deep end**, or for a slope **Pick the slope's line** and **Rise from two levels**; **Remove** deletes the area. {perm: billing.edit}
- **Edges** tab: each edge two areas share, answered once: **Yes, both faces**, **Open (no wall)**, **Weir or cut wall** (with **The weir's height (mm)**) or **Not a shared edge (drawn close, not one wall)**; **Save the answer** or **Later**. The first unanswered edge is asked as soon as the page opens. **A wall drawn on its own between two areas** picks two areas, then **Click on its line**. {perm: billing.edit}
- **Items** tab: for each work-order item, which parts it measures (**Floor**, **Side walls**, **Wall tops**, **Slope face**, **Count**), **Layers**, the areas it covers, and, when the order's rate is not per layer, **The order's rate is not per layer: bill** **each layer** or **the item once**. Each change saves at once. {perm: billing.edit}
- **Sheets** tab: the measurement sheets. **Measured on** and **New measurement sheet** make a draft sheet (only one draft at a time). **Bill from a slip** starts a sheet from the client's signed site slip. **Compare another way** makes a study (never sent or billed). {perm: billing.edit}
- An open sheet: its lines (click a number to find its outline), the **Abstract** (previous, on the drawing, approved by the client, this bill, up to date, WO qty) and the client's corrections. **Excel** and **PDF** download it. {perm: billing.view}
- **Work not done** / **Done after all**: on a draft sheet, leaves an area's item out of the sheet or puts it back. {perm: billing.edit}
- **Send to the client**: on a draft sheet. Greyed while questions are listed under "To answer before it can be sent". {perm: billing.edit}
- **Make the RA bill**: on an approved sheet with no bill yet. Asks **Proforma date**, **Billed against** (**The work order** or **A verbal order**, with **Confirmed by (the client's role or person)** and **Confirmed on**); **Make the proforma** makes the draft RA bill. {perm: billing.edit}
- A slip sheet: the slip's picture beside **A line, as written on the slip** (**What**, **No**, **Length**, **Width / height**, **Work-order item**, **Bill this line**, **Why it is left out**) and **Add the line**. **On the slip, not billed (n)** lists the lines left out. {perm: billing.edit}
- **Ask for a new item / variation**: on a slip line not mapped to any work-order item. Asks the description, unit and rate; **Send to the director** puts it on the Variations page. {perm: variation.request}
- The bill (opened from the sheet or the register): proforma, buyer, order, lines with work-order rates, GST, **Revisions**, **Material check** and the **Billing checklist** (each check **OK** or **Fix**). {perm: billing.view}
- **Send the bill**: on a draft bill; greyed until every check of the billing checklist is OK. It submits the RA bill to the client. {perm: billing.edit}
- **Make it the tax invoice**: on a sent bill with no invoice yet. Makes the tax invoice from the proforma's lines. {perm: billing.edit}
- **Keep the bill as it is now as a revision** and **Mark sent**: keep each version of the bill and mark the one sent to the client. {perm: billing.edit}
- **Import** tab: **Old measurement sheet (.xlsx)**, **Old proforma (.xlsx)**, **Measured on**, **Read them**. Their quantities become the "previous" of the first bill made here; rows not read are listed. {perm: billing.edit}

**Material reconciliation (site page > Material reconciliation)** {perm: closeout.billing}
- Product by product: **Issued (gross)**, **Returned**, **Net used**, **Needed** (the approved quantity × the system's consumption and wastage), **Excess / short** and **Needed from**. {perm: closeout.billing}
- **Bill period**: **The whole site**, or one bill's period. **Excel** downloads the table. {perm: closeout.billing}
- **Lines measured per running metre**: a running-metre line needs its width once, because the consumption is per sqm. **Give the width** / **Change the width** asks it in metres. Until it is given the product shows "to check: give the width". {perm: closeout.billing}
- **Return to godown**: on a product in excess. Asks the quantity (the excess is filled in). It books the return from the work into the site store and a dispatched transfer to the godown, which stores receive there. {perm: store.edit}

**Work completion certificates (site page > Work completion)** {perm: closeout.billing}
- **Completion date** and **Make the certificate**: makes a draft certificate (WCC-<year>-0001) from the approved measurements, with the areas, systems, products and the guarantee years from the work order or the quotation. {perm: closeout.billing}
- Each certificate: **Completed**, **Areas**, **Guarantee** (years and expiry) and the status (draft, or "signed by ... · locked"). **PDF** and **Guarantee bond** download it. {perm: closeout.billing}
- **Add the 3D page** / **Remove the 3D page**: on a draft, adds or leaves out a page with the building in 3D (the site needs a building model). {perm: closeout.billing}

**Rules**
- A measurement is in the unit of its contract line (the accepted work order's unit). Another unit, or L x B on a running-metre item, is refused.
- A place outside our RFI zones needs a reason before the line is saved.
- An approved line is locked: it cannot be changed or deleted. A line the client has cannot be changed until the client approves or corrects it.
- Only draft or disputed lines can be sent. Bills take only approved lines.
- On a drawing sheet, an area, item and layer is billed only once. An area that is billed has its sizes locked.
- A sheet is sent only when every question is answered (heights, slopes, shared edges, layers). The RA bill is made only from an approved sheet, and only when no other RA bill of the site is a draft.
- A bill made from a sheet is sent only when its billing checklist is all OK: rates match the work order, quantities within the work order (or an approved variation), no layer the order does not have, the signed slip attached, every slip line billed or listed with why, shared edges answered, every area linked to the drawing.
- The certificate takes only approved measurements, and every area needs a system. A signed certificate is locked; a change after that is an addendum.
- A return to the godown is at most the excess.

**What happens next**
- **Send n to the client**: the lines become "sent". The client's users who may approve measurements get "n measurement line(s) to approve: MB-...", with a link to the portal.
- The client approves or corrects each line in the portal. The site in-charge and the site's members are told of each approval or correction. An approved line counts in the book and can be billed.
- **Send to the client** on a drawing sheet: its totals go into the book as one line per item. On a site where the client approves, they are sent as a set and the sheet is "sent"; else the sheet is "approved" at once. A slip sheet is approved at once: the signed slip is the client's approval, recorded by us.
- **Make the proforma**: a draft RA bill opens below the sheet. **Send the bill** submits it: the client is told in the portal, the salesperson gets "follow up for certification" and accounts is told a receipt is expected (see Bills).
- **Make the certificate**: the client signs it in the portal; it is then locked and shows in the Guarantee register.
- **Return to godown**: a green note shows "Transfer TO-... made to <godown>"; stores receive it at the godown.

**Hands off**
- Receives: the client contract and the accepted work order (units and rates) from billing; the RFI zones from the site team; the drawing from AutoCAD takeoff; the material issued from stores.
- Passes on: sets of lines to the client to approve; approved quantities to RA bills (billing) and to labour bills (accounts); certificates to the client to sign; excess material to stores.

**When it goes wrong**
- "This place is outside our RFI zones (...): give the reason to measure it": type why in **Reason, if this place is outside our RFI zones** and save again.
- "The contract measures '...' per rmt: a measurement in sqm is refused (...)" or "... per rmt: ..., not L x B": the work order fixes the unit. Measure in that unit.
- "'...' is not a size: write it in metres (5.918) or feet and inches (19 ft 5 in)": correct the size.
- "Measurement #n (approved ...) is locked: it cannot be changed or deleted. Make a new revision or an addendum.": the line is approved. Ask the client to correct it, or measure the change as a new line.
- "The client has this line: let them approve or correct it": wait for the client's answer.
- "Line #n is sent" (or approved): only draft or disputed lines can be sent. Untick it.
- "Pick the measurement lines to send": tick at least one line.
- A line shows a pending correction from the client and never becomes approved: the app has no button yet to accept or dispute a correction. Tell the office admin.
- "That contract line is not on this site": pick another line, or refresh the page after changing the site.
- "Missing permission: billing.edit": your role may look at the drawing and the bills but not change them.
- "Send or delete the draft sheet first": a draft sheet is open. Send it or delete it before a new one.
- "Answer first: ...": answer the listed questions (heights, slopes, shared edges, layers) on the Areas, Edges or Items tab.
- "Nothing measured on this sheet": no line has a quantity; check the items' parts and the areas.
- "Area A is already billed for this item and layer on MS-...": that area is billed on an earlier sheet. Mark it **Work not done** here.
- "<sheet> is draft: the RA bill is made from an approved sheet": send the sheet and wait for the client's approval.
- "Finish (submit or cancel) the draft RA bill first": another RA bill of the site is a draft. Submit or cancel it under Client billing.
- "No accepted work order: bill against a verbal order (who confirmed it, when)": pick **A verbal order** and fill who confirmed it and when.
- "Billing checklist: ...": a check is not OK. Fix each listed item, then send again.
- "<bill> bills quantities measured only by the camera (...): give a laser or manual size, or record the client's certified quantity": camera sizes are not billed. Measure those areas by laser or by hand, or get the client's certification first.
- "No excess of that product on this site" / "The excess is n kg: return at most that": return no more than the excess shown.
- "No approved measurement on these areas: the certificate takes only approved quantities": get the measurements approved first.
- "No system for ...: give the work order line a system (its quotation line) or the area a stage template with one": the area's item has no system; ask planning to set it.
- "Give the guarantee years: neither the work order nor the quotation has them": the guarantee years are missing from the work order and the quotation.
- "This site has no building model yet: build it from the AutoCAD drawing (3D tab) first.": build the 3D model before adding the 3D page.
