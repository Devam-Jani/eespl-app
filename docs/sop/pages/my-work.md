---
page: /my-work
title: My work
routes: /my-work, /
mark: ↻ Refresh
---
My work is the page the app opens after you sign in. It lists everything waiting for you, one
section per role you hold, the most urgent first. In the side menu it is called **Approvals**, with
the number waiting beside it. On a phone, site roles reach it from the **My day** tab at the bottom.

**On the page**
- The heading shows your name, your job title and "n waiting": the number of lines on the page.
- **↻ Refresh**: loads the lists again. Use it after you finish something in another tab.
- **From the process (to do until done)**: the to-dos the process rules sent you (for example
  "Approve" a travel claim, or a step on a site). It is shown first when you have any. A to-do that
  is already on your role's own list (same link) is not shown twice.
- One section per role you hold, each with the number of lines in a grey badge:
  **Director: decisions waiting**, **Planning**, **Billing**, **Accounts**, **Sales**,
  **Estimating**, **My sites** (site engineer), **Today on site** (site supervisor),
  **Store and purchase**, **Deliveries to confirm** (site receiver), **Office** (office admin).
  The super admin sees the director's section. A section with nothing in it shows "All clear."
- Each line shows what it is about (in bold), extra detail lines when there are some, why it is
  waiting (for example "Submitted by the supervisor: approve or return", "Not marked today",
  "Ready to bill"), and its age: "today" or "n d". An age over 7 days is shown in red.
- The coloured edge of a line: red for escalated or urgent, orange for a warning, none for normal.
- The action button on each line (for example **Review**, **Mark**, **Write**, **Confirm**,
  **Make PO**, **Bill it**, **Allocate**, **Decide**, **Approve**): opens the page where you do it.
  Nothing changes until you act on that page.
- **Done** (only on lines from the process): closes the to-do by hand. It opens a **Reason** field
  ("Why was "<action>" not done in the app?"). Type at least 3 characters, then **Close it**.
  **Cancel** leaves the line open.
- "Nothing waiting for you." shows when you have no lines at all.
- Under the lists, roles with a dashboard see their dashboard (the same as **More numbers** on the
  Dashboard page). A person whose only role is site supervisor does not get it, so the page stays
  short on a phone.

**Rules**
- A line closes by itself when you do the step on its page (approve the report, mark attendance,
  confirm the delivery ...). You do not need to tick anything.
- **Done** is for a step that was really done outside the app. The reason is kept and shown on the
  site's process timeline (site > Process tab).
- **Done** closes that to-do for everyone who got it for the same item, and stops its escalations.
- You only see lines for the roles you hold. A person with two roles sees both sections.
- A process to-do left open past the time set in Settings > Process rules escalates: it goes to
  the roles named there (often the director) and is marked "· escalated" in red.

**What happens next**
- Open the line, do the step on its page, come back: the line is gone. Press **↻ Refresh** if the
  page was left open.
- The number beside **Approvals** in the menu refreshes when you change page (at most every
  15 seconds).

**Hands off**
- Receives: the to-dos the other roles' steps create for you (a report submitted, an indent
  approved, a claim ready, a delivery dispatched ...).
- Passes on: whatever you do on the linked page creates the next role's line on their My work.

**When it goes wrong**
- "Say briefly why '<action>' was not done in the app": the reason under **Done** was shorter than
  3 characters. Write a short reason.
- "Nothing to close": the to-do was already closed (by you on another device, or by someone else's
  step). Press **↻ Refresh**.
- "Notification not found": the to-do is not yours. Press **↻ Refresh**.
- A line stays after you acted: the step was not saved or was saved on another item. Open the line
  again and check the page's status.
- The page shows "Loading…" for long: the connection is slow. Wait, or reload the browser page.
