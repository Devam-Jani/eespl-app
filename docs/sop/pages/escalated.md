---
page: /escalated
title: Escalated (all sites)
routes: /escalated
---
Every to-do from the process rules that went past its time and was escalated, across all sites,
the oldest first. It is the list for following up who is holding what. Each row closes by itself
when the step is done.

**On the page**
- **Delays: the client's and ours**: the days of delay per site, split into the client's delay and
  ours, with the late places. Press a site to open its handover tab. Shown only when some site has
  delays.
- The table:
  - **Waiting**: how long since the first to-do was sent ("n h", or "n d" after 48 hours), and
    "since <date>".
  - **Item**: what the to-do is about.
  - **Site**: press it to open the site's Process tab.
  - **Step**: the process step's number and name, and a red **level n** badge when it escalated
    more than once.
  - **Waiting on**: the people who got the to-do and have not done it.
  - **Open**: opens the page where the step is done.
- "Nothing escalated." when the list is empty.

**Rules**
- A to-do escalates after the hours set for its step in Settings > Process rules, to the roles
  named there. Information-only steps never escalate.
- Escalations always come by email as well (when the company has email on), whatever the person
  chose in My notifications.
- A row disappears when the step is done in the app, or when someone closes the to-do with
  **Done** and a reason.

**What happens next**
- Call the person under **Waiting on**, or open the item and do or reassign the step.

**Hands off**
- Receives: the escalations of every role's late to-dos.
- Passes on: the follow-up to the person holding the step.

**When it goes wrong**
- "Missing permission: one of process.escalations, process.rules": your role does not see this
  list.
- A row stays after the work is done: the step was done outside the app. The person holding it
  closes it with **Done** and the reason on their Notifications or My work.
