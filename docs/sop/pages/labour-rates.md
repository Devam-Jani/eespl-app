---
page: /labour-rates
title: Labour rates and bills
routes: /labour-rates
---
The labour contractors' piece rates, and the labour bills made from them. Labour is paid back to back with what we bill the client: a piece-rate bill takes its quantity from the client bills (the billed quantity, or the certified one when the client certified less); a gang on attendance is billed by its hours on each site. No labour quantity is typed anywhere.

**On the page**
- **Rate cards**: per contractor, each **Job**, what it **Covers**, the **Rate** (or a range) per unit, and when it is **Valid**. A card not in force today is greyed. "No rate cards yet." when there are none.
- **Labour bills**: **Bill**, **Contractor**, **Kind** (piece rate or attendance), **Period**, **Gross**, **TDS**, **Net**, **Status**. Click a row to open the bill below. {perm: payables.view}
- An open bill: each line's **Site**, **Item and job**, **Quantity from** (billed to the client, certified by the client, or hours from attendance), **Qty**, **Rate**, **Amount**; then **Gross**, the TDS and **Net payable**, and who made and approved it. {perm: payables.view}
- **Approve (vendor bill)**: on a draft bill. Approves it and makes the vendor bill for the net. {perm: payables.edit}

**New rate** {perm: subcon.edit}
- **Labour contractor**, **Job**, **Covers**, **Rate (₹) per** with the unit (sqft, sqm, rmt, nos, cum), **Up to (a range, optional)**, **Valid from**, **Valid to**. {perm: subcon.edit}
- **Add the rate**: saves the card. Greyed until the contractor, the job and the rate are given. {perm: subcon.edit}

**New labour bill** {perm: payables.edit}
- **Piece rate** / **Gang on attendance**: the kind of bill. {perm: payables.edit}
- **Labour contractor**: the contractor. {perm: payables.edit}
- Piece rate: **Site**, **From**, **To**, then a **Job** for each contract line of the site ("— not in this bill —" leaves it out). Only the contractor's rates in force are offered. {perm: payables.edit}
- Gang on attendance: **Month (hours per site from attendance)**. {perm: payables.edit}
- **Preview**: shows each line's quantity basis, quantity and amount, and the gross. Piece rate only. {perm: payables.edit}
- **Make the bill**: makes the draft labour bill and opens it. {perm: payables.edit}

**Rules**
- A piece-rate line pays the client's quantity to date (billed, or certified when less) less what was already paid to this contractor on that line, at the card's rate in the item's unit (sqft and sqm are converted).
- The rate card must be in force on the bill's end date, and be this contractor's.
- An attendance bill covers one month; only one per contractor and month.
- A bill with nothing to pay in the period is not made.
- Only a draft bill is approved.

**What happens next**
- **Approve (vendor bill)**: a vendor bill (subcontract) for the net is made, approved and due by the contractor's payment terms; accounts pays it like any bill. Each site's line counts in that site's labour cost.

**Hands off**
- Receives: the client bills and certifications (billing); attendance hours (the site).
- Passes on: approved labour bills to accounts for payment; the labour cost to each site's budget.

**When it goes wrong**
- "Unknown labour contractor": pick a contractor from the list.
- "The upper rate is below the rate": the **Up to** rate must be at least the rate.
- "Valid to is before valid from": fix the dates.
- "<job>: the rate is valid <from> to <to>": the card is not in force on the period's end. Add a new card or change the period.
- "<job> is per rmt; the client's item is per sqm": the card's unit does not fit the item. Use a card in the item's unit.
- "<job> is another contractor's rate": pick this contractor's card.
- "That item is not on this site's contract": pick the site again.
- "The period ends before it starts": fix **From** and **To**.
- "Nothing to bill in this period": nothing new was billed to the client (or all of it is paid already).
- "<bill> already bills this month": an attendance bill exists for this contractor and month.
- "<bill> is approved" (or cancelled): only a draft is approved. Refresh.
