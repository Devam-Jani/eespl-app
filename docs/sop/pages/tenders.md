---
page: /tenders
title: Tenders
routes: /tenders, /tenders/:id
mark: New tender
---
A tender is a client's BOQ that we price line by line: import the BOQ, price each line, check the
margin, attach the terms, submit a revision (R0, R1 ...), then record the award. A won tender
becomes a site. A salesperson sees only the tenders they own or are a member of.

**On the list**
- **Search code, name, client or site** (box): type and press Enter.
- **Status** (filter): Draft, Submitted, Won, Lost, Dropped.
- **Client**, **Channel**, **Owner** (filters). {perm: tender.edit}
- **⤓ Export Excel**: downloads the tenders as filtered.
- **New tender**: opens the **New tender** form. {perm: tender.edit}
- A **Due** date in red means "Overdue and not submitted". **Quoted total** is our total for the current revision.
- Click a row to open the tender. **Previous** / **Next** page through the list.

**New tender / Edit** {perm: tender.edit}
- **Name \***; **Client (end client, ...)** (or **— not known yet —**); **Channel (who brought it)** (or **— direct —**). Choose the client, the channel, or both.
- **Site name**, **City**, **State**, **Owner**, **Received on**, **Due on**.
- **T&C template** (new tender only): the terms copied in at the start; the default is picked.
- **Team members**: other people who may see and work the tender.
- **Notes**. **Create tender** (or **Save**) and **Cancel**.

**On a tender (/tenders/:id): the header**
- The name, the status, the revision badge (e.g. "R0 draft"), the client, channel, city and due date. **Surveys** and **Methodology** links open those of this tender. {perm: survey.view, methodology.view}
- **Revision to export**: **Current (...)** or a submitted revision "as submitted".
- **⤓ Excel** and **⤓ PDF**: our BOQ with selling rates. **⤓ Client format**: our rates written into the client's own uploaded file (only when the original was an .xlsx with a rate column).
- **Submit R(n)**: freezes the BOQ and terms as revision R(n) and marks the tender **Submitted**. See **Submitting** below. Shown while the current revision is a draft. {perm: tender.edit}
- **Quoted total (excl. GST)**.
- After a submit: "R(n) was submitted. Any change to the BOQ or the terms starts R(n+1) as a draft." {perm: tender.edit}
- A yellow note "Rates not sent to the lines." shows when the BOQ rates differ from the rate working, with **Send the rates to the lines** (draft only), shown only to roles that see margins. {perm: tender.edit, tender.margin}

**Tabs**
- **Details**, **BOQ**, **Rate working**, **Margin check** (margin roles only), **Checks** (estimate roles only), **Terms**, **Revisions (n)**, and **Awaiting award** (while submitted) or **Award & bidders**.

**Details tab**
- The details list: code, client, channel, site, dates, owner, team, quoted total, **Guarantee** ("not filled (send checklist)" when empty), the lost reason and competitor when closed. Cost and margin of system-priced lines show only to margin roles; others see "Cost and margin figures need the tender margin permission."
- "Won in Kylas (lead ...): confirm and mark won." with **Mark won**, when Kylas reports the lead won. {perm: tender.edit}
- **Guarantee years**: asks for the years and saves them. Needed before submitting. {perm: tender.edit}
- **Mark submitted** (draft only): the same as **Submit R(n)**, without the note and without the rate confirmation. {perm: tender.edit}
- **Won**, **Lost**, **Dropped**: open "Mark ... as won / lost / dropped". Lost and dropped need a **Reason \***; all take **Details** (or **Why we won**) and a competitor. **Mark won** / **Mark lost** / **Mark dropped** saves. {perm: tender.edit}
- Marking **won** tells the director "Won: ... Assign the salesperson and the site engineer." and adds the tender's workings to the library as evidence. If you may make sites, the app then asks "Tender won. Create the site now?". {perm: tender.edit}
- **Back to draft**: puts a submitted or closed tender back to draft and clears the lost reason. {perm: tender.edit}
- **Edit**: opens the tender form. {perm: tender.edit}
- **Open site** once a site exists; **Create site** on a won tender without one: asks "Site start date (YYYY-MM-DD)", makes the site with the tender's client, channel and BOQ, and opens it. {perm: site.edit}
- **Quoted to (civil contractors bidding for the main job)**: when the developer's BOQ reaches us through several civil contractors, each gets its own quotation from the same BOQ. **Add a civil contractor…** and **Quote it to them too** add one and make its quotation. **Won the main contract** on a row records which contractor won the main job: the others' open quotations close as lost with "Main job lost by the contractor" ("not counted as our loss"). {perm: tender.edit}

