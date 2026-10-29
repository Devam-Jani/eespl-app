---
page: /sales/work-orders
title: Client work orders
routes: /sales/work-orders
---
Each client work order is checked against our accepted quotation before we sign it. The list shows
the work orders you may see: a salesperson sees those of their own quotations, their sites, or that
they made. Click the code to open the work order and work through its deviations.

**On the list**
- **Work order**: the code; click it to open the work order.
- **Client's ref**: the client's own work order number.
- **Quotation**: our quotation and revision it is checked against.
- **Open deviations**: how many differences are still to be decided.
- **Status**: **checking** (yellow) or **accepted · locked** (green).
- **New work order**: enters the client's work order when it comes. {perm: wo.edit}
  - **Our won quotation**: pick your won quotation (only won quotations are listed). {perm: wo.edit}
  - **Client's work order number**: the client's own reference. {perm: wo.edit}
  - **The client's work order file (optional)**: the client's PDF or Excel, read at once into the lines and the terms. {perm: wo.edit}
  - **Make the work order**: makes it and opens it. {perm: wo.edit}

**On a work order**
- The header: the client's ref, the status, our quotation, and where the lines came from ("read from" the file, or copied from our quotation, or "not yet").
- **Upload the work order (PDF / Excel)**: reads the client's file (.pdf, .xlsx, .xlsm) into the lines and the payment terms. {perm: wo.edit}
- **Copy lines from our quotation**: takes the lines from our quotation instead of a file. {perm: wo.edit}
- **Compare with our offer**: lists every difference from our offer: item missing, item added, quantity, rate, unit, discontinued product, scope, payment term, retention, advance, penalty, time limit. {perm: wo.edit}
- **Deviations from our offer (n, m open)**: each difference with **Our offer** and **The work order**.
- **Accept**: asks "Why we accept it" (filled "Accepted") and marks the deviation accepted. {perm: wo.edit}
- **Ask the client to amend**: asks "What to ask the client (note)". The deviation turns "asked to amend" and the text to send shows under it ("To send: ..."). The salesperson gets a to-do: "Work order ...: ... Send the client: ...". {perm: wo.edit}
- **Work order accepted**: enabled only when no deviation is open ("Resolve every deviation first"). It locks the work order, and its lines then set the unit, rate and quantity of the site's contract lines, which the measurement book, the RA bills and the certificate use. {perm: wo.edit}
- **Payment and terms (structured)**: payment days and basis, retention, advance, guarantee, penalty, time limit, and the scope on us and on the client, as read from the work order.
- **Edit terms**: types or corrects those terms (payment days and what they count from, retention and its release, advance, guarantee years, time limit, penalty, scope on us and on the client). An empty box clears the term. **Save the terms**, then **Compare with our offer** again. {perm: wo.edit}
- **Lines (n)**: the work order's lines with unit, qty and rate.
- **Work orders** (the link at the top): back to this list.

**Rules**
- Every deviation must be accepted or sent back for amendment before the work order can be accepted.
- An accepted work order is locked for every role. A correction is a new revision or an addendum.
- Each answer needs a note.

**What happens next**
- Send the amendment text to the client. When the amended work order comes, upload it and compare again.
- Once accepted, billing works from the work order's rates and quantities.

**Hands off**
- Receives: the client's work order after a quotation is won.
- Passes on: the accepted work order to billing (contract lines, RA bills).

**When it goes wrong**
- "Work order not found": it is not on your quotations or sites.
- "Link the accepted quotation first": the work order has no quotation linked; ask the administrator.
- "Write a note": give a note when you accept or ask to amend (pressing Cancel or leaving it empty does nothing).
- "n deviation(s) still open: accept each or ask the client to amend it".
- "The work order has no lines": upload the file or **Copy lines from our quotation** first.
- "Work order ... (accepted) is locked: it cannot be changed or deleted. Make a new revision or an addendum."
- "Missing permission: wo.edit": you may see the work order but not work it.
- "QTN-... is sent: a work order is entered against a won quotation": mark the quotation won first.
- "Quotation not found" on **Make the work order**: the quotation is not yours.
