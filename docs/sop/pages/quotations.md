---
page: /quotations
title: Quotations
routes: /quotations, /quotations/:id, /quotations/:id/working
mark: New quotation
---
A quotation is the techno-commercial offer: the cover letter, the areas with their specification
and budgetary offer, the terms and the client references. Every change made after it is sent can
go into a new revision (R0, R1 ...); every revision is kept. A salesperson sees only the
quotations they made, are salesperson on, or that belong to their leads.

**On the list**
- **Search code, client or project** (box): filters as you type.
- **Status** (filter): draft, sent, negotiation, won, lost, expired; **All statuses** clears it.
- Click the code (e.g. "QTN-... R0") to open the quotation.
- **Total** shows "rates only" when no line has a quantity.
- **New quotation**: opens the **New quotation** dialog. {perm: quotation.edit}

**New quotation** {perm: quotation.edit}
- **From a lead** / **From a client** / **Blank** (tabs): what the quotation starts from.
- **Search leads** or **Search clients**, then **Lead** or **Client**: pick the parent. Its firm, city, contact and state fill the letter.
- **Client firm** and **Project**: required on **Blank**; otherwise left empty they come from the lead or client.
- **City**, **Kind attention**, **Letterhead** (the default letterhead is picked).
- **Start from a preset**: a preset sets the letterhead, the letter, the areas in order, the T&C and the references. Areas ticked below replace its areas.
- **Areas to offer**: tick each area (offer item) to include. An item with several options shows **Opt.A**, **Opt.B** ... ticks. "imported, check" marks an item read from an old file.
- **Build the quotation**: makes R0 as a draft, fills the rates from the rate library and opens the editor. If made from a lead, the lead's "Prepare quotation" task closes.
- **Cancel**: closes without making anything.

**The editor: top of the page**
- The header shows the code, the revision, the status, the client, project, date, validity, letterhead and salesperson; a won quotation links to its **site**.
- **Revision** (drop-down): open another revision of the same quotation. Shown when there is more than one.
- A yellow note "Rates not sent to the lines." appears when the lines' rates differ from the rate working. **Send the rates to the lines** copies the worked rates onto the lines. It is shown to everyone who can edit the quotation, but only roles that see margins (estimator, director) can use it; others get an error.
- **Checks before it is sent**: shown only when something is wrong: coverage written outside the material library, or T&C wording that gives free-issue materials away (what it says and what it should read). {perm: estimate.view}
- **Margin check** / **Hide the margin check**: opens the margin check card (see below). {perm: tender.margin}
- **⤓ Word**, **⤓ PDF**: download the quotation as it is now.
- **⤓ PDF for letterhead paper**: the PDF with the header and footer blank, for printing on letterhead stationery.
- **Issue files** (**Re-issue files** once issued): saves the Word and PDF with this revision and attaches them to the lead's timeline. Re-issuing marks the older files "replaced". {perm: quotation.send}
- **Mark sent**: on the latest revision, in draft or negotiation. See **Sending** below. {perm: quotation.send}
- **Negotiation**: a sent quotation goes into negotiation (the client is bargaining). {perm: quotation.edit}
- **Won** / **Lost**: on the latest revision in draft, sent or negotiation. They open the **won** and **lost** dialogs. {perm: quotation.send}
- **New revision**: copies this revision into the next one (R1, R2 ...) and opens it. A sent quotation moves to negotiation. Not shown on a won quotation. It needs the right to edit quotations; without it the app says "You cannot change this quotation".
- **Rate working**: opens /quotations/:id/working (see below).
- **Changes from R(n)**: shows what changed from the revision before: each line's old and new rate and the % change, quantities, text changes, lines and areas added or removed, and the totals.
- **Quantities from a survey**: opens **Quantities from a site survey**. {perm: quotation.edit}
- **Refill rates**: fills the rates again from their source; rates typed by hand stay. {perm: quotation.edit}
- On a phone the editor is read only: **Share PDF** shares the PDF (or downloads it when the browser cannot share) and **⤓ PDF** downloads it. Edit on a laptop.

