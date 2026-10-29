---
page: /billing/payments
title: Payment follow-up
routes: /billing/payments
mark: Log a call
---
The client bills that are past their due date and still not fully paid, with what each one is waiting for and every call made about it. The due date is the invoice date (or the certification date, when the client's work order says so) plus the work order's payment term. Each call is logged here; a promised date becomes the next reminder.

**On the page**
- The table lists each overdue bill:
  - **Bill**: the RA bill code (with the tax invoice number under it). Click it to open the bill on its payment tab, where receipts and the bill's tracking steps are.
  - **Site**: the site code and name.
  - **Outstanding**: what is still to be received on the invoice.
  - **Due**: the due date, and under it how it was worked out (for example "n days after the invoice (work order ...)", "the client's billing cycle" or "the invoice's due date").
  - **Overdue**: the days past the due date. Orange up to 29 days, red from 30 days.
  - **With the client at**: the last tracking step of the bill (for example signed by the client's project manager, sent to head office), or "not tracked yet".
  - **Follow-ups**: every call logged so far, newest first: date, who was spoken to, what was said and the promised date.
- **Log a call**: opens the call form under the table for that bill.
  - **Who you spoke to** (required): the person at the client.
  - **What was said** (required): the answer you got.
  - **Promised date** (optional): the date the client promised to pay.
  - **Save**: adds the call to the bill's follow-ups and refreshes the list.

**Rules**
- A bill shows here only while money is still outstanding on its invoice and today is past the due date. A cancelled bill never shows. A bill that is not invoiced yet has no due date and does not show.
- Calls cannot be edited or deleted after **Save**. Each one is kept in the audit log with who logged it.
- Who you spoke to and what was said need at least 2 characters each.
- You see only the bills of the sites your role may see.

**What happens next**
- The app checks every day and sends these reminders (each once per bill and due date):
  - on the due date: accounts gets "Payment due" with the amount outstanding;
  - 5 days after the due date (a setting): the salesperson gets "Payment overdue";
  - 30 days after the due date (a setting): the director gets "Payment overdue (30 days)", and the salesperson and the site engineer are told as well.
- On the promised date of the latest call: accounts gets "The client's promised payment date" to check the money came in.
- From the first day overdue, the client's users who handle payment see the bill as overdue in the client portal, with an in-app notice once per bill. The client is never emailed.
- When the receipt is entered against the invoice and nothing is outstanding, the bill drops off this list and the reminders stop.

**Hands off**
- Receives: issued invoices from billing; the due date from the client's work order or billing cycle.
- Passes on: the call notes to the salesperson and the director (they see them on the bill); the payment itself to accounts, who enter the receipt.

**When it goes wrong**
- "Nothing overdue.": no bill is past its due date with money outstanding.
- A bill you expected is missing: check it is invoiced (a bill with no invoice has no due date) and that the receipt was not already entered in full.
- **Due** looks wrong: the payment term comes from the client's work order, else from the client's billing cycle, else from the invoice's own due date. Fix the term there.
- "Bill not found": the bill was cancelled or is on a site you may not see.
- A **Save** that fails closes the call form and shows the reason above the table. Press **Log a call** again and type the call again.
