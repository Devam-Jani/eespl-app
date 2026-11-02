---
page: /billing
title: Client billing
routes: /billing
mark: New receipt
---
The client's side of the money, per site: the client contract, its RA bills (running account bills), the tax invoices and the receipts, with the ageing of what clients owe. An RA bill is made from the approved measurement book, submitted to the client, certified by them, then invoiced; the receipt settles the invoice. The same contract and bills show on the site page's Finance tab.

**On the page**
- **RA bills by site**, **Invoices**, **Receipts**, **Ageing**: the tabs.
- **New receipt**: opens "Receipt from a client". {perm: billing.edit}

**RA bills by site**
- **Site** (field): pick the site. Its contract, RA bills and invoices show below.
- "No client contract yet.": the site has none. **Make the contract from the won tender** makes it from the won tender's priced BOQ lines, then takes the accepted work order's units, rates and quantities. {perm: billing.edit}
- **Contract value** and **Terms** tiles: the client, GST %, SAC, retention %, TDS %, GST TDS %, the advance, what is left of it, and the recovery % per bill.
- **New RA bill (from the approved measurements)**: makes the next draft RA bill (RA-<site>-01, 02 ...) and opens it. Each line's quantity is suggested from the approved measurement book less what earlier bills took (never straight from progress); a quantity above the book is refused. {perm: billing.edit}
- Opened from **Raise RA bill** (Ready to bill), the page shows the site picked and the new draft bill open.
- **Extra item**: opens "Extra item beyond the BOQ" with **Description**, **Unit**, **Qty**, **Rate** and **Add**. The item is billable once approved. {perm: billing.edit}
- **Approve extra: <item>**: one button per extra item waiting; approves it. {perm: billing.approve}
- The bills table: **RA bill**, **Period to**, **Submitted**, **Certified**, **Net**, **Status** (draft, submitted, certified_by_client, rejected_by_client, certified, invoiced, cancelled) with the invoice number, and **PDF**. Click a row to open the bill.
- **Invoices**: the site's tax invoices and credit notes (see the Invoices tab).

**An RA bill (the window)**
- The status, the period, and the client's remark when they rejected or commented in the portal.
- The lines: **Item** (extra items marked "extra"), **BOQ**, **Previous**, **Suggested**, **This bill**, **Certified**, **Cumulative**, **Rate**, **Amount**. Below: gross submitted and certified, retention, advance recovery, other deduction and **Net**.
- **This bill** (field per line): the quantity billed now. Only on a draft. {perm: billing.edit}
- **Certified** (field per line): the client's certified quantity. Only on a submitted bill or one the client certified in the portal. {perm: billing.edit}
- **Other deduction (₹)** and **Reason**: on a draft or a bill being certified. **Certified by (client)**: when recording the certification. {perm: billing.edit}
- **PDF**: the bill as a PDF.
- **Save**: saves the draft's quantities and deduction. {perm: billing.edit}
- **Submit to client**: sends the draft to the client for certification. {perm: billing.edit}
- **Record certification**: saves the certified quantities typed here; the bill becomes certified. {perm: billing.edit}
- **Confirm client certification**: on a bill the client certified in the portal. Their quantity per line becomes the certified figure. Until this, their certification changes nothing in the books. {perm: billing.edit}
- **Back to draft**: on a bill the client rejected or certified in the portal and we disagree. It goes back to draft and the client's quantities are cleared. {perm: billing.edit}
- **Raise tax invoice**: on a certified bill. Makes the tax invoice from the certified lines (due in 30 days) and the bill becomes invoiced. {perm: billing.edit}
- **Cancel bill**: asks "Cancel <bill>? It keeps its number." The bill is cancelled and keeps its number. It gives back what it took: its approved measurements are free for the next bill (the billing checklist no longer shows "billed in" it), its measurement sheet can be billed again, and its Ready-to-bill items are open again. Not possible once invoiced. {perm: billing.edit}

**Invoices**
- Every tax invoice and credit note: **Number**, **Date**, **Client**, **Taxable**, **GST** (IGST, or CGST + SGST), **Total**, **Outstanding** (with the retention held), **PDF**.
- **Credit note**: on an invoice. Asks the taxable amount and the reason, then makes the credit note. {perm: billing.approve}