**The editor: the outline (left), the preview (centre) and the panel (right)**
- **Cover letter**: **Client firm**, **City**, **Kind attention**, **Project**, **Brand**, **Areas list**, **Date**, **Valid for (days)**, **Guarantee (years)**, **Letterhead**, **Salesperson**, **Signatory name**, **Designation**, **Opening**, **Subject**, **Body**, **Enclosures (one per line)**. **Save** keeps them for this quotation only. {perm: quotation.edit}
- **Save back to library**: writes this letter into its library template as a new version (older quotations keep their copy). {perm: quotation.template.edit}
- **Items**: one row per area, with "area type missing" and an orange "n checks" badge when the specification and the budgetary offer do not agree. Click an area to open it.
- In an area: **Area type** (used for survey quantities), **Area name**, **Budgetary offer title**, **Options offered** (ticks), **Save names**, **Remove area** (asks "Remove ... from this quotation?"). {perm: quotation.edit}
- **Save names back to library**: writes the area's names into the library item. {perm: quotation.template.edit}
- **Technical specification**: open a specification, change its **Title** and sections, then **Save specification** (this quotation only). **Save back to library** writes it into the library block. {perm: quotation.edit}
- **Budgetary offer**: click a line to open it: **Description**, **UoM**, **Rate (₹)**, **Qty** (empty means rate only), **Amount**, **If required**, **Client's scope**. **Save line** saves it for this quotation; **Use the filled rate** drops a typed rate; **Delete** removes the line. {perm: quotation.edit}
- Under a line, the rate's source shows ("Typed here" for a typed rate). Cost, margin % and margin amount show only to roles that see margins. {perm: tender.margin}
- **+ Line**: add a line **From the library** (search and click it) or **Or a new line (this quotation only)** with **Unit**, **Rate (empty: Suggest)** and **Option**, then **Add**. **Cancel** closes it. {perm: quotation.edit}
- **+ Add an area**: opens **Add an area**: pick the **Offer item**, tick its options, **Add**. {perm: quotation.edit}
- **Terms & conditions (n)**: each clause with its **Category**, **↑** / **↓**, **Remove**; **+ From the T&C library** adds library clauses; **Save terms** saves them for this quotation. Lines starting with "- " print as a), b), c). {perm: quotation.edit}
- **References (n)**: **Title**, **State (e.g. Gujarat)**, **Area type**, **Load from the library** (fills past clients of that state and area type), a tick per client to include it, **↑** / **↓**, **Save references**. {perm: quotation.edit}
- **Follow-ups & files**: the **Negotiation log**, the **Follow-ups** and the **Issued files** (each with a download button).
- **Negotiation log**: **What the client asked ("match X on this item")**, **What we gave**, **Revision that followed**, **Log**. Logging tells the estimator and the salesperson "the client asked ... Revise the offer." If no new revision follows in 2 days, the director is told. The form shows to everyone who opens the quotation, but only roles that edit quotations can log; others get "Missing permission".
- **Follow-ups**: made when the quotation is sent, on day 2, 7, 15 and 30. **Done** asks "What did the client say? (optional)" and closes the follow-up; its note goes on the lead's timeline. An overdue follow-up shows red.

**Sending (Mark sent)** {perm: quotation.send}
- First, any area warnings are listed: "Check before sending (warnings, not blocks) ... Send anyway?". Cancel to fix them.
- If the lines' rates differ from the rate working, the app asks "... Send with the rates the lines have now?". OK sends with the lines' rates and the choice is logged.
- The send checklist must pass: **Guarantee (years)** filled, a clause of our scope (category Applicator or our scope) and a clause of the client's scope (**Client's obligations**) from the T&C library.
- If nothing was issued yet, the Word and PDF are issued now.
- The quotation turns **sent**, the follow-ups on day 2, 7, 15 and 30 are made, the lead moves to **Quoted**, and the salesperson is told "... sent to ...: follow-ups on day 2, 7, 15 and 30." The page says "Sent: follow-ups are scheduled."
- When the checklist blocks, the author is told what is missing. The director can send anyway: the app asks for a reason (at least 5 characters) and logs it ("Sent past the checklist (logged)."). {perm: sendcheck.override}

**Won and lost** {perm: quotation.send}
- **Won** opens "... won": for each area with options, pick what **the client chose**; **Site**: **Make a new site** or **Link** an existing site. **Mark won** then:
  - makes the tender (order) record holding the quotation's lines (the chosen option of each area; "if required" lines too; client's-scope lines never), and makes or links the site;
  - makes the client in Clients if the quotation had none;
  - stops all follow-ups, marks the lead **Won**;
  - tells the director "Won: ... Assign the salesperson and the site engineer." (to office admin too if not done in 48 hours);
  - shows "Tender (order) ... holds the quotation's lines; site ... is ready for execution and billing." with **Open the site** and **Close**.
- **Lost** opens "... lost": **Why was it lost?** (required) and **Note (who won it, at what rate…)**. **Mark lost** closes the quotation and stops the follow-ups of all its revisions. Lost quotations count in the closure scorecard.

