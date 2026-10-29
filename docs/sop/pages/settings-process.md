---
page: /settings/process
title: Process rules
routes: /settings/process
mark: + Application
---
The chain between teams. When one team finishes its step, the next person is told, in the app
and by email (our staff only), and chased if nothing happens. This page sets who is told, the
message, when it escalates and to whom, and the company defaults behind it. Information-only rules
never escalate. Every change is saved at once and written to the audit log ("Saved (logged).").

**Prices, rate working and lots**
- **Margin in new rate workings (a saved working keeps its own)**: **on cost: rate = cost × (1 + margin)** or **on the selling price: rate = cost ÷ (1 − margin)**.
- **Flag a price change of more than (%)**: a vendor price that moves more than this is flagged.
- **Flag a worked rate off the rate library by more than (%)**: a rate working this far from the rate library is flagged.
- **A call-off past the plan's balance plus (%) needs planning**: a material call-off above the plan's balance plus this margin needs planning's approval.
- **A gang's standard day (hours)**: the hours of a normal gang day.
- **Save**: saves this card. "Saved (logged)." shows next to the button.

**Defaults**
- **Default <role> (a site with nobody in the role)**: one box each for planning, billing, accounts, store purchase, estimator, salesperson, site engineer and supervisor. Pick the person told when a site has nobody in that role. The empty choice is **The office admin** (planning) or **Everyone holding the role** (the others). A choice is saved at once.
- **Stage bill limit (days): the director is told after**: when a finished stage is not billed within these days, the director is told. Saved when you leave the box.
- **Daily summary email at (hour, IST)**: 0 to 23. The hour the daily summary email goes to people who chose "summary" for some rules. Saved when you leave the box.

**Wastage per application (material plans)**
- One line per application (a word found in a place's name, such as podium): the minimum and maximum wastage %. Saved when you leave a box.
- **+ Application**: asks "Application (a word found in the place's name, e.g. podium)" and adds it with 5–7 %.

**The rules table**
- **#**, **Event**: the rule's number, title and the event that starts it.
- **Who is told: the message**: one line per recipient, with the role, **information** or the action they must take, "if <condition>" when it applies only sometimes, and the message.
- **+ another recipient…**: pick a role to add it to the rule. The new recipient gets the same message and action as the rule's first recipient.
- **Escalation**: "after <hours> h → <roles>" for each step, "none", or "information: never". Type new hours in the box; saved when you leave it.
- **Email**: ticked, the action items of this rule are also emailed. Information items stay in the app.
- **On**: untick it to switch the rule off. Nobody is told for that event until it is ticked again.

**Rules**
- Only roles with the process rules right open and change this page.
- An escalation is more than 0 and at most 1440 hours (60 days) and must go to at least one role.
- Escalations are always emailed, whatever the person chose.
- Each person can choose app, email or a daily summary per rule in My notifications; their choice wins over the **Email** tick.
- Wastage: the minimum must be 0 or more, not above the maximum, and the maximum 100 or less.
- Changes apply to events from now on. Notices already sent stay.

**What happens next**
- The next event of each rule tells the roles listed, on the site's own people first, else the default person.
- An action item not done in time escalates to the roles in **Escalation**; the director sees it on Escalated.

**Hands off**
- Receives: the way of working agreed by the director and the planning head.
- Passes on: the to-dos and notices every role gets in My work and Notifications.

**When it goes wrong**
- "An information-only rule never escalates": an escalation cannot be set on a rule that only informs.
- "Unknown role: <role>": pick a role from the list.
- "Wastage for <application>: 0 <= min <= max <= 100": fix the minimum or maximum.
- "Rule not found": reload the page.
- Choosing **The office admin** or **Everyone holding the role** again after a person was set clears the person; "Saved (logged)." shows.
