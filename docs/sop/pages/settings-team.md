---
page: /settings/team
title: Team settings
routes: /settings/team
mark: Save
---
The team's reminders and targets: the day monthly RA bills fall due, the tender award reminder,
the closure target, and who receives the site allocation list. The director also gives single
people extra rights here. Every change is written to the audit log.

**On the page**
- **Monthly RA bills: billing gets the to-do on day**: 1 to 28. From this day each month, billing gets a "Monthly RA bill due" to-do for every running site with measured work not yet billed that month.
- **Tender awaiting award: remind every (days)**: 7 to 365. A submitted tender still awaiting the award gives its owner a follow-up reminder this often, until it is won or lost.
- **Closure rate target (%)**: 0 to 100. The company target on the salespeople's scorecard (a salesperson's own target, if set, wins).
- **Site allocation list goes to**: the people who get the site allocation list when planning sends it (hold Ctrl to pick several).
- **Save**: saves the four fields. "Saved." shows.

**Allowed per person (the director)** {perm: grants.manage}
- One row per person, with two tick boxes on top of their roles: {perm: grants.manage}
- **Costs and margins**: the person may see costs and margins (for example a planner). {perm: grants.manage}
- **Decides won jobs**: the person may decide who handles a won job. {perm: grants.manage}
- A tick is saved at once. Every change is logged. {perm: grants.manage}

**Rules**
- Only roles with the planning edit or company settings right save the team settings.
- Only the director (grants right) gives or takes away the per-person rights. {perm: grants.manage}

**What happens next**
- Billing, salespeople and planning get their to-dos and reminders on the new days.
- When planning sends the site allocation list, it goes to the bell of the people chosen here.
- A person given a right has it on the server at once; their menu and screens show it the next time they open or reload the app. {perm: grants.manage}

**Hands off**
- Receives: the targets and days agreed by the director.
- Passes on: RA bill to-dos to billing, award reminders to the tender owner, the allocation list to the chosen people.

**When it goes wrong**
- A number out of range is refused. The error shows in red at the top.
- "Choose who receives the allocation list (settings)": (on the planning board) nobody is chosen in **Site allocation list goes to**. Pick the people and press **Save**.
- If a per-person tick does not stay, the change was refused; the reason shows in red at the top. {perm: grants.manage}
