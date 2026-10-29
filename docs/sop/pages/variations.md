---
page: /variations
title: Variations
routes: /variations
---
The list of variations asked from site slips: a slip line that no work-order item covers, proposed by billing as a new item with its description, unit and rate. The director approves it (it joins the work order and is billed with its sheet) or not, with why.

**On the page**
- The table: **Site / sheet**, **On the slip** (the line as written), **Proposed item** (description and unit), **Rate**, **Status** (proposed, approved, rejected) and **Decision**.
- **Note** (field): the reason. Needed only for **Not approved**. {perm: variation.approve}
- **Approve**: approves the new item. {perm: variation.approve}
- **Not approved**: refuses it, with the note. {perm: variation.approve}
- Once decided, **Decision** shows the note, or "decided <date>". While proposed, others see "waiting for the director".
- A green note after a decision says what was done.
- "No variations asked": none yet. Billing asks for one from a slip line (Measure and bill > the slip sheet > **Ask for a new item / variation**).

**Rules**
- A variation is asked only for a slip line not mapped to a work-order item, with a description, a unit and a rate above zero. One open request per line.
- **Not approved** needs the reason in **Note**.
- A decided variation cannot be decided again. A refused line can be asked for again.
- Approval needs the site's work order.

**What happens next**
- **Approve**: the item is added to the work order as V1, V2 ... ("Variation: <description>") and to the client contract as an extra item beyond the BOQ, already approved. If the slip's sheet is still a draft, the slip line is mapped to it, worked out in its unit and billed with that sheet; the bill lists it under "Variations in this bill, for the client to agree". If the sheet was already sent, map the line to the new item on a draft sheet to bill it.
- **Not approved**: the line stays listed as unbilled on the slip.
- No notification is sent either way: billing sees the decision on the slip sheet and here, and the director checks this page for new requests.

**Hands off**
- Receives: requests from billing (variation.request) from a slip sheet.
- Passes on: approved items to the work order and the contract, billed by billing with the sheet and agreed by the client with the bill.

**When it goes wrong**
- "Say why it is not approved": type the reason in **Note**, then **Not approved**.
- "The variation is approved already" (or rejected): someone decided it. Refresh.
- "The site has no work order to add the variation to": the site has no client work order. Billing records it first.
- "A variation is asked for this line already": the line has a request waiting.
- "That line is mapped to a work-order item already": the line is billable as it is.
- "Give the item's description and unit" / "Give the rate": fill them when asking.
- "Variation not found": it is on a site you may not see.
