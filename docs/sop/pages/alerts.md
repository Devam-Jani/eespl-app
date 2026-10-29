---
page: /alerts
title: Alerts
routes: /alerts
---
Alerts are the warnings the app checks for every hour: a missing daily report, a late site, a cost
past its budget head, an overdue invoice, a late PO and so on. Each alert goes to the roles set for
its rule (and to the site in-charge or the item's owner), lands in the bell and stays here until
someone acknowledges it.

**On the page**
- The line under the title says when the worker last checked. "Each item once a day; acknowledged
  items rest for a week."
- **Check now**: runs every rule at once instead of waiting for the hour. The message says "Checked: n new alert(s)." {perm: dashboard.company}
- **State** (filter): **Open** (default), **Acknowledged** or **All**.
- **Rule** (filter): **All rules**, or one rule: **DPR missing after 8 pm**, **Site behind
  schedule**, **Cost passed a budget head**, **Invoice overdue**, **PO delivery late**, **Low
  stock**, **Petty cash balance negative**, **Tender due, not submitted**, **Kylas sync failing**,
  **Quotation follow-up overdue**, **Delivery not confirmed at site**, **Delivery still not
  confirmed (escalated)**, **Rate contract expiring**, **Work done, not billed**, **Material
  consumption off the system**, **Tender awaiting award: follow up**, **Monthly RA bill due**.
- Each row: the day, the rule's name (small), and the alert. Press the alert to open its page.
- **Acknowledge**: marks the alert seen and dealt with. The row then shows "acknowledged by
  <name>" and leaves the **Open** list.
- "No alerts." shows when the filter finds none.

**Rules**
- You see the alerts sent to you. The management dashboard roles see every alert. {perm: dashboard.company}
- An item raises its alert at most once a day. A new alert for the same item closes the older open
  one.
- An acknowledged item is not raised again for 7 days (the company's setting), even if the cause is
  still there.
- Who gets each rule by default: DPR missing: office admin; behind schedule: super admin and office
  admin; budget head (90%): office admin and accounts; invoice overdue (30, 60, 90 days): accounts
  and office admin; PO late, low stock: store and purchase; petty cash negative: accounts; tender due
  in 2 days: estimator and office admin; Kylas failing for 24 hours: super admin; quotation
  follow-up overdue: office admin; rate contract expiring: store and purchase; work done not billed:
  accounts; award follow-up: planning; monthly RA bill: billing. The site in-charge or the item's
  owner is added where the rule has one.
- Alerts are only in the app (the page and the bell); they are not emailed.
- The DEMO company never raises alerts.

**What happens next**
- Open the alert, fix the cause on its page (send the DPR, follow up the invoice, chase the PO),
  then **Acknowledge** it.
- An alert not acknowledged comes back the next day while the cause is still there.

**Hands off**
- Receives: the hourly check over every site, bill, PO, stock and tender.
- Passes on: the work to whichever role fixes the cause; the acknowledgement shows who took it.

**When it goes wrong**
- "Alert not found": the alert is not one sent to you, or it is gone. Reload the page.
- "Missing permission: dashboard.company": only the management dashboard roles can run **Check
  now**.
- An alert you expected is missing: it may have been acknowledged in the last 7 days. Set **State**
  to **Acknowledged** or **All**.
