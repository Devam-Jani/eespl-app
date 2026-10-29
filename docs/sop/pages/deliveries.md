---
page: /deliveries
title: Deliveries at site
routes: /deliveries, /deliveries/:id, /r/:token
---
Every dispatch to a site gets a delivery note: a PO delivered straight to the site store, or a
godown-to-site transfer. The note the driver carries has a QR code and a short receipt link. At site
the material is counted on that link (or on the delivery page in the app), with two photos, and the
site's stock follows the count, not what was sent.

**The list (Deliveries at site)**
- **Site** (filter): **All sites** or one site. You only see deliveries for the sites you are on,
  unless your role sees every site.
- Tabs: **All**, **Not confirmed** (with the count of open ones, e.g. **Not confirmed (3)**),
  **Short / damaged**, **Confirmed**.
- Columns: **Delivery** (the note's code and the number of items; press the code to open it),
  **Site**, **From** (the vendor, or "Godown transfer"), **Expected**, **Status** ("not confirmed",
  "confirmed", "short", "cancelled", plus a red "n discrepancy" badge and a "drop-off photo" badge
  when the driver's photo is attached), **Not confirmed for** (hours since the expected time, or
  "due" when it is not yet late) and **Received by** (with an "unlisted receiver" badge when the
  person is not the site's supervisor, in-charge or named receiver).
- A row is highlighted when it is more than 24 h past its expected time and still not confirmed.
  The hours turn red after 48 h.
- A yellow "Test links" warning means the app address is still the office PC: the QR codes open only
  there. Do not send those delivery notes to site until the public address is set.

**The delivery page**
- The header shows the code, the status, the site, the vendor or "godown transfer", the expected
  time and, when late, how many hours it has not been confirmed.
- **⤓ Delivery note (QR)**: downloads the delivery note PDF with the QR code and receipt link, to
  print or share again.
- **Driver / vehicle**: opens the driver and vehicle form, with **vehicle no**, **driver name**,
  **driver phone** and **Expected at site**. Only while the delivery is not confirmed. {perm: store.edit, po.edit}
- **Save and print again** (in that form): saves the changes, makes a new delivery note PDF with a
  new receipt link and sends the new link to the site again. The old link stops working at once. It
  does not print or download anything: press **⤓ Delivery note (QR)** to get the new PDF. {perm: store.edit, po.edit}
- **Cancel** (in that form): closes it without saving. {perm: store.edit, po.edit}
- **Driver's drop-off photo**: attach the driver's photo of the material left at site, when no one
  at site confirmed it. It proves drop-off, not quantity: the delivery stays "not confirmed". Only
  while the delivery is not confirmed. {perm: store.edit, po.edit}
- **Items**: each item with **Sent** (and the packs, e.g. drums or bags), **Received** and
  **Damaged**. A row is highlighted when less came than was sent.
- **Discrepancies**: each short or damaged quantity, once counted.
- A debit note draft against the vendor (PO deliveries only), with its lines and amount, when
  something was short or damaged.
- **Receipt**: who confirmed it, their phone, when, and an "unlisted receiver: review" badge when it
  was not the supervisor, in-charge or named receiver. GPS position when the phone gave it. The
  photos: "Material as unloaded", "Signed challan", and the driver's drop-off photo.
- **Confirm (count it yourself)**: shown when you may confirm deliveries for this site and the
  delivery is still open. {perm: delivery.confirm}
- **received** and **damaged** (for each item, in the item's unit): count it yourself; do not copy
  the sent quantity. Enter 0 for an item that did not come. {perm: delivery.confirm}
- **Photo: material as unloaded** and **Photo: signed challan**: **Take the photo** opens the
  camera. Both are needed. {perm: delivery.confirm}
- **Confirm delivery**: records your count once, under your name. The message "Confirmed: stock
  now follows your count." appears. {perm: delivery.confirm}

**The receipt link (/r/...)**
- Opened from the QR code or the short link on the delivery note, or from the link in the site's
  notification. No login. It shows only this delivery: its items and quantities, the site, the
  expected time and vehicle, never rates or values. Labels are in English, Gujarati and Hindi.
- "May receive when the supervisor is away": the site's named receiver, when one is set.
- **1. Count each item as it is unloaded**: for each item, **Sent** is shown; set **Received** and
  **Damaged** with the number box or the **−** / **+** buttons. Boxes start empty ("Not counted
  yet"). When less than sent is entered, "Less than sent: the store is told at once." appears.
- **2. Take two photos**: **Material as unloaded** and **Signed challan**. **Take photo** opens the
  camera; **Take again** replaces the photo.
- **3. Who received it**: **Your name** (needed) and **Phone**. The location is saved when the
  phone allows it.
- **Confirm delivery**: sends the count once. It shows "Sending…" while it goes, then "Thank you:
  the delivery is confirmed." Opening the link again later shows "Already confirmed by" and the name.

**Rules**
- A delivery is counted once. After it is confirmed no one can change the count, and the receipt
  link only shows who confirmed it.
- Every item must have a received count. Damaged is part of what came, so damaged cannot be more
  than received. A count more than 1.5 times what was sent is refused.
- Both photos are needed every time.
- The receipt link works until the delivery is confirmed, or for the number of days set in Site
  control settings (**Receipt link works for (days)**). Changing the driver or vehicle makes a new
  link; the old one stops working.
- A confirmation by someone who is not the site's in-charge, a site member, or the named receiver
  (matched by name or phone) is kept but marked "unlisted receiver" for review.
- The driver's drop-off photo never confirms the delivery or moves stock.

**What happens next**
- When the delivery note is made, the site in-charge and the site's members get the receipt link in
  their notifications. The site engineer and the supervisor are told the material is on the way and
  to prepare the surface (cleaning, grinding) before it arrives.
- On confirm, a PO delivery posts the GRN at once with the counted quantities (damaged quantities
  rejected). A godown transfer is completed with the good quantity; anything damaged or missing is
  written off at the site. The site's stock follows the count.
- Anything short or damaged becomes a discrepancy. The store and purchase users (and whoever raised
  the PO) are notified at once. On a PO delivery a debit note draft is started against the vendor
  at the PO rate.
- The site engineer and planning are told the material is at site and work can start on that area.
- The vendor's bill is blocked by the three-way match when it bills more than was confirmed
  received; accounts sees which delivery is still not confirmed at site.
- Not confirmed 24 h (setting) after the expected time: the site in-charge gets an alert. After 48 h
  (setting): planning (the planning user set in Site control settings, or the office admins) gets a
  high alert, which says when a drop-off photo is attached.

**Hands off**
- Receives: the delivery note from the store and purchase role, made when a PO to a site store is
  sent or a godown transfer to the site is dispatched.
- Passes on: the counted stock to the site store; the discrepancy and debit note draft to store and
  purchase; "material at site" to the site engineer and planning; the confirmed quantity to
  accounts for the vendor bill check.

**When it goes wrong**
- "This receipt link is not valid": the link is wrong, was replaced by a newer one (driver or vehicle
  changed), or the delivery was cancelled. Ask the store for the current delivery note.
- "This receipt link has expired: ask the store for a new delivery note": the link's days ran out.
  The store saves the driver / vehicle form again to make a new link.
- "Already confirmed by <name> at <date time>": someone counted it already. Open the delivery in the
  app to see the count and photos.
- "Count every item, take both photos and enter your name.": something is missing on the receipt
  link. Fill the empty boxes, take both photos, enter your name.
- "Count every item (enter 0 for an item that did not come)": an item has no received count.
- "Take both photos: the material as unloaded and the signed challan": one photo is missing.
- "Counts cannot be negative, and damaged is part of what came": damaged is more than received, or a
  number is negative. Correct it.
- "A count is far above what was sent: count again": a received count is over 1.5 times the sent
  quantity. Recount; check the unit shown next to the box.
- "Enter numbers only" or "Enter your name": correct the field and send again.
- "Too many tries: wait a few minutes and try again": the link was opened or sent too often from this
  phone. Wait, then try again.
- "No connection: try again": the phone lost signal. Nothing was saved; press **Confirm delivery**
  again when the signal is back.
- "You cannot confirm deliveries for this site": you are not on that site. Ask for the site to be
  allocated to you, or let the site's supervisor confirm.
- "Only the store can do this": changing the driver or attaching a drop-off photo is for the store.
- "<code> is already confirmed": the driver or vehicle cannot be changed after confirmation.
- "No PDF: make a new receipt link": the PDF file is missing. The store saves the driver / vehicle
  form again to make a new note.
- "Delivery not found": the delivery is not on your sites.
