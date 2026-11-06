---
page: /sites/:id/drawing-quote
title: Make quotation from drawing
routes: /sites/:id/drawing-quote
mark: Make the quotation
---
From the architect's drawing (read in the takeoff, its areas mapped to the site's places and area types) to a draft quotation and its rate working, every quantity traceable to the drawing. Nothing is sent to the client from here: the quotation is a draft, and the usual send checks apply.

**On the page: the drawing and the client**
- **Drawing revision**: the site's drawings read for areas, with how many of their areas are mapped. **Client** (the site's by default) and **Quote in** (sqm, or sq ft converted once × 10.7639). **Start** opens a run; **Earlier runs** opens one.
- **Check against the drawing**: per plan, its areas, how many are mapped and their sqm (and the plan's own area from the building model); the labels not mapped and the closed shapes that are no area and no cut-out, so nothing is silently left out.

**A run**
- One card per area type with its quantity in sqm and sq ft, and per area: **Floor**, **Cut-outs** (shafts, ducts inside it), **Upturn** (the area's own from the drawing, else its type's, else the system's, else the default; hover to see which), **Sunk** (its side walls instead of an upturn), **Total sqm** and **How** the sum is worked ("Terrace: (300.00 − 4.00 cut-outs) floor + 78.00 rmt × 0.30 upturn = 319.40 sqm").
- **Key points** of the area type, and **The client's BOQ or spec line for it**: its words rank the options too.
- The options of every brand with their checks (✓ meets, ✗ does not, ? not stated in TDS); the area type's default system is ticked. Tick one or more (two options for the terrace are two options of the item); **Add any other product** with its consumption per sqm; **Leave this area type out** asks why.
- **Areas not mapped**: map them in the takeoff, or **Leave out** with a reason (**take back** puts one back). While an area is not mapped, or an area type has nothing ticked, the reasons show above and **Make the quotation** waits.
- **Make the quotation**: a draft quotation (its items the area types, its lines the ticked options with the drawing's quantities) and its rate working (consumption, wastage, prices with freight, labour, margin on the selling price); the working's rates go onto the lines. On a newer revision of the drawing it makes the next revision of that quotation and lists **What the new drawing revision changed** per line (old and new quantity, the areas added, removed or resized). **Open the draft quotation** opens it.
- **Review**: every cell (quantity, consumption, wastage) can be changed; a changed cell says "changed by user" with who and when, and **back to calculated** sets it back. The rate follows. **Price**, **freight**, **labour** and **margin** are shown and changed only by roles that see costs. {perm: tender.margin, consumption.cost}
- Click a row of the review to light its areas **On the drawing** and **In 3D**.
- **3D picture for the cover**: downloads a picture of the building for the quotation's cover.
