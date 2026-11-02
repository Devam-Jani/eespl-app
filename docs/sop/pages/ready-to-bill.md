---
page: /ready-to-bill
title: Ready to bill
routes: /ready-to-bill
mark: Raise RA bill
---
The page is titled "Work done, not billed". It lists every stage finished on a place and not billed yet, grouped by site, with the value of each site's list. A stage comes here when its last task is done; it carries its measured quantity and the contract line it maps to. From here billing raises the site's RA bill.

**On the page**
- One card per site: the site and the total value of its items.
- **Raise RA bill**: makes the site's draft RA bill with the finished stages' quantities filled in. {perm: billing.edit}
- The table: **Place**, **Stage**, **Contract line** (with the item number; "no contract line" in red when the stage maps to none; a "camera sizes" badge when the sizes came only from the camera; the note), **Qty**, **Survey** (the surveyed sqm), **Value** and **Waiting** (days since the stage was done).
- A row waiting more than 7 days is shown as overdue.
- "Nothing finished and unbilled.": nothing is waiting.

**Rules**
- Only items with a contract line go into the bill. An item with "no contract line" stays here.
- Each line's quantity is cut to what is left of its BOQ quantity after earlier bills.
- The bill still checks the measurement book: a quantity above the approved book is refused.
- Only one draft RA bill per site's contract at a time.
- Camera-only sizes can be billed in the draft, but the tax invoice waits for a laser or manual size, or the client's certification.

**What happens next**
- **Raise RA bill**: the draft RA bill is made and the site's items leave this list (marked billed). Client billing opens with the site picked and the new draft bill open: check it, then **Submit to client**.
- **Cancel bill** on that draft (Client billing) puts the site's items back on this list, open again.
- When a stage is done, billing gets "Work done on <date>: make the stage bill" and the salesperson is told. After 7 days not billed, the director is told. The to-do closes when the bill is submitted.

**Hands off**
- Receives: finished stages from the site team (the last task of a stage done), with the measured quantity.
- Passes on: the draft RA bill to billing's Client billing page, then to the client.

**When it goes wrong**
- "This site has no client contract yet": make the contract first (Client billing > the site > **Make the contract from the won tender**).
- "Nothing ready to bill on a contract line": every item has "no contract line". Map the stage to a contract line, or bill it by hand.
- "Finish (submit or cancel) the draft RA bill first": a draft is already open for the site. Submit or cancel it under Client billing.
- "'<item>': n sqm is more than the measurement book (m); add the measurement first": the approved book is short. Measure and get it approved, then raise again.
- "'<item>': n sqm is beyond the BOQ qty m; ...": bill the excess as an extra item.
- After **Raise RA bill** Client billing opens without the bill: the bill was made. Pick the site and click the bill in the list.
