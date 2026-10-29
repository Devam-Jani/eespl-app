---
page: /scorecard
title: Closure scorecard
routes: /scorecard
---
One row per salesperson: quotations sent, won and lost (with the reasons), the closure rate against
the target, and the follow-ups done on time. The director sees every salesperson; a salesperson sees
only their own row. The page has no buttons: it only reads.

**On the page**
- **Salesperson**: the name.
- **Sent**: the salesperson's quotations (latest revision of each) that were ever sent, or are sent, in negotiation, won, lost or expired.
- **Won** and **Lost**: the latest revisions now won or lost.
- **Lost because**: each reason with its count (e.g. "price 2, competitor 1"); "not given" when no reason was saved.
- **Closure**: won ÷ (won + lost), as a %, then "/ target %". Red when below the target; "—" while nothing is decided.
- **Follow-ups on time**: follow-ups done on or before their due date / follow-ups due up to today (cancelled ones are not counted).

**Rules**
- The target is the salesperson's own closure target if set, else the company target (65 % unless changed in the team settings).
- Expired quotations count as sent, not as lost.
- A quotation closed as "main job lost by the contractor" (the civil contractor we quoted lost the main contract) is counted in **Lost** and lowers the closure rate in this version, although the tender page says it is not our loss.
- Training (DEMO) users are left out of the director's view.

**What happens next**
- Low closure: look at **Lost because** and talk it through with the director.
- Follow-ups late: open Quotations, **Follow-ups & files**, and close each follow-up with **Done** on the day.

**Hands off**
- Receives: the quotations marked sent, won and lost, and the follow-ups closed, by the salespeople.
- Passes on: nothing; the director uses it to review the salespeople.

**When it goes wrong**
- "Missing permission: scorecard.view": your role does not see the scorecard.
- Your row is missing: you have no quotation as salesperson yet.
