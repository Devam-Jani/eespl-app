---
page: /leads
title: Leads
routes: /leads, /leads/:id
mark: New lead
---
Every enquiry is a lead: who called, the company and city, what they need, where it came from and
who owns it. The list shows the leads you may see; a salesperson sees only the leads they own or
entered. Click a row (or a card in **Kanban**) to open the lead: its details, its status and its
activity timeline.

**On the list**
- **Search code, name, company, phone, city** (box): type and press Enter to filter the list.
- **Status**, **Source**, **Owner**, **Kylas status** (filters): narrow the list. **All statuses**, **All sources**, **All owners** and **Any Kylas status** clear a filter.
- **Follow-up due** (tick): only the leads whose next follow-up date has come. A due date shows in red in the **Follow-up** column.
- **List** / **Kanban** (tabs): a table of 50 leads a page, or one column per status (up to 300 leads).
- In **Kanban** you can drag a card to another status column; the lead's status changes and a line is added to its timeline. {perm: leads.edit}
- **⤓ Export Excel**: downloads the leads as they are filtered.
- **New lead**: opens the **New lead** form. {perm: leads.edit}
- **Previous** / **Next**: move through the pages of the list.
- The **Kylas** column: **Kylas off** (the link is not switched on), **Kylas pending** (waiting to be sent), **In Kylas** (sent), **Kylas failed**, or **Kylas: needs phone**.

**The New lead / Edit form** {perm: leads.edit}
- **Contact name \*** and **Phone (mobile) \***: both required. When you leave the phone box, the app checks the number; if another lead has it, a warning names that lead ("This phone is already on ... You can still save.").
- **Email**, **Company**, **City**, **State**, **Source** (Website, Call, Referral, Channel, Walk-in, Exhibition, Other).
- **Channel (who brought it)**: a salesperson, partner or manufacturer route; **— direct —** for none.
- **Client (if known)**: pick the client if it is already in Clients.
- **Owner**: who works the lead. Left on **Me**, you become the owner.
- **Interest: system**, **Interest: work category**, **Est. area (sqm)**, **Est. value (₹)**, **Next follow-up**, **Requirement**.
- **Create lead**: saves it as **New**, gives it a code and opens it. If the Kylas link is on, the lead is queued for Kylas once.
- **Save** (on Edit): saves the changes in EESPL only. On a lead already in Kylas the form says "Edits stay in EESPL: they are not sent to Kylas in this version."
- **Cancel**: closes the form without saving.

**On a lead (/leads/:id)**
- The header shows the contact, the status badge, the Kylas badge, the company and city, and the tender code when the lead has one.
- A yellow note "Same phone as ..." lists other leads with the same phone, with links.
- **Status** (drop-down): New, Contacted, Site visit, Quoted, Won, Lost, Junk. Picking a status saves it at once and adds a line to the timeline. Picking **Lost** opens **Mark the lead lost** first. {perm: leads.edit}
- **Surveys**: opens the site surveys of this lead. {perm: survey.view}
- **Quotations**: opens the quotations made from this lead. {perm: quotation.view}
- **New quotation**: opens Quotations with the **New quotation** dialog already on this lead. {perm: quotation.edit}
- **Convert to tender**: asks "Create a tender from this lead?". Yes makes a tender with the lead's client, channel, city, state and owner, links the lead to it, and moves a New, Contacted or Site visit lead to **Quoted**. Only shown while the lead has no tender. {perm: tender.edit}
- **Edit**: opens the same form as **New lead**, filled in. {perm: leads.edit}
- **Kylas** box: the Kylas lead number, the forecast stage and when it was sent; the last error in red. **Retry** sends the lead to Kylas again; shown only when the lead has a phone, is not in Kylas yet, and the send failed or the link was off. {perm: leads.edit}
- **Activity**: the timeline (notes, calls, visits, status changes, Kylas outcomes, issued quotations with a **⤓ Issued quotation (PDF)** button).
- **Note type** (Note, Call, Visit), **What happened?** and **Add**: write what happened and press **Add**; it goes on the timeline with your name and the time. {perm: leads.edit}

**Mark the lead lost** {perm: leads.edit}
- **Reason \***: Price, Competitor, Timing, Specification, Relationship, Other, Main job lost by the contractor.
- **Lost to (competitor, if known)** and **Details**.
- **Mark lost**: enabled once a reason is picked. The lead turns **Lost** and the reason, competitor and note show on the lead. **Cancel** keeps the old status.

**Rules**
- A lead needs a phone number. Kylas finds a lead by phone, so a lead without one is never sent.
- Kylas gets the lead once, when it is created. Later edits stay in EESPL. Kylas outcomes (lost, junk, won) come back every few minutes and show on the timeline.
- A salesperson can change only the leads they own or entered. {perm: leads.edit}
- Moving a lead to **Won** or **Lost** by hand does not start a job. A job starts when a quotation or a tender is marked won.
- Sending a quotation moves a New, Contacted or Site visit lead to **Quoted**. Marking the quotation won marks the lead **Won**.

**What happens next**
- Make the quotation from the lead (**New quotation**), or **Convert to tender** when the client sends a BOQ.
- Log every call and visit on the timeline so the next person sees the whole story.

**Hands off**
- Receives: enquiries allocated by planning (Enquiries to allocate); the salesperson is told "Enquiry ... allocated to you ... Prepare the quotation." If no quotation is made in 3 days, planning is reminded. Leads also come from Kylas.
- Passes on: the quotation (Quotations) or the tender (Tenders).

**When it goes wrong**
- "Lead not found": the lead is not yours (or was removed). Ask the owner or planning.
- "You cannot change this lead": you may see it but not change it; ask the owner.
- "Pick why the lead was lost": choose a reason in **Mark the lead lost**. Dragging a card to the **Lost** column in Kanban gives this error, because the drag cannot ask for a reason; open the lead and use **Status** instead.
- Picking **Main job lost by the contractor** as the reason is refused for a lead in this version. Pick the closest other reason and write the details.
- "Set the lead's client or channel first (a tender needs one)": edit the lead, fill **Client (if known)** or **Channel (who brought it)**, then **Convert to tender** again.
- "This lead already has a tender": open it from the tender link under the name.
- "Missing permission: tender.edit": your role cannot make tenders; ask the estimator.
- "A lead needs a phone number" / "Add a phone number: without one Kylas cannot be searched after a timeout": fill **Phone (mobile)**.
- "This lead is already in Kylas": nothing to retry.
- "Unknown channel", "Unknown client", "Unknown owner": the item was removed while the form was open; close and open the form again.
