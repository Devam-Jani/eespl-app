---
page: /material-requests
title: Material requests
routes: /material-requests, /my-site/:id/material
mark: Approve…
---
The site's material request, in place of the phone message: the site asks by area and thickness, the
app works out the kg (or litres) and the packs from the material library and the mix design, and
checks the quantity against what the site's estimate has left. Planning approves (or changes) it and
an indent is raised. The site asks on **Ask for material** (My site → Ask for material); planning
decides on **Material requests**.

**On the page: Ask for material (on the phone)**
- Open it from My site: the **Ask for material** step ("By area and thickness: the app works out the
  kg and the bags"). **Back to my site** returns. {perm: material_request.create}
- **Material**: the materials of the site's estimate. Choosing one fills **Thickness (mm)** from its
  line or mix. {perm: material_request.create}
- **Area of the estimate** (optional): one of the estimate's areas, or **— the whole site —**. The
  request is then checked against what that area has left. Choosing an area fills **Area to do (sqm)**
  with its floor area if the box is still empty. {perm: material_request.create}
- **Area to do (sqm)**: the sqm you will do with this material. {perm: material_request.create}
- **Thickness (mm)**: shown only for a material that is part of a mix design (nodular concrete,
  plaster, brick bat); the mix's name is under it. {perm: material_request.create}
- As you type, the working shows in a box, for example "280 sqm × 10.7639 × 2.77 kg/sqft = 8,349 kg
  = 334 bags", with "The estimate has n left" (for this area, or in all). Check it before sending: it
  stops a 4,345 being sent for an 8,345. {perm: material_request.create}
- **Why more than the estimate**: appears, and must be filled, when the quantity is more than the
  estimate has left (the box turns yellow and says "this is more."). {perm: material_request.create}
- **Send to planning**: saves the request (status "Waiting for planning") and shows "<code> sent to
  planning: <working>". The form empties for the next one. The button stays grey until the working
  shows. {perm: material_request.create}
- **This site's requests**: the site's last 20 requests with code, material, status, working, date,
  area, the indent raised, and the quantity and note if planning changed it. {perm: material_request.create}

**On the page: Material requests (planning)**
- Filters: **Waiting** (not decided yet), **Over the estimate** (requests sent with a reason for more
  than the estimate) and **All**. {perm: material_request.approve}
- Columns: **Request** (code, material, date), **Site** (opens the site), **Area**, **Working** (the
  formula), **Left before** (what the estimate had left when it was asked), **Over the estimate** (a
  red "Over: <reason>" badge) and **Status**, with the changed quantity, the refusal note or the
  **Indent <code>** link (opens it on Indents). {perm: material_request.approve}
- **Approve…** (on a waiting request): opens **Approve <code>** with the working and, if it is over
  the estimate, the reason in yellow. **Quantity** (change it only with a note), **Required by**
  (optional date) and **Note (optional)**, which becomes **Why the quantity is changed** and is
  required when you change the quantity. **Approve and raise the indent** approves it and raises the
  indent. {perm: material_request.approve}
- **Refuse…** (on a waiting request): opens **Refuse <code>**. **Why it is refused** is required.
  **Refuse** refuses the request. {perm: material_request.approve}

**Rules**
- The site can ask only when its site has a material estimate. The materials and areas offered come
  from the site's latest issued estimate (if none is issued, the latest draft).
- Quantities are rounded up to a whole unit: material is ordered whole. Packs come from the pack size
  in the library.
- Over-estimate reason: if the quantity is more than the estimate has left for that material (for
  the chosen area, or for the whole site), the request is refused unless a reason is written. "Left"
  is the estimate's quantity less every earlier request for that material that was not refused
  (the approved quantity where planning changed it). Asking for all that is left, rounded up, is not
  over.
- A material with no coverage in the library cannot be asked for: planning adds the coverage first.
- Only a waiting request can be approved or refused, once.
- Planning may change the quantity on approval only with a written reason; the site sees the new
  quantity and the reason under its request.

**What happens next**
- Sent: the request shows on planning's Material requests (**Waiting**) and on planning's My work as
  "Material request <code>", marked when it is over the estimate. No other alert is sent.
- Approved: an indent is raised at once for the site's store, status submitted, with the request's
  code and working (and planning's change) in its remark and the packs on its line. The request shows
  "Approved: indent raised". The indent then goes the usual way: approval on Indents, then the
  purchase order. {perm: material_request.approve}
- Refused: the request shows "Refused" with the reason, for the site to see. The refused quantity no
  longer counts against what the estimate has left.
- The estimate's **Summary and balance** counts every request not refused under **Requested**.

**Hands off**
- Receives: requests from the site engineer and site supervisor; the estimate from planning; the
  coverages and mix designs from the Material library.
- Passes on: the approved request, as a submitted indent, to whoever approves indents (store and
  purchase, director), then the purchase order and the delivery to site.

**When it goes wrong**
- "No material estimate for this site yet": planning makes the estimate first; the materials and
  areas come from it.
- "<qty> <unit> is more than the estimate has left (<left> <unit>): say why": fill **Why more than
  the estimate** and send again.
- "<material> has no coverage in the library: planning adds it first": ask planning to add the
  coverage in the Material library.
- "<material> is not in <mix>": the mix design does not hold that material; tell planning.
- "That area is not in the site's estimate": the estimate changed; reload the page and choose again.
- "Give the area in sqm" / "Choose the material": fill the field.
- "The working could not be shown": the working failed to load; check the connection and type the
  area again.
- "Say why the quantity is changed": write the reason when you change the quantity on approval.
- "Say why it is refused": write the reason before refusing.
- "<code> is indented" or "<code> is rejected": someone already decided it; the list was out of date.
- "Request not found": the request is not on one of your sites.