**BOQ tab**
- The grid: **Item no**, **Description**, **Unit**, **Qty**, **Rate**, **Amount**, **Client remarks**, **Our product**, **Make**, **Our remarks**, **Status** (Unpriced, Suggested, Priced, NQ).
- Margin roles also see **Cost**, **Margin %** and **Source**; **Margin %** can be typed on system-priced lines. {perm: tender.margin}
- Arrows move · Enter or typing edits · Tab goes to the next cell · Esc cancels. In **Qty** type a number, **QRO** (rate only) or **NQ** (not quoted). QRO and NQ lines are left out of the totals. {perm: tender.edit}
- **⤒ Import client BOQ**: opens **Import client BOQ**: **Choose the BOQ** (.xlsx, .xlsm, .xls, .csv or .pdf, up to 20 MB), then **Sheet**, **Header row** and the **Columns** (**Description \*** is required; the client's rate is kept for reference only). The first 30 rows show as they will be imported. If the tender has lines already, tick "Replace them (priced rates are kept where the item no and description match)". **Import n lines**, then **Done**. {perm: tender.edit}
- **Suggest rates**: proposes a rate for each unpriced line from the rate library and the systems ("Suggested x of y lines ...; z left unpriced, w priced lines untouched."). Priced lines are not touched. {perm: tender.edit}
- **Accept all ≥** with **Minimum score %** (80 by default): asks "Accept n suggestion(s) scoring x% or more?" and turns them **Priced**. {perm: tender.edit}
- **Add line** (asks for the description; goes under the selected line) and **Add section** (asks for the title). On a section: **Rename**, **Add note** / **Edit note**, **Remove heading** (its lines stay). {perm: tender.edit}
- **Apply margin** with **Margin %** (25 by default): asks "Set x% margin on every system-priced line? Library and manual rates are not changed." {perm: tender.margin}
- The totals: **Subtotal**, **GST**, **Total with GST**; margin roles also see **Cost of system-priced lines** and **Margin on them**.
- Click a line to open its panel: the client's rate, make and remarks; **Candidates** with their score and reason, **Why this rate** (red when more than 15% above the median of past BOQs) and **Use this**; the **Rate library** min, median and max; the **System build-up** (materials, surface preparation, labour, cost, margin).
- In the panel: **Mark not quoted** / **Quote this line**, **Clear rate**, **Delete line** (asks "Delete this line?"). {perm: tender.edit}

**Rate working tab**
- The same rate working as on a quotation: main items, their build-up, and **Rates to the lines**. **Match the client BOQ to the library** opens the library match. Editing needs the margin right and the tender edit right; without the tender edit right the working is read-only (no editing buttons), and **Mark final: add to the library** also needs the knowledge edit right. {perm: tender.margin}

**Margin check tab** {perm: tender.margin}
- Per BOQ line: rate, material, labour and cost per sqm, the material share and the margin on the selling price, with warnings ("Material alone is ...% of the rate ... (over ...%)", "No labour estimate in the working: the margin is before labour", no coverage, no price). "No rate working yet" until the rate working exists.
- **Material share limit %** and **Save** (director). **Free issue (the client supplies)** and **Save the free issue and its clause**: takes those products out of our cost and writes the clause into the tender's terms.

**Checks tab** {perm: estimate.view}
- **Checks before it is sent**: coverage written outside the material library, and T&C wording that gives free-issue materials away, with the corrected wording. "No coverage outside the material library and no T&C wording to correct." when all is right.

**Terms tab**
- The clauses in order, with "edited for this tender" or "own text" badges.
- **Add own clause**, **Edit**, **↑** / **↓** (or drag), **Remove**, **Save terms** ("Terms saved for this tender. The T&C library is unchanged."). **Search clauses** and **Search** on the right, **Add** on a library clause. {perm: tender.edit}

**Revisions tab**
- **Submitted revisions**: each with who submitted it, when, the note, the totals and the line count.
- **Compare**: **From revision** and **To revision** show the totals and each line's change and Δ rate.

**Awaiting award / Award & bidders tab**
- The status, when it was submitted, the last follow-up, and the reminder period.
- **Log a follow-up** (while awaiting award): asks "What did the client say?" and records the follow-up date.
- **Send checklist:** lists what is still missing.
- **Bidders**: rank (L1, L2 ...), contractor and rate. **Contractor**, **Rate (₹)**, **Rank (1 = L1)**, **us** and **Add bidder** add one. {perm: tender.edit}
- **They won** on another bidder opens "Another contractor won": **Follow up on** (a date at their waterproofing stage) and **Record the winner**. The tender closes **Lost** to them (reason Price unless already set) and a new lead is opened with the winner, owned by the tender's owner, with that follow-up date ("Lead ... opened with the winner."). {perm: tender.edit}
- **Negotiation log**: what the client asked and what we gave; **Log** tells the estimator and the salesperson to revise. {perm: tender.edit}

**Submitting**
- If the BOQ rates differ from the rate working, the app asks to submit with the lines' rates; Cancel, then **Send the rates to the lines**, to use the working's.
- Then "Submit R(n) to the client? This freezes the BOQ as it is now. Note (optional):".
- The send checklist must pass: every quoted line has **Our product** and **Make**, the guarantee years are filled, and the terms hold our scope and the client's scope from the T&C library. When it blocks, the author is told what is missing.
- The director may send past the checklist with a reason of at least 5 characters (logged). {perm: sendcheck.override}
- On submit the tender is **Submitted** (awaiting award). The salesperson and planning are told "Tender ... submitted: awaiting award". The tender is followed up every 60 days (the setting) until won or lost.

**Rules**
- A submitted revision is frozen. Any change to the BOQ or terms starts the next revision as a draft; the submitted one stays as it was, with its rate working.
- A tender needs a client, a channel, or both.
- Lost and dropped need a reason.
- Only margin roles see costs and margins, apply a margin or change a line's margin %.
- There is no separate approval button: the send checklist is the gate, and only the director can submit past it.

**Hands off**
- Receives: tenders converted from leads (salesperson), BOQs from clients, rates and margins (estimator).
- Passes on: the submitted BOQ to the client; the win to the director (assign the team); the won tender to a site (director or office admin); the winner's lead back to the salesperson when another contractor wins.

**When it goes wrong**
- "Choose the client, the channel, or both" / "A tender needs a client, a channel, or both".
- "Tender not found": not yours; ask the owner to add you to **Team members**.
- "You cannot change this tender": your scope does not cover it.
- "... cannot be sent yet: n line(s) without our product; n line(s) without the manufacturer; Guarantee years not filled; Our scope not attached from the T&C library; The client's scope not attached from the T&C library": fill **Our product** and **Make** in the grid, press **Guarantee years**, add the clauses on **Terms**, then submit again.
- "Only the director can send past the checklist".
- "...: ... (largest difference ₹...). Send the rates to the lines from the rate working, or confirm the lines' rates.": on the Details tab **Mark submitted** cannot confirm; use **Submit R(n)** and answer OK, or ask the estimator to send the rates.
- "R(n) is already submitted. Change the BOQ or T&C to start R(n+1)."
- "Pick why the tender was lost or dropped": choose a reason.
- "That is us: mark the tender won instead".
- "Upload an .xlsx, .xls, .csv or .pdf file"; "The file is larger than 20 MB"; "Could not read the file: ..."; "No sheet named ..."; "The header row is past the end of the sheet"; "This tender already has n BOQ lines; import again with replace".
- "The description cannot be empty"; "Quantity: a number with up to 3 decimals, QRO or NQ"; "Rate: a number with up to 2 decimals"; "Margin: a percentage, e.g. 25"; "Enter a percentage between 0 and 100".
- "Line ... is not quoted; set it back to unpriced first"; "Line ...: a margin applies only to system-priced lines"; "Missing permission: tender.margin".
- "Mark the tender won first"; "... was already made from ..." (the site exists: **Open site**).
- "The tender is already quoted to ..."; "The main contract is already decided".
- "The rate working is for the estimator and the director" / "Tender editing is not for your role": ask the estimator.
