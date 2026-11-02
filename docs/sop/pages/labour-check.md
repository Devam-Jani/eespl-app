---
page: /labour-check
title: Labour bill check
routes: /labour-check, /sites/:id/labour-claims
mark: Mark checked
---
Billing checks each labour contractor's bill against the work done before it is paid. The page lists the subcontractor bills still in draft, with their productivity check (square metres done per man-day against what is expected). A bill flagged "productivity low" also waits for the director's decision. The site's **Labour claims** page (from the site page) holds the contractor's claimed area against the approved measurement of each area.

**On the page (Labour bill check)**
- The table: **Bill** (number and the work order), **Site / contractor**, **Gross**, **Productivity** and **Checked**.
- **Productivity**: "low: <actual> / <expected> sqm per man-day (director decides)" in red, or "(director approved)" once the director approved it; otherwise the status (for example ok). Under it: "<n> sqm by <m> man-days".
- A row flagged low and not yet approved by the director is shown as overdue.
- **Mark checked**: records that you checked the bill against the work done. The cell then shows "✓ <who> · <date>".
- "No labour bills waiting.": no draft subcontractor bill.

**Labour claims (site page > Labour claims)** {perm: closeout.billing, closeout.claim_approve}
- Each claim: **Contractor** (with the period), **Area**, **Claimed**, **Approved** (the approved measurement of that area and item), **Above approved** (the excess and its %, in orange), **RFI zone** ("ours · <zone>" or the other applicator), **Photos** (measured and claimed) and **Decision**. {perm: closeout.billing, closeout.claim_approve}
- **Pay approved**: asks "Note (optional)", then pays the approved quantity (or the claim, when it is not above). {perm: closeout.billing}
- **Pay claimed…**: shown when the claim is above the approved quantity. Asks "Why pay the claimed area (the director approves it)?"; the reason is needed. {perm: closeout.billing}
- "waiting for the director" with the reason: a claim sent to the director. {perm: closeout.billing, closeout.claim_approve}
- **Approve**: asks "Approved because", then pays the claimed quantity. {perm: closeout.claim_approve}
- **Refuse**: asks "Refused because", then pays the approved quantity only. {perm: closeout.claim_approve}
- A decided claim shows "pays <qty> (claimed / approved)", who decided and who approved, with the reason. {perm: closeout.billing, closeout.claim_approve}
- "No claims yet.": no claim entered on this site. {perm: closeout.billing, closeout.claim_approve}
- **Enter a claim**: enters a contractor's claim. {perm: closeout.billing}
  - **Contractor**: the labour contractor's name. {perm: closeout.billing}
  - **Area (empty: the whole site)**: the place claimed (an area under it counts too). {perm: closeout.billing}
  - **Item (empty: every item)**: the contract line claimed; picking it fills the **Unit**. {perm: closeout.billing}
  - **Claimed quantity**, **Unit** and **Month**: what the contractor claims, for which month. {perm: closeout.billing}
  - **Note (optional)** and **Photos of the claimed work (optional)**. {perm: closeout.billing}
  - **Save the claim**: saves it (open) and uploads the photos; it shows in the list against the approved measurement. {perm: closeout.billing}
- **Add photos** (on a claim not yet decided): uploads more photos of the claimed work; the claimed photo count goes up. {perm: closeout.billing}

**Rules**
- **Mark checked** does not approve or pay the bill. A bill flagged low productivity stays for the director after your check.
- A labour claim is paid on the approved measurement. Paying more needs a reason and the director.
- When a role that may approve claims presses **Pay claimed…**, it is approved at once.
- A decided claim is locked.

**What happens next**
- When a labour contractor's bill is entered, billing gets "Labour bill <bill> of <contractor> for <site>: check it against the work done". **Mark checked** closes that to-do.
- A bill flagged low: the director gets "productivity low. Decide." and decides it under Payables (subcontractor bills).
- **Pay claimed…** above the approved quantity: the director gets "<contractor> claims <n> at <area>, approved <m>. Billing asks to pay the claim: <reason>" with a link to the claims page. **Approve** or **Refuse** closes it.

**Hands off**
- Receives: subcontractor bills entered by accounts; labour claims of the contractors; the approved measurements (billing, the client).
- Passes on: checked bills to accounts for payment; low-productivity bills and claims above the measurement to the director.

**When it goes wrong**
- "Bill not found": the bill was removed or approved meanwhile. Refresh.
- "Paying more than the approved measurement needs the reason": type the reason in the prompt.
- "Claim #n (decided) is locked: it cannot be changed or deleted. Make a new revision or an addendum.": it is decided already.
- "Claim #n is not waiting for the director": it was decided meanwhile. Refresh.
- "Claim not found": the claim is on a site you may not see.
- "Claim #n (decided) is locked ...": photos cannot be added to a decided claim.
- A claim's **Approved** is 0: no approved measurement on that area and item yet. Get the measurement approved first (Measurement book).
