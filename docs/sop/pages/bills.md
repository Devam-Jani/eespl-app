---
page: /bills
title: Bills
routes: /bills, /bills/:id, /bill-tracking, /billing/tracking
---
Every RA bill (running account bill) of your sites, each with one page for its whole story: the quantities billed and certified by the client, its steps at the client, and the payment. The bill itself is made, submitted and certified under Client billing (or Measure and bill); this page follows it from submission to the last receipt. The old links (bill tracking) open this page.

**On the page (the list)**
- **Search bills** (field): filters by bill code, site or invoice number.
- **Bill**: the RA bill code (RA-<site>-01 ...), with the tax invoice number under it. Click it to open the bill.
- **Site**, **With the client at** (the last step marked, or "not tracked yet"), **Outstanding** (on the invoice) and **Due** (with a red "n d overdue" badge when late).
- Cancelled bills are not listed. From a site page, **Bills** shows that site's bills only.

**One bill (/bills/:id)**
- The title shows the code and a red "n days overdue" badge when late. The line under it: "Invoice ... of <date>" or "Not invoiced yet", the due date with how it was worked out, and where the bill is at the client.
- **Quantities** tab: each item with **Rate**, **Billed** (quantity and amount), **Certified** (quantity and amount), **Difference** (in red when the client cut it) and **Reason**. The **Total** row shows who at the client certified it and when.
- **Give the reason**: on a line the client certified differently, with no reason yet. Asks why (at least 3 characters) and saves it on the line. {perm: billing.edit}
- **The client's copy**: downloads the client's signed certification or email, when one was attached. {perm: billing.view}
- **Record certification**: on a bill that is submitted (or certified by the client in the portal). Opens "<bill>: the client's certification": {perm: billing.edit}
  - **Approved at the client by** (name, designation), **Date**, **Certified amount (₹)**, **Signed copy or email** (**Choose the file**: PDF, image or email file), and the **Certified** quantity of each line (the billed quantity is filled in). {perm: billing.edit}
  - **Record certification** saves it; **Cancel** closes the form. {perm: billing.edit}
- **Steps at the client** tab: the client's billing cycle (the days bills reach the site and head office, and the payment days), then six steps: **Prepared**, **Submitted at site**, **Signed by the client's PM**, **Sent to head office**, **With the client's accounts**, **Paid**. A step done shows its date, who marked it, "signed copy" and the days it stayed there.
- **Mark today**: marks that step done today. {perm: closeout.billing}
- **Upload the signed copy**: on **Signed by the client's PM**. Pick the photo or PDF of the signed bill; the step is marked today with the file. {perm: closeout.billing}
- **Payment** tab: **Due and received** (the due date and how it was worked out; invoice total, received, outstanding; each receipt with its number, date and amount) and **Follow-ups** (each call: date, who, what was said, the promised date).
- **Who you spoke to**, **What was said**, **Promised date** and **Log the call**: adds a call to the follow-ups. {perm: closeout.payments}

**Rules**
- Steps go forward only. A step cannot be dated before the step before it. Steps may be skipped.
- **Signed by the client's PM** needs the signed copy: it is our proof when a bill goes missing.
- A certified quantity can never be more than the quantity billed. Certification needs the client's signed copy or email.
- The certification is recorded only on a submitted bill (or one the client certified in the portal). After it, the bill is certified and can be invoiced under Client billing.
- The due date is the work order's payment term (after the invoice or after the certification), else the client's billing cycle, else the invoice's own due date. A bill with no invoice has no due date.
- Who you spoke to and what was said need at least 2 characters each.
- Amounts here are selling amounts only; costs are never shown.

**What happens next**
- **Record certification**: the bill becomes certified. The salesperson's "follow up for certification" to-do is closed. If the client certified less than billed, billing and the salesperson get "Client certified less than billed: give the reason"; after 3 days it goes to the director. **Give the reason** closes it.
- Every day the app checks the steps and the payment:
  - a bill not submitted at site by the end of the client's billing window: billing gets "Submit it or it waits a month", the salesperson is told;
  - a bill at one step for 7 days: the salesperson gets "Follow it up with the client"; 3 days later the director is told;
  - on the due date: accounts gets "Payment due"; 5 days late: the salesperson gets "Call the client"; 30 days late: the director, with the salesperson and the site engineer told;
  - on a promised date logged with a call: accounts gets "Check it came in".
- When accounts enters the receipt against the invoice, it shows under **Payment**; the salesperson and the director are told a payment came in.

**Hands off**
- Receives: submitted RA bills from billing (Client billing or Measure and bill); receipts from accounts.
- Passes on: the certification to accounts (for the invoice and the receipt); the follow-up to the salesperson; the payment calls to accounts and the director.

**When it goes wrong**
- "The bill is already at '<step>'": a later step is marked. Steps cannot go back.
- "A step cannot be dated before the step before it": the earlier step has a later date. Mark the steps in order.
- "Upload the signed copy: it is our proof when a bill goes missing": use **Upload the signed copy**, not a plain mark.
- "Attach the client's signed copy or email": choose the file before **Record certification**.
- "<bill> is draft; it must be sent first": submit the bill under Client billing first.
- "The certified qty cannot be more than the qty billed": lower the certified quantity.
- "Billing or the site's salesperson records it": your role may not record it on this site.
- **Record certification** is missing: the bill is not submitted, or it is already certified.
- "Bill not found": the bill was cancelled or is on a site you may not see.
- **Due** looks wrong: the term comes from the client's work order, else the client's billing cycle, else the invoice. Fix it there.
