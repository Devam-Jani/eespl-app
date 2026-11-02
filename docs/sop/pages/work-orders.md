---
page: /work-orders
title: Client work orders
routes: /work-orders, /work-orders/:id
---
The client's work orders, each checked against our accepted quotation before we sign it. Every difference (an item missing or added, a unit, rate or quantity, scope, payment, retention, advance, penalty, time limit, a discontinued product) is listed as a deviation and resolved. When none is open, the work order is accepted and locked: from then on its units, rates and quantities rule the client contract, the measurement book, the RA bills and the certificate.

**On the page (the list)**
- **Work order** (click to open it), **Client's ref**, **Quotation** (code and revision), **Open deviations**, **Status** ("accepted · locked" or "checking").
- From a tender or a site, the list shows only that tender's or site's work orders.
- **New work order**: enters the client's work order. {perm: wo.edit}
  - **Our won quotation**: pick the quotation the work order is for. Only won quotations are listed (a salesperson sees their own). {perm: wo.edit}
  - **Client's work order number**: the client's own reference. {perm: wo.edit}
  - **The client's work order file (optional)**: the client's PDF or Excel; it is read at once (lines and terms). {perm: wo.edit}
  - **Make the work order**: makes it (CWO-...) and opens it. From a tender's or a site's list, it is linked to that tender or site; else to the quotation's. {perm: wo.edit}

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
- **Edit terms**: types or corrects the terms: **Client's work order number**, **Payment within (days)**, **Counted from** (the invoice, the certification or the final bill), **Retention (%)**, **Retention released**, **Advance (%)**, **Guarantee (years)**, **Time limit (days)**, **Penalty**, **On us** and **On the client** (a comma between items). An empty box clears the term. **Save the terms** saves them; press **Compare with our offer** again after a change. {perm: wo.edit}
- **Lines (n)**: each line with its unit, quantity and rate.
- The **Work orders** link at the top goes back to the list in your menu (Billing, or Sales for a salesperson).
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
- The upload reads no lines (the lines stay "not yet"): the file is a scan, damaged or an unusual layout. Copy the lines from our quotation, type the terms with **Edit terms** and compare.
- "QTN-... is sent: a work order is entered against a won quotation": the quotation is not won yet. Mark it won first.
- "Quotation not found": a salesperson can enter a work order only for their own quotation (or a site they are on).
- "The work order is made, but its file was not read: ...": the work order is there; upload the file again from the work order (a .pdf, .xlsx or .xlsm under 15 MB).
