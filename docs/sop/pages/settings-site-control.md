---
page: /settings/site-control
title: Site control
routes: /settings/site-control
mark: Save
---
The timings and limits of the site-control alerts: unconfirmed deliveries, work done but not
billed, rate contracts ending, labour productivity and material consumption. Every save is written
to the audit log.

**On the page**
- **Delivery not confirmed: alert the site in-charge after (hours)**: 1 to 240. A dispatched delivery not confirmed at site this many hours after it was expected raises an alert to the site in-charge.
- **Then alert planning after (hours)**: 1 to 480. Still not confirmed after this many hours, a high alert goes to planning.
- **Planning (who gets the second alert)**: one person, or **The office admins** (all of them).
- **Receipt link works for (days)**: 1 to 60. How long the delivery receipt link sent for a delivery stays valid.
- **Work done, not billed: alert after (days)**: 1 to 90. A finished stage still open in Ready to bill after this many days raises an alert to the site in-charge.
- **Rate contract ending: alert purchase (days before)**: 1 to 90. An active rate contract ending within this many days raises an alert to renew it.
- **Labour check: flag below expected by (%)**: 0 to 100. A gang this far below its expected output is flagged.
- **Consumption variance: flag outside ± (%)**: 0 to 100. A site whose material issued is further than this from the systems' consumption is flagged.
- **Save**: saves all the fields. "Saved." shows.

**Rules**
- Only roles with the company settings right save this page.
- The new values apply from the next alert run. Alerts already raised stay.

**What happens next**
- The alerts show on Alerts and in the bell of the people named above.

**Hands off**
- Receives: the limits agreed by the director and planning.
- Passes on: delivery alerts to the site in-charge and planning, billing alerts to the site in-charge, contract alerts to purchase.

**When it goes wrong**
- A number outside its range is refused next to the field. The error shows in red at the top.
- "User not found": the chosen planning person was removed. Pick another and save.