**Receipts**
- Every receipt: **Number**, **Date**, **Client**, **Mode** and reference, **Received**, **TDS**, **GST TDS**, and the invoices it settled. Advance and retention receipts are marked.

**Ageing**
- Per client: what is due in **0-30 days**, **31-60 days**, **61-90 days**, **90+ days** (in red), **Due** and **Retention held**, with a total row.

**Receipt from a client (New receipt)** {perm: billing.edit}
- **Client \***, **Mode** (neft, rtgs, cheque, upi, cash), **Ref / UTR / cheque no**, **Into bank**. {perm: billing.edit}
- **Received (₹)**, **Client TDS, income tax (₹)**, **GST TDS (₹)**, **Short payment / write-off (₹)**; with a write-off, **Reason for the write-off \***. {perm: billing.edit}
- **Mobilisation advance (not against invoices)**: tick it for an advance; no invoice is settled. {perm: billing.edit}
- The client's open invoices with **Outstanding**, **Due now** and **Settle**: spread the money over them. The line under shows received + TDS + GST TDS + write-off against what is spread. {perm: billing.edit}
- **Save receipt**: greyed until the full amount is spread over invoices (or it is an advance). **Cancel** closes it. {perm: billing.edit}

**Rules**
- Only one draft RA bill per contract at a time.
- A bill's quantity can never take a line beyond its BOQ quantity (bill the excess as an extra item), nor beyond the approved measurement book.
- An extra item is billed only after it is approved (billing.approve). Items approved on the Variations page are approved already.
- A draft that came from a measurement sheet is submitted only when its billing checklist is all OK.
- Certified quantities can never be more than what was submitted.
- The tax invoice is raised only on a certified bill. A bill billing camera-only sizes is not invoiced until a laser or manual size, or the client's certification, is there.
- A cancelled bill keeps its number. An invoiced bill is not cancelled: cancel its invoice with a credit note.
- A credit note is never more than what is left on the invoice.

**What happens next**
- **Submit to client**: the client's billing users are told in the portal ("<bill> submitted for certification"). The salesperson gets "follow up for certification" (after 15 days it is raised again); accounts is told a receipt is expected. The "make the stage bill" and "monthly RA bill due" to-dos of billing are closed.
- **Record certification** / **Confirm client certification**: the bill is certified; the salesperson's follow-up is closed. If certified less than billed, billing and the salesperson get "give the reason" (Bills > the bill > **Give the reason**); after 3 days the director.
- **Raise tax invoice**: the invoice shows in **Invoices** and on the bill's Payment tab. The due-date and overdue reminders start (see Bills).
- **Save receipt**: the invoices' outstanding goes down; the salesperson and the director are told a payment came in.

**Hands off**
- Receives: the approved measurement book (billing, the client); ready-to-bill stages; approved extra items and variations (director).
- Passes on: submitted bills to the client and the salesperson; certified bills and invoices to accounts; receipts to the ageing and the site's profit.

**When it goes wrong**
- "<site> already has a contract": open the existing one.
- "Finish (submit or cancel) the draft RA bill first": a draft is open. Submit or cancel it.
- "'<item>': n sqm is beyond the BOQ qty m; bill the excess as an extra item (approved with billing.approve)": lower the quantity, and add the excess with **Extra item**.
- "'<item>': n sqm is more than the measurement book (m); add the measurement first": measure and get it approved first.
- "'<item>' is an extra item not approved yet (billing.approve)": ask the director to approve it.
- "Nothing to bill": every quantity is zero.
- "Billing checklist: ...": fix each listed check on the bill under Measure and bill.
- "<bill> is <status>": the bill is no longer a draft (or not in the step the button needs). Refresh.
- "The certified qty cannot be more than the qty submitted": lower the certified quantity.
- "<bill> is <status>; a tax invoice is raised on the certified bill": record the certification first.
- "<bill> bills quantities measured only by the camera (...)": give a laser or manual size, or record the client's certified quantity.
- "The contract has no client": the site has no client; fix it on the site.
- "Spread the full n (received + TDS + GST TDS + write-off) over invoices": the amounts spread do not add up.
- "<invoice>: n is more than the m outstanding": settle no more than is owed.
- "Give the reason for the short payment / write-off": fill the reason.
- "The credit note is more than what is left on the invoice": lower the amount.
- "Missing permission: billing.edit" / "Extra items are approved with billing.approve" / "Credit notes need billing.approve": your role may not do this.