**The margin check** {perm: tender.margin}
- Shown when the quotation has a rate working. One row per line: **Rate / sqm**, **Material / sqm** (click it to see each product's coverage, wastage, price and how the cost is worked), **Labour / sqm**, **Cost / sqm**, **Material share**, **Margin**, **Warnings**.
- Margin is on the selling price: (rate − cost) ÷ rate. A red margin is a loss.
- A row is flagged when material alone is over the director's limit (70 % unless set): "Material alone is ...% of the rate ... (over ...%)". Other warnings: "No labour estimate in the working: the margin is before labour", "No coverage in the library for ...", "No price for ...", "No rate per sqm to compare with".
- **Material share limit %** and **Save**: the director sets the limit; others see "Material share limit ...% (set by the director)".
- **Free issue (the client supplies)**: tick the products the client gives free. **Save the free issue and its clause** takes them out of our cost and writes the matching clause into the quotation's T&C (under the client's scope).

**Rate working (/quotations/:id/working)**
- Groups the quotation's lines into main items and works the rate of each: consumption × (price + freight) × (1 + wastage) + surface preparation + labour, then the margin.
- Without margin rights you see each main item's rate per sqm and sq ft and its lines only.
- **Suggest the groups** (first time) / **Group again** (asks "Group every line again? The main items and their workings are made afresh."), **Group the rest**, **Move to** on each line (another main item, **→ a new main item…**, **→ not grouped**). {perm: tender.margin}
- **Margin for this working:** **on the selling price** or **on cost**. {perm: tender.margin}
- Per main item: **Main item**, **System**, **Application**, **Surface**, **Client asks: min kg/sqm · DFT mm**, **Wastage %**, **Coats**, **Surface preparation (₹/sqm)**, **Labour rate card (what we pay)**, **Labour in the rate (₹/sq ft)**, **Labour paid (₹/sq ft)**, **Margin %**, and the products with **Consumption**, **Reason (when changed)**, **Price**, **Freight used**, **Freight actual**. **Work the rate** saves and shows the **Build-up per sqm**, the **Cushions (visible, not hidden)**, **Against what we sold at before** and **Against the rate library**. {perm: tender.margin}
- **Rates to the lines**: copies the worked rates onto the quotation lines ("n client line(s) priced from the working"). Lines in another unit are left for you. {perm: tender.margin}
- **Mark final: add to the library**: adds the working to the BOQ knowledge as new evidence ("Added to the library: n main item(s)."). It also needs the knowledge edit right; without it the app says "Missing permission: knowledge.edit". {perm: tender.margin}
- **Working sheet (Excel)**: downloads the internal working. {perm: tender.margin}

**Rules**
- Only the latest revision can be changed, and only while it is draft, sent or in negotiation. A won, lost or expired quotation is changed by a new revision (not after won).
- Changes on the panels stay in this quotation; the library changes only with a **Save back to library** button.
- A sent or negotiating quotation past its validity turns **expired** by itself and its follow-ups stop.
- A salesperson's new quotation always has themselves as salesperson. {perm: quotation.edit}
- There is no separate approval button: the send checklist is the gate, and only the director can send past it.

**Hands off**
- Receives: leads (from the salesperson or planning), the rate working and margin (estimator), Kylas leads at the quotation stage ("Make the quotation").
- Passes on: the won quotation to the director (assign the salesperson and site engineer); the tender (order) and site to execution and billing; rate change requests to the estimator through the negotiation log.

**When it goes wrong**
- "Give the client firm and the project": fill **Client firm** and **Project** (or pick the lead or client).
- "You cannot make quotations" / "You cannot change this quotation" / "You cannot send or close this quotation": your role or scope does not allow it; ask the salesperson or the director.
- "R... is an old revision: change the latest one (or make a new revision)": open the latest revision with **Revision**.
- "... is won/lost/expired: make a new revision to change it": press **New revision**.
- "A won quotation is not revised" / "Make the new revision from the latest one".
- "... cannot be sent yet: Guarantee years not filled; Our scope not attached from the T&C library; The client's scope not attached from the T&C library": fill **Guarantee (years)** on the cover letter, add the clauses with **+ From the T&C library**, **Save terms**, then **Mark sent** again.
- "Only the director can send past the checklist": fix what is missing instead.
- "...: ... (largest difference ₹...). Send the rates to the lines from the rate working, or confirm the lines' rates.": ask the estimator to send the rates, or confirm the lines' rates when asked.
- "Only a sent quotation goes into negotiation"; "Change the status on the latest revision"; "The quotation is already ..."; "A ... quotation cannot be sent" / "cannot be won".
- "Choose why the quotation was lost": pick a reason.
- "The rate working is for the estimator and the director": shown if you press **Send the rates to the lines** without margin rights. Ask the estimator.
- "... say why the consumption differs from ... for this site": write a reason of at least 3 characters next to the changed consumption.
- "R... was submitted: its working is kept as it was; work on the new revision".
- "You cannot see surveys": your role has no access to surveys; ask the site engineer for the quantities.
- A follow-up's **Done** shows no message if it fails; reload the page and check the follow-up's status.
