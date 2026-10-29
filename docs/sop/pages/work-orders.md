---
page: /work-orders
title: Client work orders
routes: /work-orders, /work-orders/:id
---
The client's work orders, each checked against our accepted quotation before we sign it. Every difference (an item missing or added, a unit, rate or quantity, scope, payment, retention, advance, penalty, time limit, a discontinued product) is listed as a deviation and resolved. When none is open, the work order is accepted and locked: from then on its units, rates and quantities rule the client contract, the measurement book, the RA bills and the certificate.

**On the page (the list)**
- **Work order** (click to open it), **Client's ref**, **Quotation** (code and revision), **Open deviations**, **Status** ("accepted · locked" or "checking").
- From a tender or a site, the list shows only that tender's or site's work orders.
- The page has no button to make a work order; a work order with no row here has to be made by the office admin.

**One work order (/work-orders/:id)**
- The title shows the client's reference and "accepted · locked" or "checking". The line under it: the quotation it is checked against, and where the lines came from ("read from <file>", quotation, typed, or "not yet").
- **Upload the work order (PDF / Excel)**: reads the client's file. The lines read replace the work order's lines (when any are read), and payment, retention, advance, guarantee and other terms found in the text fill the terms still empty. {perm: wo.edit}
- **Copy lines from our quotation**: copies our quotation's lines (not the client-scope ones) as the work order's lines. {perm: wo.edit}
- **Compare with our offer**: lists the deviations from our quotation again. A deviation already resolved stays resolved while it is still there. {perm: wo.edit}
- **Work order accepted**: accepts and locks it. Greyed while a deviation is open ("Resolve every deviation first"). {perm: wo.edit}
- **Deviations from our offer (n, m open)**: **Kind** (red while open, orange when the client is asked to amend, green when accepted), **What**, **Our offer**, **The work order** and **Resolution**.
- **Accept**: asks "Why we accept it" (filled with "Accepted") and accepts the deviation. {perm: wo.edit}
- **Ask the client to amend**: asks "What to ask the client (note)". The deviation shows "asked to amend" with the text to send ("To send: Please amend the work order ..."). {perm: wo.edit}
- **Payment and terms (structured)**: payment days and basis, retention (and its release), advance, guarantee years, penalty, time limit, and the scope on us and on the client.
- **Lines (n)**: each line with its unit, quantity and rate.
- On an accepted work order the buttons are gone: it is locked.

**Rules**
- Every deviation must be accepted or sent for amendment before the work order is accepted. A resolution needs a note.
- A work order with no lines cannot be accepted.
- Accepted means locked, for every role: no upload, copy, compare, resolve or delete. A correction is a new revision or an addendum.
- On acceptance, each work-order line gives the matching contract line (by the quotation line, else by the wording) its unit, rate and quantity. A contract made later takes them too.
- Comparing needs the accepted quotation linked to the work order.

**What happens next**
- **Ask the client to amend**: the salesperson gets "Work order <wo>: <topic>. Send the client: <text>" with a link to the work order.
- **Work order accepted**: the units and rates are locked into the client contract. Measurements in another unit are refused from then on; RA bills and proformas use the work order's rates; the guarantee years come from it.

**Hands off**
- Receives: the client's work order (file) and our accepted quotation from sales.
- Passes on: amendments to ask to the salesperson; the locked units and rates to billing (measurement book, RA bills) and to the site.

**When it goes wrong**
- "n deviation(s) still open: accept each or ask the client to amend it": resolve every open deviation first.
- "The work order has no lines": upload the work order or copy the lines from our quotation.
- "Link the accepted quotation first": the work order has no quotation. Ask the office admin to link it.
- "Work order <code> (accepted) is locked: it cannot be changed or deleted. Make a new revision or an addendum.": it is accepted.
- "Write a note": the resolution needs a note.
- The upload reads no lines (the lines stay "not yet"): the file is a scan or an unusual layout. Copy the lines from our quotation and compare.
- No work order to open: the page cannot make one. Ask the office admin.
