---
page: /sites
title: Sites
routes: /sites, /sites/:id, /sites/:id/new-area, /sites/:id/fronts, /sites/:id/takeoff, /sites/:id/building, /sites/:id/material-plan, /sites/:id/zones
mark: New site
---
The list of the sites you may see, and each site's own page. A site holds its places (towers,
floors, flats, rooms), what we do where (scopes), the stages and steps of the work, the drawings,
the 3D view, the team and every execution record. Roles that work on assigned sites only (site
engineer, site supervisor, sales) see only the sites where they are the in-charge or in the team.

**On the page**
- **Search code, name, client or city** (field): type and press Enter. The list shows the sites whose code, name, client or city match.
- **Status** (filter): **All statuses**, **Planned**, **Active**, **On hold**, **Completed** or **Closed**.
- **Client** (filter): **All clients** or one client.
- **Channel** (filter): **All channels** or one channel (the contractor or consultant the job came through).
- **In-charge** (filter): **Any in-charge** or one person.
- **Source** (filter): **App + Powerplay** (all), **Made in the app** or **Past (Powerplay)** (sites brought over from the old system).
- **Late** (tick): only the sites past their target date that are not completed.
- **⤓ Export Excel**: downloads the list as it is filtered. It shows "Exporting…" while it works.
- **New site**: opens the **New site** form. {perm: site.edit}
- The table: **Code**, **Name** (with the city, and a **Powerplay** badge for old sites), **Client**, **Channel**, **Status**, **Progress**, **In-charge** and **Target**. Click a row to open the site.
- **location missing** (badge next to the status): a planned, active or on-hold site with no pinned location. Check-ins at this site cannot be checked. Pin it in the site's **Location & visits** section.
- **Margin %** (column): the site's margin so far. It is red with ⚠ when the cost to date is more than what is billed. Only shown to roles that see both margins and bills. {perm: tender.margin}
- **Target** in red: the site is past its target date and not done.
- "No sites found." means nothing matches the search and filters.

**The New site form** {perm: site.edit}
- **Name \***: the site's name. It is the only field you must fill. {perm: site.edit}
- **Status**: starts as **Planned**. Set **Active** when work begins. {perm: site.edit}
- **Client**: pick the client, or leave "— unknown —". {perm: site.edit}
- **Channel**: the contractor or consultant, or "— direct —". {perm: site.edit}
- **Site in-charge**: the person who runs the site. The in-charge always sees the site, even with access to assigned sites only. {perm: site.edit}
- **City**, **State**, **Address**, **Notes**: free text. {perm: site.edit}
- **Start date** and **Target date**: the start date also sets the year in the site code. The planned dates of the generated tasks start from the start date. A site past its target date shows as late. {perm: site.edit}
- **Latitude / longitude**: the site's pin (for example 23.0225 and 72.5714). Without it, check-ins at the site cannot be checked. {perm: site.edit}
- **Create site**: saves the site and opens its page. **Cancel** closes the form without saving. {perm: site.edit}

**Rules**
- The site gets the next code of its start year, S-<year>-<number> (for example S-2026-0001). The code cannot be changed. {perm: site.edit}
- A new site also gets its own store, so material can be received and issued there. {perm: site.edit}
- A site made from a won tender is made on the tender's page, not here. It takes the tender's client, channel, city and priced BOQ lines, and the tender's methodology. Its BOQ lines are then put on places in the **Scope** section.
- Only roles that create and edit sites can create a site or change its details, team, structure and scope. {perm: site.edit}

**Hands off**
- Receives: a won job. The director picks its salesperson and site engineer on the won-job page. That makes the site in **Planned** status (or links the tender's site), with the engineer as in-charge. Sites without a tender are created here by the director or the office admin.
- Passes on: the site with its places, scopes and tasks. The site engineer and the site supervisor post the work. Planning plans the material. Billing measures and bills.

**When it goes wrong**
- "Unknown client", "Unknown channel" or "Unknown user for the site in-charge": the client, channel or person was removed while the form was open. Close the form, open it again and pick again. {perm: site.edit}
- "Site not found": the site does not exist, or it is not one of your sites. Ask the director or the office admin to add you to the site's team.
- A site you expect is missing from the list: clear the search, set **Status** to **All statuses** and **Source** to **App + Powerplay**. If it is still missing, you are not in its team.

### The site page: header and sections

Opened by clicking a site in the list. The header shows the site's code, name, client, channel,
the tender it came from (a link) and the target date (red when late).

**On the page**
- **Back to sites**: goes back to the page you came from, or to the list.
- The status chip: "<n>% done · " then **late**, **on hold**, **not started** (a planned site), **done** (100 %) or **in progress**.
- **Update work**: opens **My site today** for this site, where the day's work, material and report are posted. {perm: site.update}
- The section tabs. The first seven sections you may open are tabs. The rest are in the **More** list, under "Sections".
- The sections and who sees them: **Overview**, **3D building**, **Stages**, **Drawings**, **Site visits**, **Process**, **Handover**, **Location & visits**, **Structure** and **Scope** are shown to everyone who opens the site. **Daily reports**, **Materials**, **Measurements & bills**, **Plan & lots**, **Labour**, **Inspections**, **Work orders**, **MOM**, **Assets**, **Budget** and **Portal** need their own rights (see each section below).
- The **More** list also has an "Open" group with the site's other pages. Each shows only with its right: **Surveys**, **Work fronts**, **Material plan**, **Measurement book**, **AutoCAD takeoff**, **Measure and bill**, **Methodology**, **RFI zones**, **Measure**, **Billing checklist**, **Material reconciliation**, **Labour claims**, **Bills**, **Work completion** and **Issues**.
- On a phone, the tabs are one list called **Section**. The other pages are in it as "Open: <page>".

### Overview

The site's details, the gaps to chase, and the team.

**On the page**
- **Site details**: **Code**, **Client**, **Channel**, **Address**, **Location**, **Start**, **Target**, **In-charge**, **Source** ("This app" or "Powerplay (<ref>)") and **Notes**.
- **Edit**: opens the "Edit <site code>" form, with the same fields as the New site form. **Save** keeps the changes. {perm: site.edit}
- "DPR missing on <n> day(s) in the last 30 (latest <date>) · write it": days without a daily report. **write it** opens the **Daily reports** section. When nothing is missing it says "Every DPR of the last 30 days is in." {perm: dpr.view}
- **Open MOM points (<n>)**: action points from meeting minutes that are still open, with the MOM code and due date. Overdue points are red. {perm: inspection.view}
- **Late tasks (<n>)**: up to 15 steps past their planned end, with the place and the due date. "Nothing is late." when none.
- **Team on site**: each person and their **Role on site**.
- **Member** (field per row): pick the person. {perm: site.edit}
- **Role on site** (field per row): **incharge**, **supervisor**, **sales**, **office**, **viewer** or **receiver**. {perm: site.edit}
- **Remove**: takes the person off the list. {perm: site.edit}
- **Add person**: adds a row with the first person in the list as **supervisor**. Change the person and the role. {perm: site.edit}
- **Save team**: saves the whole list. Nothing changes until you press it. {perm: site.edit}

**Rules**
- Being in the team is what lets the site engineer, the site supervisor and sales see the site. Notifications meant for "the site's engineer" or "the site's supervisor" go to the team member holding that role.
- **Save team** replaces the whole team with the list on screen. A row removed and not saved is still in the team. {perm: site.edit}
- Changing the status to **Closed** stops new indents for the site. {perm: site.edit}
- Every change to the details and the team is kept in the audit log, with the before and after. {perm: site.edit}

**When it goes wrong**
- "A person is listed twice": the same person is on two rows. Remove one and save again. {perm: site.edit}
- "Unknown user id": a picked person no longer exists. Reload the page and pick again. {perm: site.edit}
- "You cannot change the site on this site": your right to edit sites does not cover this site. Ask the director or the office admin. {perm: site.edit}

### Overview: site control strip

A row of warnings and one setting at the top of the **Overview** tab. Each badge only shows when its count is above zero. Clicking a badge opens the list behind it.

**On the page**
- **n delivery not confirmed** (amber badge): delivery notes for this site that nobody has confirmed yet. Opens Deliveries filtered to this site and to the unconfirmed ones.
- **n new area waiting** (blue badge): areas the site asked for that are still pending. Opens the New areas page.
- **n consumption off the system** (red badge): products used outside the learned range on this site's areas. Opens Consumption for this site.
- **+ New area**: opens the form to ask for an area that is not in the scope (the New area page of this site). It is shown to everyone, but the form only opens for roles that may update or edit the site; others see "No access".
- **Receiver when the supervisor is away**: the named person (and phone) who may confirm deliveries when the supervisor is not on site. Shows "none named" when nobody is set.
- **Change**: opens the **Named receiver** box. {perm: site.edit}
- **Name** and **Phone** (fields in the box): the receiver's name (up to 100 characters) and phone (up to 20). Leave both empty to remove the receiver. {perm: site.edit}
- **Save**: stores the receiver and closes the box. The change is logged. {perm: site.edit}

**Rules**
- Name a receiver only for people who really take deliveries for you (labour leader, applicator). Anyone else who confirms a delivery is flagged for review.
- Only roles that edit sites can change the receiver, and only on a site they may edit. {perm: site.edit}

**What happens next**
- The receiver can confirm deliveries in place of the supervisor. Their confirmation is not flagged.
- The badges clear by themselves when the deliveries are confirmed, the new areas are decided and the consumption is back in range.

**When it goes wrong**
- "No access" after **+ New area**: your role cannot ask for new areas. Ask the site engineer or the supervisor of the site.
- The **Named receiver** box stays open after **Save**: the save was refused (for example "You cannot change this site" when the site is not one you may edit). The app shows no message. Close the box and ask a director or the office admin. {perm: site.edit}

### 3D building

The site in 3D, coloured by the state of the work. It has two forms. Until a building model is
made from the AutoCAD drawing, it shows **schematic** boxes built from the **Structure** section.
Once a model exists, it shows the **X-ray** view of the real building. Both refresh every minute.

**Schematic view: on the page**
- "Schematic: Boxes from the site structure, not the real building." is shown above the view.
- **Build from AutoCAD**: opens the building model page (see "Building model" below). {perm: building.edit}
- **Work status** (tab): each place coloured by its work: **Done / certified**, **In progress**, **Waiting at a hold point**, **Blocked**, **Not started (scheduled)** and **No work here** (see-through). Late places get a **Late** outline. The legend gives the count of each. Floors and towers show their rolled-up % (grey to green).
- **Realistic** (tab): plain building tones (concrete floors, brick flats, tiled wet areas).
- **Survey** (tab): each place coloured by its approved surveys: **Measured (laser / by hand)**, **Measured by camera only** or **Not measured**. Ready work fronts get a blue outline, "Work front ready (<n>)". {perm: survey.view}
- "Approved surveys only · <n> area(s) not placed on the structure": surveyed areas that are not tied to a place. Their quantities are missing from the 3D and from the per-place totals. Map them to a place in the survey. {perm: survey.view}
- **Products · <place>** (side panel in **Survey**): the product totals of the approved surveys, floor by floor, for the clicked tower or floor, or the whole site. **Whole site** goes back to the site total. {perm: survey.view}
- **Reset view**, **Top** and **Front**: move the camera. They are grey when nothing is shown.
- **Below ground** (tick): shows basements and other places below ground. Shown only when the site has them.
- **Floors up to** (slider): hides the floors above the chosen one ("all", G, B1 ...).
- **Open floor…** (list): cuts the building open at one floor and shows its flats and rooms. You can also click a floor in the view. **Show all floors** closes the cutaway.
- **Work** (filter): **All work** or one stage template. Places without that work turn see-through.
- **Status** (filter): **All statuses** or one state from the legend.
- **Save image**: downloads a PNG of the view with the site name, code, date, overall % and the legend. Grey until the site has a structure.
- Hover a place to see its name, % done, AutoCAD area, current and next step, "Waiting for certification" and "Late".
- "No structure yet. Add a tower in the Structure tab." with **Go to the Structure tab** when the site has no places.

**X-ray view: on the page**
- **Drawing** and **BIM (IFC)**: switch between the model from the AutoCAD drawing and the client's BIM file. Shown only when a BIM file was uploaded.
- **X-ray**, **Status** and **Realistic**: the view mode.
- **Rooms first**: dims the building and lights up our rooms.
- **Explode**: spreads the floors apart.
- **Open a floor (cutaway)** (list): "Floor: All floors" or one floor.
- **⋯** (more tools): **Reset**, **Top**, **Front**, **Iso**, **Save image** and **Glow** (**Glow: auto**, **Glow: on**, **Glow: off**).
- The legend with counts, **Overall progress** with the % and the next step.
- The replay bar: play / pause, **Progress on a date** (slider) and the date ("Today" at the end).
- **Save video for client**: records the replay as a short WebM video (at most 30 s). It shows "Recording…" meanwhile.
- The room list of the open floor: click a room to see it.
- "Built from the AutoCAD drawing (model version <n>). **Edit the building model**": opens the building model page. {perm: building.edit}
- In **BIM (IFC)**, clicking an element opens **Our place**: link it to one of our places ("— not linked —" to unlink), then **Close**. Linked elements are coloured by that place's work. {perm: building.edit}
- A BIM file larger than the site's laptop limit is not opened at once. The app warns that it may freeze the browser. **Open it anyway** opens it.

**The selected place (both views)**
- Click a room (or a flat) to open its panel: the name, the size (sunk depth and wall height in the X-ray), the state with "step <n> of <m>", the steps with their dates, and the last 3 photos.
- **×**: closes the panel.
- **Update this step**: opens the current step in the same box as in **Stages**. Grey when every step is done. {perm: site.update, site.edit}
- **Raise a snag**: opens the snag form for this site and place.
- "No work scheduled here." means the place has no scope and no tasks.

**When it goes wrong**
- "This browser cannot draw 3D here (WebGL is off or not supported), so the camera buttons are hidden": use another browser or turn on hardware acceleration.
- "The BIM file could not be read: <reason>": ask for a lighter IFC export (one building, no furniture). {perm: building.edit}
- "Upload the IFC file first" or "Place not found on this site" when linking: reload the page. {perm: building.edit}

### Stages

Every step of the work, place by place. Steps are made by **Generate tasks** in **Scope**: one
task per step of the stage template, for every place the work is assigned to. The heading reads
**Tasks (<n>)**.

**On the page**
- **Show** (filter): **All tasks**, **Late**, **Blocked** or **Waiting for certification**.
- **List** and **Gantt**: the table, or bars on a time line. In the Gantt, grey is planned, coloured is actual and the red line is today.
- The table, grouped by place: **Step** (with **hold point** and **checklist** badges), **Weight** (its share of the stage), **Planned**, **Actual**, **Status** (**Not started**, **In progress**, **Done**, **Certified**, **Blocked**) and **Assignee**. A red planned date means late.
- "No tasks. Assign the BOQ to areas on the Scope tab, then "Generate tasks"." when the site has none.
- Click a step to open its box.

**The step box**
- The line under the title: the planned dates, the weight, "hold point: the office certifies it before the next step" and the certification time.
- **Status**: **Not started**, **In progress**, **Done** or **Blocked**. {perm: site.update, site.edit}
- **% done**: 0 to 100. Setting **Done** makes it 100. {perm: site.update, site.edit}
- **Remark**: a note on the step. {perm: site.update, site.edit}
- **Inspection checklist**: for steps that need an inspection. Each **Check item** gets **Pass** or **Fail**. **×** removes an item. **Add check** adds one. {perm: site.update, site.edit}
- **Photos**: the step's photos. "required to finish" means **Done** needs at least one.
- **Share with client** (tick under a photo): shows the photo in the client portal. {perm: site.update, portal.manage}
- **Add a photo**: takes or picks a photo (jpg, png, webp or heic, up to 15 MB). It is saved at once. {perm: site.update, site.edit}
- **Certify hold point**: shown on a finished hold-point step. It asks for an optional "Certification remark (optional)" and marks the step **Certified**. {perm: site.edit}
- **Save**: saves the status, % done, remark and checklist. **Close** closes the box without saving.

**Rules**
- A step cannot start or finish before the step before it is done. {perm: site.update, site.edit}
- After a hold-point step (a ponding test, for example), the next step waits until the office certifies it. {perm: site.update, site.edit}
- **Done** needs a photo when the step asks for one, and every inspection item passed when the step has a checklist. {perm: site.update, site.edit}
- The last step of a stage is **Done** only after the quality checklist of each checklist step in that stage is completed and passed. {perm: site.update, site.edit}
- Certifying needs a passed inspection with its checklist, made in **Inspections**. {perm: site.edit}
- A certified step is locked. Only roles that edit sites can change it. Moving a step back to **Not started**, **In progress** or **Blocked** clears its finish date and its certification. {perm: site.update, site.edit}
- Only done and certified steps count in the progress. A hold-point step counts only once certified.

**What happens next**
- The place's, floor's, tower's and site's % are worked out again at once. The 3D view shows it within a minute.
- When the last step of a stage on a place is done, the place is "ready to bill". Billing is told "Work done on <date>: make the stage bill." and the salesperson is told billing makes it. The director is reminded after 7 days if the bill is not made.
- When every stage of a place is done, the place's finish date is recorded for the schedule.

**When it goes wrong**
- "'<step>' is not done yet": finish the step before it first. {perm: site.update, site.edit}
- "'<step>' is a hold point: the office must certify it before the next step starts": ask the office (director or office admin) to certify it. {perm: site.update, site.edit}
- "Add a photo before marking this step done": add a photo, then save **Done** again. {perm: site.update, site.edit}
- "Every inspection item must pass before this step is done": mark every item **Pass**, or fix the work first. {perm: site.update, site.edit}
- "Complete the quality checklist '<checklist>' for '<step>' before the stage is marked done": do the checklist in **Inspections**, then mark the step done. {perm: site.update, site.edit}
- "This step is certified": only the office can change it now. {perm: site.update}
- "You cannot post progress on this site": you are not in this site's team. Ask the director or the office admin. {perm: site.update, site.edit}
- "The step must be done first" or "This hold point needs a passed inspection with its checklist first (Inspections tab)": the step is not done, or its inspection is missing or failed. {perm: site.edit}
- "Upload a photo (.jpg, .png, .webp or .heic)" or "The photo is larger than 15 MB": take the photo again with the phone camera. {perm: site.update, site.edit}

### Stages: quality checklist

Below the stages, per area: each stage's start and end, our sign and the client's. Shown to roles with the site close-out or billing close-out work.

**On the page**
- One row per area with "n stages", our signs "n/n" and client signs "n/n". Click the row to open its stages (all are open when the site has three areas or fewer).
- Per stage: **Started**, **Ended**, **Our sign**, **Client's sign**.
- **Sign (with dates)**: asks "Stage started on (YYYY-MM-DD)" then "Stage ended on (YYYY-MM-DD)", then signs the stage for us. {perm: closeout.site}
- **Record the signed copy**: pick the photo or PDF of the paper the client signed, then answer "Who signed for the client (name and designation)?". Shown after our sign. {perm: closeout.site}
- "waiting for the client": we signed, the client has not. "after our sign": we have not signed yet.
- "✓ <name> (in the app)" or "(recorded by staff)": how the client signed.

**Rules**
- A stage cannot end before it started.
- Once the client has signed, the stage's sign is locked for every role.
- The client signs in the portal, or staff record the signed paper.

**What happens next**
- Our sign opens the stage for the client's sign in the portal ("waiting for the client").
- Recording the signed copy marks the client's sign as done, with the name and the copy kept.

**When it goes wrong**
- "The stage cannot end before it started": enter the dates again. {perm: closeout.site}
- "Stage <name> (signed by the client) is locked: it cannot be changed or deleted. Make a new revision or an addendum.": the client already signed. Nothing more to do. {perm: closeout.site}
- "Missing permission: closeout.site": your role cannot see the checklist.

### Daily reports

The tab is shown with the permission to view daily reports (dpr.view). It holds one daily progress report (DPR) per site per day. What was recorded on site that day (labour, task updates, material in and out, equipment) is pulled in by itself; the supervisor adds the story and submits it, and the site engineer approves or returns it.

**On the page**
- **Day** (field): the day of the report. It opens on today. A future day cannot be picked.
- The status badge next to the day: **Not started**, **draft**, **submitted**, **approved** or **returned**.
- **PDF**: downloads the report as a PDF. Shown once the report is past draft.
- **Recorded today**: the day's labour (present, half days), **Task updates**, **Material in**, **Issued** and **Equipment**, taken from what was entered on site. It is live while the report is a draft and frozen when it is submitted.
- **Show all n task updates** / **Show fewer**: shows the full list when there are more than five task updates.
- **Weather** (buttons): **Sunny**, **Cloudy**, **Light rain**, **Heavy rain**, **Hot**, **Windy**. {perm: dpr.edit}
- **Work done today \*** (field): where, what and how much. It must be filled before the report can be submitted. {perm: dpr.edit}
- **Work by place**: one line per place worked on: **Place** (the place on the site's list, or a new area still waiting for planning), **What was done**, **Qty**, **Unit** and **People**. **×** removes a line. {perm: dpr.edit}
- **+ Add work on a place**: adds a line. {perm: dpr.edit}
- **Hindrances** and **Plan for tomorrow** (fields): free text. {perm: dpr.edit}
- **Take / add photos**: takes or picks photos; each is added to the report at once. {perm: dpr.edit}
- **Save draft**: keeps the report as a draft. The message "Saved as draft." shows. {perm: dpr.edit}
- **Submit DPR**: sends the report for approval. The message "Submitted." shows. The button stays greyed out until **Work done today** is filled. {perm: dpr.edit}
- **Approve**: approves a submitted report. It then shows as **approved**. {perm: dpr.approve}
- **Return**: asks "Return to the supervisor: what needs correcting?" and sends the report back with your comment (at least 3 letters; a shorter answer does nothing). {perm: dpr.approve}
- **Last 31 days**: the reports of the last month with their status (an approved report shows here as "acknowledged"), weather and who submitted it. Click a row to open that day.

**Rules**
- A report can be written and changed only while it is new, a draft or returned. Once submitted, it is read-only for everyone.
- Every line of **Work by place** must name a place when the site has a list of places.
- **Approve** and **Return** show only on a submitted report, and only to the site engineer of the site, or to an office role that can write reports for every site.
- Approving moves progress: each line's quantity is added once to the open scope of its place (same unit). A scope that reaches 100 % becomes ready to bill, as a finished stage does.
- Photos can be added only while the report is a draft.
- A to-do or notification about a report opens this tab on today's date: pick the report's day in **Day** or in **Last 31 days**.

**What happens next**
- Submit: the site engineer gets the to-do "Daily report of <date> for <site>: approve or return." After 24 hours without an answer it goes up to planning. Client users who see daily reports in the portal are told a new report is in.
- The first submitted report on a place tells planning that work started there, and the site moves to "ongoing" on the status board.
- A line on a new area that is still waiting tells planning and the salesperson that work is going on in an area not in the quotation ("Quote or approve"). After 48 hours it goes up to the director.
- Return: the supervisor who submitted gets "Daily report of <date> returned: <comment>". The report shows "Returned by …: <comment>. Correct it and submit again."

**Hands off**
- Receives: the day's attendance, task updates, material and equipment entries made on site by the supervisor.
- Passes on: the submitted report to the site engineer; approved quantities to the site's progress and ready-to-bill list.

**When it goes wrong**
- "A DPR cannot be written for a future day": pick today or an earlier day.
- "The DPR of <date> is already submitted" (or approved): it can no longer be changed. Ask the site engineer to return it if it needs a correction.
- "Write the work done before submitting": fill **Work done today**.
- "Pick the area it was used on (from the site's list), or ask for a new area": a line has no **Place**. Pick one, or ask for a new area first.
- "That area is not on this site's list: ask for a new area" / "That new area is not open on this site": the place was removed or the new area was rejected. Pick another place.
- "The DPR is already submitted": photos were added to a report that is not a draft. This also happens on a returned report: correct and submit it without new photos, or note them in the text.
- "The site engineer approves daily reports" / "The site engineer returns daily reports": you cannot approve or return on this site.
- "The DPR is acknowledged" (or returned): someone else already acted on it. Pick the day again to reload it.

### Materials

The site's material in one place: stock in the site store, indents, transfers, issues and returns, and goods received. The tab is shown to roles that can see indents, stores, GRNs or POs; each part below shows only with its own permission.

**On the page**
- **Stock at site** (tile): the value of the stock in the site's store, with a link to the store.
- **Issued to work** (tile): the value issued to work on this site, net of returns.
- **Freight charged** (tile): freight charged to the site, split into inbound and godown → site.
- **New indent**: opens the **New indent** form for this site. **Save draft** keeps it as a draft. **Submit for approval** sends it for approval. {perm: indent.create}
- **Receive material (GRN)**: opens the **New GRN** form for the site store. Shown only when the site has a store. **Save draft** or **Submit for approval**; the stock goes in only when the GRN is approved. {perm: grn.edit}
- **Issue to work**: opens **Issue material to work**. Pick **For task** (or "— general site use —"), **Date**, **Remark** and the lines, then **Issue**. The stock leaves the site store at its average rate. {perm: store.edit}
- **Return to store**: opens **Return unused material to the store**. Fill **Date**, **Remark** and the lines, then **Return**. The stock goes back at the average rate. {perm: store.edit}
- **Request / send transfer**: opens **Transfer material** into this site's store. Fill **From**, **To**, **Transporter**, **Vehicle no**, **Freight (₹, charged to the receiving site)**, **Remark** and the lines. Tick **Dispatch now (stock leaves the sending store)** to send at once (button **Dispatch**); leave it to only ask (button **Save request**). {perm: store.edit}
- **Stock** (table): every product in the site store with its quantity. {perm: store.view}
- **Indents** (table): the site's indents. Click a row to open it. From there you can **Edit**, **Submit**, **Cancel indent**, **Reject**, **Approve** or **Create PO**, as your role allows. {perm: indent.view}
- **Transfers** (table): transfers to and from the site. **Dispatch** sends a saved request; **Receive** opens the receive form for a transfer that arrived. {perm: store.view}
- **Issues & returns** (table): every issue and return on the site. {perm: store.view}
- **Received at site (GRN)** (table): goods received into the site store. Click a row to open the GRN. {perm: grn.view}

**Rules**
- You can only issue what is in the store, unless the company allows negative stock.
- Freight on a transfer is charged to the receiving site.

**What happens next**
- A submitted indent waits for approval. When it is approved, store and purchase is told to place the PO.
- A received transfer or an approved GRN adds to **Stock**. An issue lowers it and adds to **Issued to work**.

**When it goes wrong**
- "Only n unit of product in store; n asked": there is not enough stock for the issue. Lower the quantity, or bring the material in first (transfer or GRN). {perm: store.edit}
- "That task is not on this site": the task picked belongs to another site. Pick again. {perm: store.edit}
- "Pick two different stores": a transfer's **From** and **To** are the same store. {perm: store.edit}
- **Receive material (GRN)** is missing: the site has no store yet. Ask store and purchase to add one. {perm: grn.edit}

### Measurements & bills

The tab is shown with the permission to view client billing (billing.view). It holds the site's client contract, its running (RA) bills and invoices, and, for roles that see margins, the site's profit.

**On the page**
- **Billing** and **Cost to date** cards: billed, certified, received, advance, retention, contract value; cost by head, **Total cost**, **Gross profit** with margin %, and the projected profit. "Cost to date is more than what is billed." shows in red when it is. {perm: tender.margin}
- When there is no contract: "No client contract yet." and **Make the contract from the won tender**, which makes the contract from the won tender's priced BOQ. {perm: billing.edit}
- **Contract value** and **Terms** tiles: GST, SAC, retention, TDS, advance and its recovery.
- **New RA bill (from progress)**: makes a draft RA bill with the quantities suggested from the measurement book, and opens it. {perm: billing.edit}
- **Extra item**: opens **Extra item beyond the BOQ** with **Description**, **Unit**, **Qty**, **Rate**; **Add** saves it. It is billable once approved. {perm: billing.edit}
- **Approve extra: <item>**: approves a waiting extra item. {perm: billing.approve}
- The RA bills list: **RA bill**, **Period to**, **Submitted**, **Certified**, **Net**, **Status**, and **PDF**. Click a row to open it.
- **Invoices**: the site's tax invoices.

**Inside an RA bill**
- Each line: BOQ, previous, suggested, this bill, certified and cumulative quantity, rate and amount. **This bill** is typed on a draft; **Certified** is typed once submitted. {perm: billing.edit}
- **Other deduction (₹)**, **Reason** and, when certifying, **Certified by (client)**. {perm: billing.edit}
- **Save** and **Submit to client** (on a draft). {perm: billing.edit}
- **Record certification**: records the client's certified quantities. {perm: billing.edit}
- **Confirm client certification**: accepts what the client certified in the portal. {perm: billing.edit}
- **Back to draft**: reopens a bill the client certified or rejected. {perm: billing.edit}
- **Raise tax invoice**: on a certified bill. {perm: billing.edit}
- **Cancel bill**: asks "Cancel <code>? It keeps its number." and cancels it. {perm: billing.edit}

**Rules**
- Quantities come only from the measurement book, never straight from progress.
- A bill cannot go beyond the BOQ quantity or beyond what is measured. The excess is billed as an approved extra item.
- One draft RA bill at a time per contract.
- The certified quantity cannot be more than what was submitted.

**What happens next**
- **Submit to client**: client users who see billing in the portal are told; the salesperson gets "follow up for certification", and accounts are told a receipt is expected. After 15 days without certification the salesperson is reminded.
- When the client certifies less than billed, billing and the salesperson are asked to give the reason; after 3 days it goes up to the director.

**When it goes wrong**
- "<site> already has a contract": reload the tab.
- "Finish (submit or cancel) the draft RA bill first": open the draft and finish it.
- "'<item>': <qty> is beyond the BOQ qty …; bill the excess as an extra item (approved with billing.approve)": lower the quantity, or add an extra item.
- "'<item>': <qty> is more than the measurement book (…); add the measurement first": record the measurement first.
- "'<item>' is an extra item not approved yet (billing.approve)": have the extra item approved first.
- "Nothing to bill": the bill is empty.
- "Billing checklist: …": the bill's checklist has open points; clear them first.
- "The certified qty cannot be more than the qty submitted": lower the certified quantity.
- "Missing permission: billing.edit": you can read the bills of this site but not change them.

### Drawings

The site's drawings with every revision (R0, R1 ...). Each revision is a draft until it is
approved or rejected. The AutoCAD takeoff and the building model read the .dwg drawings kept here.

**On the page**
- **Drawings (<n>)**: each drawing with its title, discipline and place, then **Approved: R<n>** or **No approved revision**, and **Latest: R<n> (<status>)** when a newer revision is not approved yet.
- **Upload drawing**: opens **Upload a drawing**. {perm: site.update, site.edit}
- **Title \***, **Discipline** (**architectural**, **structural**, **waterproofing** or **other**) and **Place (optional)** (**Whole site** or one place). {perm: site.update, site.edit}
- **Choose the drawing**: PDF, PNG, JPG or DWG, up to 50 MB. It is saved as R0. **Upload** saves it. {perm: site.update, site.edit}
- **New revision** (on a drawing): pick the new file. It is saved as the next revision, as a draft. Older revisions stay as they were. {perm: site.update, site.edit}
- **Share with client** (tick): shows the drawing in the client portal. {perm: site.update, portal.manage}
- The revision rows: the revision, the file name (click to download it), size, who uploaded it and when, and its status (**draft**, **submitted**, **approved**, **rejected**) with the approver and remark.
- **Submit** (on a draft): marks it **submitted**, ready for approval. {perm: site.update, site.edit}
- **Approve** (on a draft or submitted revision): asks for an optional remark and marks it **approved**. The newest approved revision becomes the drawing's current one. {perm: drawings.approve}
- **Reject**: asks "Reject R<n>: why?" and marks it **rejected**. {perm: drawings.approve}

**Rules**
- A reject needs a remark. {perm: drawings.approve}
- An approved or rejected revision cannot be changed. Upload a new revision instead.
- Nobody is notified when a revision is uploaded or submitted. Tell the approver (director or office admin). {perm: site.update, site.edit}
- Work only from the approved revision shown in the green badge.

**When it goes wrong**
- "Upload a drawing as PDF, PNG, JPG, DWG or DXF": the file is of another kind. Save it as one of these. {perm: site.update, site.edit}
- "The drawing is larger than 50 MB": save a lighter copy (fewer layouts, no images) and upload it again. {perm: site.update, site.edit}
- "R<n> is already approved" (or rejected, or submitted): someone acted on it first. Reload the page.
- "Give a remark when rejecting a drawing": write why, then reject again. {perm: drawings.approve}
- "The file is missing": the stored file is gone from the server. Upload the revision again. {perm: site.update, site.edit}

### Site visits

The visits logged at this site: date, who went, notes, photos and whether the phone's location was saved. The list and the button show only for roles that log site visits; other roles see an empty tab.

**On the page**
- **+ Log a visit**: opens **Log a site visit**. {perm: sitevisit.log}
- **Date** (field): the day of the visit. Today by default. {perm: sitevisit.log}
- **Notes (who you met, what was agreed)** (field, required): at least 3 characters. {perm: sitevisit.log}
- **Photos** / **Choose photos**: one or more photos; on a phone it opens the camera. {perm: sitevisit.log}
- The location line: the GPS position and accuracy when the phone allows it, else "Location is saved when the phone allows it." {perm: sitevisit.log}
- **Save visit**: saves the visit with its photos and GPS. **Cancel** closes without saving. {perm: sitevisit.log}
- Each line of the list: date, who, notes, "n photo(s)", "GPS", and the badge **first visit after the win** on the salesperson's first visit after the job was won. {perm: sitevisit.log}

**Rules**
- A role with "own" scope sees only its own visits. {perm: sitevisit.log}
- You can log a visit only on a site you are on, unless your role covers every site. {perm: sitevisit.log}

**What happens next**
- After a job is won and the team is assigned, the salesperson gets the task "make the first site visit". Logging the first visit closes that task and marks it **first visit after the win**. {perm: sitevisit.log}
- The visit shows as a step on the site's **Process** tab.

**When it goes wrong**
- "Not your site": you are not a member of this site. Ask for the site to be added to you. {perm: sitevisit.log}
- An error about the notes being too short: write at least 3 characters. {perm: sitevisit.log}
- No GPS on the visit: the phone blocked the location. Allow location for the app and log the next visit standing at the site. {perm: sitevisit.log}

### Process

The site's chain from enquiry to payment, one step per process rule. It shows who did each step and when, and which step the site is waiting on. Nothing is edited here.

**On the page**
- **Process: enquiry to payment**: the steps in order, numbered as in Settings > Process rules.
- Each step shows who did it ("the app" when it was automatic), when, and "(n times)" if it happened more than once.
- A step not yet done shows "not reached yet".
- The current step is highlighted. When it waits, it shows "waiting on <role> for <hours or days>", and "escalated" in red once it has been escalated.
- "Closed without the action by <person> on <date>: "<reason>"": someone closed the notice without doing the step in the app, and why.

**Rules**
- Each step tells the next role by an in-app notice (and email for staff), and chases it if nothing happens. The waiting time and escalation come from Settings > Process rules.
- A notice can be closed without the action only with a reason; the reason shows here.

**What happens next**
- The step moves on by itself when the next action is done in the app (for example a visit logged, a survey done, an indent approved, a bill sent).

**When it goes wrong**
- "Site not found": the site is not one your role covers.
- A step stays "waiting" though the work is done: the action was done outside the app. Do it in the app, or close the notice with the reason from your notifications.

### Handover

When the client hands each place over to us, and the target finish that follows. The engineer enters the client's promised date; only the supervisor's confirmation starts the clock.

**On the page**
- **Client delay** (figure): days the client handed over later than promised, over all places.
- **Our delay** (figure): days we finished later than the target, over all places.
- The table, one row per place: **Place**, **Promised by the client** (date and who promised, or "moved by ... because ..."), **Handover (supervisor)** ("received <date>", "not received yet" or "awaited"), **Stage days**, **Target finish** ("starts at the handover" until received), **Finished**, **Client delay**, **Our delay**. Amber rows: the promised handover date has passed. Red rows: the target finish has passed.
- **Promised date**: opens the fields **Promised handover**, **Who promised it** and **Client says handed over (does not count)**, with **Save** and **Cancel**. **Save** needs a date and a name of at least 2 characters. {perm: site.update}
- **Move the date**: shown before the handover once a date was promised. Opens **New date** and **Because (the client sees it)**, with **Move** and **Cancel**. **Move** needs a reason of at least 3 characters. {perm: closeout.site}
- **Received**: asks "Received on (YYYY-MM-DD)" and records the real handover on that date. Shown to the site's supervisor until the place is received.
- **Not yet**: records that the place is not received yet ("not received yet").

**Rules**
- Only the site's supervisor confirms the handover: a site supervisor, a member of the site with the role "supervisor", or a role that edits every site.
- What the client says does not count. Only **Received** starts the clock: target finish = the real handover date + the stage days.
- The handover date cannot be in the future.
- A moved date and its reason are shown to the client in the portal.

**What happens next**
- **Received** marks the place's work front ready. Planning is told to plan the material for that area (with the wastage).
- **Move the date** sends the client an in-app notice in the portal: "<place>: handover date moved to <date> (<reason>)". {perm: closeout.site}
- If the promised date passes without **Received**, the site engineer is told to follow it up with the client and planning is told to replan.
- If the target finish passes and the place is not finished, the site engineer is told to finish the area.

**When it goes wrong**
- "The site's supervisor confirms the handover": you are not the supervisor of this site. Ask the supervisor to press **Received**.
- "The handover date cannot be in the future": enter today or an earlier date.
- "Needs site.update": your role cannot enter promised dates.
- "Place not found": the place was removed from the structure. Reload the page.

### Location & visits

The site's pin on the map and who checked in at the site in the last 30 days. The pin is what check-ins are measured against.

**On the page**
- "Location missing: pin the site so check-ins can be checked." (warning): the site has no pin.
- The map: the site pin and its check-in circle. Tap the map to pick a new place. {perm: site.location}
- **Use my location**: picks where you stand now ("Finding…" while it looks). It is greyed out, with the reason, when the browser blocks location. {perm: site.location}
- **Radius in metres** (field): the check-in radius, 20 to 5000 m. Empty uses the company default. {perm: site.location}
- **Save the pin**: saves the picked place (or the current pin) and the radius. The app shows "Saved (the change is logged)." {perm: site.location}
- **Go to site (Google Maps)**: opens directions to the pin.
- **Who checked in (30 days)**: **Person**, **Date**, **In – out**, **Time on site** ("on site" while still there). Amber rows were checked in or out outside the circle.
- **Labour gangs**: the gangs checked in at the site, with headcount, times and hours. Amber rows were outside the circle.

**Rules**
- Pin the site standing at the gate, or pick the place on the map.
- **Save the pin** also saves the radius field. If the field is empty, the radius goes back to the company default. Type the radius again each time you move the pin. {perm: site.location}

**What happens next**
- Check-ins at the site are measured against the new pin and radius from now on. Earlier check-ins are not changed.

**When it goes wrong**
- "Pick the place on the map first": there is no pin yet and nothing picked. Tap the map or use **Use my location**. {perm: site.location}
- **Use my location** is greyed out: the browser or phone blocks location. Allow it, or pick the place on the map. {perm: site.location}
- An error about the radius: it must be between 20 and 5000 m. {perm: site.location}

### Plan & lots

The material planned for the whole project and the lots the site calls off against it. The tab is shown to roles that see planning or indents, or raise indents.

**On the page**
- **Material planned for the whole project**: one row per product with **Product**, **Planned**, **Called off**, **Waiting**, **Delivered**, **Issued** and **Balance**. A negative balance is red.
- **Fix the plan**: fixes the plan at the computed quantities (BOQ and survey quantities with consumption and wastage). Shown until the plan is fixed. The app shows "The plan is fixed at the computed quantities." {perm: planning.edit}
- **Call off now** (column): the quantity of each product to call off now. {perm: indent.create}
- **For the next (days)** (field): how many days the lot is for (1 to 60). 4 by default. {perm: indent.create}
- **Reason (needed past the plan)** (field): needed only when the lot goes past the plan. {perm: indent.create}
- **Call off the lot**: makes the lot. Active once at least one quantity is above zero. {perm: indent.create}
- **Lots** (table): **Lot**, **Products**, **For**, **Called by**, **Status** and **Indent** (a link to the indent made from the lot).
- **Approve** / **Reject** (on a lot "over the plan: waiting for planning"): approve makes the indent; reject asks "Why is it rejected?". {perm: planning.edit}

**Rules**
- A lot within the balance plus the tolerance (shown in the text above the table) becomes a submitted indent at once.
- A lot past the balance plus the tolerance needs a reason and waits for planning.
- A rejection needs a reason.

**What happens next**
- Within the plan: "<lot> called off: indent <indent>." The indent goes through the usual approval; once approved, store and purchase is told to place the PO.
- Past the plan: "<lot> is over the plan: waiting for planning." No notice is sent; planning sees it in **Lots** and approves or rejects it.

**When it goes wrong**
- "More than the plan's balance plus the tolerance for <products>: give the reason (planning approves it)": fill **Reason (needed past the plan)** and call off again. {perm: indent.create}
- "Say why it is rejected": a rejection needs a reason. {perm: planning.edit}
- "<lot> is approved" or "<lot> is rejected": someone already decided the lot. Reload. {perm: planning.edit}
- "Needs indent.create" or "Needs planning.edit": your role cannot do this step.

### Labour

The tab is shown with the permission to view labour (labour.view). It is where the site's workers are marked present each day, the worker list is kept and the month's muster roll is read. Staff also check in and out of the site here.

**On the page**
- **Quick mark**, **Workers (n)**, **Muster roll**: the three views of the tab.
- **Staff check-in**: checks you in at this site. A message "Checked in at <site code>." shows. No location is sent with it.
- **Check-out**: checks you out of the site you are checked in at. A message "Checked out." shows.

**Quick mark**
- **Day** (field): the day being marked; not a future day. The counts P, ½ and A show beside it.
- **✓ Mark all present**: sets every worker to present on screen (workers already marked at another site are skipped). Nothing is saved yet. {perm: labour.edit}
- **P**, **½**, **A** next to each worker: present, half day, absent. A worker marked elsewhere that day shows "Marked at <site>" and cannot be marked here. {perm: labour.edit}
- **Hours here** (field): for a subcontractor's worker, the hours spent on this site. {perm: labour.edit}
- **OT hrs** (field): overtime hours; not on an absent day. {perm: labour.edit}
- **📷 Group photo**: adds one photo to everyone marked that day. Mark first. {perm: labour.edit}
- **Save attendance (n)**: saves the n marks. Your phone's location is saved with them when the phone allows it. The message "Saved n mark(s)." shows. {perm: labour.edit}
- When no worker is on the site, "No workers posted to this site. Add them below." shows: add them in the **Workers** view.

**Workers**
- **Add worker**: opens **Add a worker** with **Name \***, **Phone**, **Trade**, **Type** (**Own labour** or **From a subcontractor**), **Subcontractor \*** (for a subcontractor's worker), **Daily wage (₹)**, **OT rate per hour (₹)** and **Aadhaar (last 4 digits)**. **Save** adds the worker to this site. {perm: labour.edit}
- Click a worker's row to edit them in the same form. {perm: labour.edit}
- Only the last 4 digits of the Aadhaar number are kept.

**Muster roll**
- **Month** (field) and **Excel** (download): the month's days, half days, OT hours, wage and amount due per worker, with the total wage due.

**Rules**
- A worker is marked at one site per day.
- The day's wage and OT rate are copied from the worker when marked; a later wage change does not change past days.

**When it goes wrong**
- "<Name> is already marked at <site> on <date>": the worker is on another site that day. Correct it there first.
- "<Name>: no overtime on an absent day": clear **OT hrs** or change the mark.
- "Attendance cannot be marked for a future day": pick today or earlier.
- "Mark the attendance first": the group photo needs at least one saved mark that day.
- "Pick the subcontractor this worker comes from" / "Own labour has no subcontractor": fix **Type** and **Subcontractor**.
- "give at least the last 4 digits of the Aadhaar number": type at least 4 digits, or leave it blank.
- "Check out of <site> first": you are still checked in somewhere else. Press **Check-out** first.
- "You are not checked in": there is no open check-in to close.

### Inspections

The tab is shown with the permission to view inspections (inspection.view). An inspection fills a checklist on site, often at a hold point of a stage, with photos and the client representative's signature.

**On the page**
- **New inspection**: opens the inspection form. {perm: inspection.edit}
- The list: **Code**, **Date**, **Checklist**, **Step / place** (with a "certified" badge when the hold point was certified), **Result** (**Pass**, **Fail**, **Pass with remarks**).
- **PDF**: downloads the inspection report.
- **Ask client to sign**: puts the inspection in the client's portal for an on-screen signature. It then shows "waiting for client", and later "client signed: <name>". {perm: inspection.edit}

**The inspection form**
- **Step (hold point)** (field): a hold-point step of the site, or "— none: a general inspection —". Picking a step picks its checklist.
- **Checklist \*** (field): the checklist to fill.
- Each checklist item: **Pass** / **Fail** / **n/a** buttons, a number, a text, or **Take photo**. A red \* marks a required item.
- **More photos**: extra photos.
- **Result** (field): "Pass (from the answers)", **Pass with remarks** or **Fail**. When an item failed, it is locked at **Fail**.
- **Date**, **Remarks**, **Client representative** (name) and **Signature (client representative)** (drawn on the screen).
- **Certify the hold point "<step>" if it passes** (tick box, on by default): certifies the step when the inspection passes. {perm: site.edit}
- **Save inspection**: saves it with a new INS code.

**Rules**
- A failed pass/fail item makes the result Fail; it cannot be saved as a pass.
- Every required item must be answered, and every required photo taken.
- A hold point is certified only when the step is done and has a passed inspection with its checklist. Certifying needs the site edit permission.
- When a hold-point step is picked, the app always tries to certify it on save (the tick box is on by default, and roles without the site edit permission do not see it). If the certification is refused, the whole inspection is not saved.

**What happens next**
- **Ask client to sign**: client users who see inspections in the portal are told "<code> is waiting for your sign-off".
- A certified hold point counts in the area's progress.

**When it goes wrong**
- "'<item>' is required" / "'<item>': add the photo" / "'<item>': answer pass, fail or n/a" / "'<item>': give a number": fill that item.
- "A checklist item failed: the result is fail": set **Result** to **Fail** or correct the answer.
- "Certifying a hold point needs site.edit": the inspection was not saved. Pick "— none: a general inspection —" in **Step (hold point)**, or ask a role with the site edit permission to do it.
- "The step must be done first": the hold-point step is not done yet, and the inspection was not saved. Finish the step first, or pick "— none: a general inspection —" until it is done.
- "This hold point needs a passed inspection with its checklist first": the step's own checklist must pass first.
- "The signature must be a PNG drawn on screen" / "The signature image is too large": draw the signature again.
- "<code> is already signed by the client": nothing more to ask.

### Work orders

The tab is shown with the permission to view subcontractor work orders (subcon.view). A work order (WO) gives part of the site's work to a subcontractor at agreed rates. The subcontractor's work is then measured against it.

**On the page**
- **New work order**: opens the work order form. {perm: subcon.edit}
- The list: **WO**, **Subcontractor**, **Value**, **Billable to date**, **Status** (draft, approved, active, completed, closed). An **over-measure** badge shows when a measurement goes beyond the WO quantity and waits for approval.
- Click a row to open the work order.

**The work order form**
- **Subcontractor \*** (with its PAN, GSTIN, bank and default TDS shown under it), **Material by** (**EESPL** or **Subcontractor**), **Retention %** (5 by default), **TDS % (blank: by PAN type)**, **Start**, **End**, **Terms (T&C template)** (**Built-in work order terms** or a saved template) and **Remark**.
- **Scope**: one line per item with **Description**, **Unit**, **Qty**, **Rate** and the computed **Amount**. **+ Line** adds a line; **×** removes one.
- The work order value and the retention show under the lines.
- **Save draft**: saves the work order as a draft.

**Inside a work order**
- The **Value** and **Billable to date** tiles show retention and TDS.
- Each line shows measured and verified quantities, and "over the WO qty" in red when it is over.
- **+ Measurement**: opens **Measure: <line>** with **Date**, **Qty done (<unit>) \***, **Remark** and **📷 Photos**. A warning shows when the quantity takes the line beyond the WO quantity. **Save** records it. {perm: subcon.edit}
- **Verify**: marks a recorded measurement as checked on site. {perm: subcon.edit}
- **Approve** / **Reject** on a measurement: decides a measurement that went beyond the WO quantity. {perm: subcon.approve}
- **PDF**: downloads the work order.
- **Edit**: opens the form again. Only on a draft. {perm: subcon.edit}
- **Approve**: approves a draft work order. {perm: subcon.approve}
- **Mark completed**: on an active work order. {perm: subcon.edit}
- **Close**: on a completed work order. {perm: subcon.edit}

**Rules**
- Only a draft work order can be changed.
- The first measurement on an approved work order makes it active.
- A measurement up to the WO quantity is "recorded" and waits to be verified. One beyond it is "pending approval" and needs the approval permission.
- A work order cannot be completed while an over-measurement is still waiting.
- When **TDS %** is blank, it is set from the subcontractor's PAN type.

**Hands off**
- Receives: the subcontractor from the vendor list (type subcontractor).
- Passes on: verified measurements to the site's subcontract cost (the **Budget** tab).

**When it goes wrong**
- "Pick a subcontractor (a vendor of type subcontractor)": pick a subcontractor from the list.
- "The end date is before the start": fix the dates.
- "<WO> is approved; only a draft is changed": the work order can no longer be edited.
- "<WO>: measurements need subcon.edit on an approved WO": measure only an approved or active work order.
- "Measured <qty> against <WO qty> on the WO: this measurement needs approval": shown in yellow after saving; the approver must approve or reject it.
- "Approve or reject the over-measurements first": decide the waiting measurements before **Mark completed**.
- "You cannot approve <WO>" / "Verifying needs subcon.edit" / "Over-measurement needs subcon.approve": you lack the permission on this site.

### MOM

The tab is shown with the permission to view inspections and minutes of meeting (inspection.view). It keeps the minutes of meetings (MOM) held on the site, with their action points. Open points also show on the site's **Overview**.

**On the page**
- **New minutes of meeting**: opens the form. {perm: inspection.edit}
- Each meeting: its subject, code, date, venue and who attended, the discussion and its points (open, done or dropped; red when overdue).
- **PDF**: downloads the minutes.
- **Edit**: opens the meeting in the form. {perm: inspection.edit}
- **Done**: closes an open point. {perm: inspection.edit}

**The form**
- **Subject \***, **Date**, **Venue**, **Client / others present (comma separated)**.
- **EESPL attendees**: tick the staff present.
- **Discussion**: the notes.
- **Action points**: **Point**, **Owner (EESPL)** or **or outside** (a name), **Due**. **+ Point** adds one. Empty points are left out.
- **Save**: saves the meeting with a MOM code.

**Rules**
- No one is notified when a point is given to them. Open points show on the site's **Overview** under **Open MOM points**.

**When it goes wrong**
- "An attendee or owner is not a user": a picked user was removed. Pick again.
- "A MOM cannot move to another site": a meeting stays on its site.

### Assets

The tab is shown with the permission to view tools, assets and equipment (asset.view). It lists the tools and equipment now at this site and the equipment use logged on it.

**On the page**
- **At this site**: **Code**, **Asset** (category, make, model, or the vendor it is hired from), **Where** (with days at the site, red when it stayed too long), **Status**, **Rate** (per day or per hour).
- **Move**: opens **Move <asset>** with **To \*** (**Return to a store** or **Issue to a site**), **Date**, **Condition** and **Photo**. **Move** saves it. {perm: asset.edit}
- **Log use**: for equipment (not tools). Opens **Use of <asset>** with **Date**, **By** (**Days** or **Hours**), the quantity, **Rate** (blank: the asset's rate), **Fuel (litres)**, **Fuel cost (₹)** and **Operator**; the cost is shown. **Save** logs it. {perm: asset.edit}
- **Equipment use (last 90 days)** with its total cost, and the list of uses.

**Rules**
- An asset at a site must be returned to a store before it can go to another site.
- Equipment use counts in the site's equipment cost on the **Budget** tab.

**When it goes wrong**
- "The asset register needs asset.edit (all)": moving needs the asset permission for every site. Ask the store or the office to move it.
- "<code> is at <site>; return it to a store first": return it, then issue it.
- "<code> is already at <site>" / "<code> is already in that store": pick another place.
- "<code> is lost" (or disposed): it cannot be moved.
- "<code> is not at <site>: issue it to the site first": use is logged only for an asset at the site.
- "<code> has no rate per day" (or hour): type the **Rate**.

### Budget

The tab is shown with the permission to view the site budget (budget.view). It shows the budget against the actual cost so far, head by head, and the labour cost per sqm.

**On the page**
- **Labour cost per sqm**: the labour paid per sqm billed, against the labour line of the rate working. "over the working" shows when it is higher.
- The table: **Head** (**Material**, **Labour**, **Subcontract**, **Equipment**, **Freight**, **Other**, each with where its cost comes from), **Budget**, **Actual so far**, **Variance**, **% used**, and the **Total**. A row turns red above 90 % used.
- A budget taken from the tender shows "from tender", or "tender (not saved)" when it is only a suggestion.
- **Set budget**: makes the budget column editable. **Save budget** saves it; **Cancel** drops the change. A blank amount removes the saved budget of that head. {perm: budget.edit}
- **Budget from the tender (₹ amount)**: saves the tender's material and labour cost as the budget. {perm: tender.margin}
- **Add a cost**: **Cost head**, **₹** and **What for**, then **Add**: a cost entered by hand. {perm: budget.edit}

**Rules**
- The budget from the tender's cost is hidden without the tender margin permission; a warning says so.
- Actual costs come from the app: material issues, muster roll wages, verified work order measurements, equipment use, freight, and costs entered by hand.

**When it goes wrong**
- "A budget cannot be negative": type 0 or more.
- "The site's tender has no costed BOQ lines": the tender has no cost to copy; set the budget by hand.

### Structure

The site's places as a tree: towers, wings, basements, floors, flats and rooms (toilet, kitchen,
balcony, terrace ...), and tanks, pits and other places. Every scope, task, survey area, daily
report line and 3D box hangs on these places.

**On the page**
- **Structure (<n> places)**: with the count of each kind.
- **Collapse all** and **Expand all**: fold or open the tree. **▸** / **▾** folds one branch. They are grey when there is nothing to fold or open.
- Each place shows its name, kind, area (sqm) and progress bar.
- **Add place**: opens **Add a place** at the top level. {perm: site.edit}
- **+ Child** (on a place): opens "Add under <place>". {perm: site.edit}
- **Kind**, **Name \***, **Area (sqm)** and **Level (B2 = -2, G = 0)**, then **Add**. {perm: site.edit}
- **Edit** (on a place): asks for the **Name**, then the **Area (sqm), blank for none**. {perm: site.edit}
- **Delete** (on a place): asks "Delete <place> and everything under it?" and deletes the place, the places under it, and their scopes and tasks. {perm: site.edit}
- **Add tower…**: opens **Add a tower**, which builds a whole tower in one go. {perm: site.edit}
- "No structure yet. "Add tower…" builds a whole tower in one go." when the site has no places.

**The Add a tower box** {perm: site.edit}
- **Tower name** (T1 by default) and **Under** (**The site**, or a wing, podium or other place). {perm: site.edit}
- **Basements (B1…)** (0 to 10), **Floors above G** (0 to 150) and **Ground floor (G)** (tick). {perm: site.edit}
- **Flats per floor** (0 to 50) and **Flats from** (**G and above** or **Floor 1 and above**). Basements get no flats. {perm: site.edit}
- **Terrace on top** (tick), **Toilets per flat**, **Kitchens per flat**, **Balconies per flat**. {perm: site.edit}
- **OH tanks (on terrace)**, **Lift pits** and **UG tanks**. {perm: site.edit}
- The green line counts what will be made: "<n> places will be made: ...". {perm: site.edit}
- **Create <n> places**: makes them all. **Cancel** closes the box. {perm: site.edit}

**Rules**
- A place where work has started cannot be deleted. {perm: site.edit}
- Put the area (sqm) on rooms and flats. A BOQ quantity is split over places by their areas when every picked place has one, else equally. {perm: site.edit}
- Planning, billing and the site engineer see the structure but cannot change it. Ask the director or the office admin.

**When it goes wrong**
- "<n> tasks under <place> have started; they stay": work is booked under that place. Leave it, or rename it. {perm: site.edit}
- "Node not found": the place was deleted meanwhile. Reload the page. {perm: site.edit}

### Scope

What we do where. Each priced BOQ line of the site's tender is put on the places it covers, with
the stage template (the steps) to follow. Then **Generate tasks** makes the steps in **Stages**.

**On the page**
- **What we do where**: "The priced lines of <tender code>", or "This site has no tender: add scopes per place.", and the number of places.
- Each BOQ line: item number, description, "BOQ <qty> <unit> · assigned <qty>", the difference, and a badge: **Fully assigned**, **Under-assigned**, **Over-assigned** or **No BOQ qty (QRO)**.
- **Assign to areas** (on a line): opens "Assign <item> to areas". Grey while the site has no places. {perm: site.edit}
- Under each line, its places: **Place**, **Stage template**, **Qty**, **Tasks** ("<n> (<n> started)") and **Progress**.
- **Qty** (on a place): asks for the new **Quantity**. {perm: site.edit}
- **Remove** (on a place): asks "Remove <place>?" and takes the place off the line. Grey once a task there has started. {perm: site.edit}
- **Other scopes**: scopes not tied to a BOQ line.
- **Generate tasks**: makes one task per step of the stage template for every scope that lacks it. It then says "<n> tasks added, <n> kept; <n> tasks in all, planned to finish <date>." {perm: site.edit}
- "No priced BOQ lines." when the tender has none, or the site has no tender.

**The Assign box** {perm: site.edit}
- **Stage template**: the steps to follow. The app picks one from the line's words and marks it **suggested**. {perm: site.edit}
- **Quantity to split**: empty takes the BOQ quantity. On a QRO line (no BOQ quantity) it is required. {perm: site.edit}
- **Add all** <kind>s **in** <place or "the whole site">, then **Add**: picks every place of that kind there (for example every toilet in T1). **Clear** un-picks all. {perm: site.edit}
- **Filter places**: narrows the list. Tick each place to pick it. {perm: site.edit}
- "<n> places picked · the quantity is split by their area" (or "equally (not every picked place has an area)"). {perm: site.edit}
- **Replace this line's current assignment (only possible while no task has started)**: shown when the line already has places. Ticked, the old places are dropped and the new ones get the whole quantity. Not ticked, the new places get only the part not yet assigned (or the quantity you typed). {perm: site.edit}
- **Assign to <n> places**: saves. {perm: site.edit}

**Rules**
- Generating tasks never changes or removes tasks that exist. Run it again after adding places or scopes. {perm: site.edit}
- The tasks are planned one after the other from the site's start date (or today), each step taking its typical days. {perm: site.edit}
- A scope's stage template cannot change once it has tasks. Remove it and assign it again before any task starts. {perm: site.edit}
- Aim for **Fully assigned** on every line. **Under-assigned** means part of the BOQ is on no place, so it will not be planned, done or billed by place.

**What happens next**
- The progress of places, floors and the site is worked out again.
- The steps appear in **Stages**, in the 3D view and in the site supervisor's day.

**When it goes wrong**
- "This line has no quantity (QRO); give the quantity to split": fill **Quantity to split**. {perm: site.edit}
- "The whole quantity is already assigned; replace it instead": tick **Replace this line's current assignment** or change the quantities with **Qty**. {perm: site.edit}
- "<n> tasks of this assignment have started; it cannot be replaced. Change the quantities instead.": use **Qty** on each place. {perm: site.edit}
- "Tasks exist for this scope; its template cannot change": remove the scope before work starts, then assign it again. {perm: site.edit}
- "That BOQ line is not from this site's tender" or "Unknown stage template": reload the page and try again. {perm: site.edit}
- A site without a tender has no BOQ lines, so this section has no **Assign to areas** button. There is no other way in the app to add a scope to it.

### Portal

The tab is shown with the permission to manage the client portal (portal.manage). It decides whether the client sees this site in the client portal, what they see, who of the client may log in, and which documents are shared.

**On the page**
- "Set the site's client before sharing it in the portal." shows when the site has no client.
- **Visible in the client portal** (tick box): shows or hides the whole site in the portal. Saved at once.
- The sections the client sees: **Overview & 3D**, **Daily reports**, **Photos**, **Inspections & MOM**, **Drawings & documents**, **Billing**, **Snags**. Each is saved at once.
- Costs, supplier rates, margins, budgets, salaries and wages are never shown in the portal.
- **Client users**: name, client roles, email and phone; status **active**, **invited**, **invite expired** or **disabled**, and the last login.
- **This site** (tick box per user): lets that user see this site, or not.
- **New link**: makes a new one-time invite link for a user who has not set a password yet.
- **Disable** / **Enable**: **Disable** asks "Disable <name>? Their session ends at once." and blocks the user; **Enable** lets them in again.
- **Invite a client contact**: **Name**, **Email**, **Phone**, the client roles to give (none: everything the portal allows), and **Create invite link**.
- The invite link box: "No email or SMS is sent: copy it and send it yourself." **Copy** copies the link.
- **Documents**: the site's documents, staff's and the client's own. Click a title to download it. **Share with client** (tick box) shares a staff document.
- Upload a document: **Title**, **Choose the file** (PDF, image, DWG or DXF), **Share with client**, then **Upload**.
- **Preview as client**: pick a client user to see exactly what they see (read only). **Close preview** ends it.

**What happens next**
- Sharing a document (on upload or with the tick box) tells the client users who see documents: "New document: <title>".
- Disabling a user ends their sessions and cancels their open invite links.

**Hands off**
- Passes on: the invite link, which you send to the client contact yourself.

**When it goes wrong**
- "That email belongs to a staff login": use another email for the client contact.
- "Every site must belong to that client" / "That site belongs to another client": the site's client is different; check the site's **Client**.
- "Unknown client role": reload and pick the roles again.

### Work fronts (/sites/:id/fronts)

Opened from **Work fronts** in the site's **More** list. Made for the phone: the site supervisor
ticks each place when it is open for our work (the other trades are out, the surface is
handed over). Material is ordered for ready places.

**On the page**
- "<n> of <n> ready": how many places are ticked.
- The places as an indented list. A ready place shows "✓ ready · <who> · <date and time>".
- **Ready**: marks the place ready. {perm: site.update, site.edit}
- **📷**: takes a photo and marks the place ready with it. {perm: site.update, site.edit}
- **photo** (on a ready place): shows the photo taken.
- **Not ready**: takes the tick and the photo off. {perm: site.update, site.edit}
- "No structure yet: add blocks and floors on the Structure tab." when the site has no places.

**Rules**
- Tick a place only when it is really open for our work. Planning orders material for it on the strength of your tick. {perm: site.update, site.edit}
- The site supervisor's tick (or the director's or office admin's) also records the handover of that place as received today, if it was not recorded yet. That starts the schedule's clock for the place. Anyone else's tick marks it ready for material only. {perm: site.update, site.edit}

**What happens next**
- Planning is told "<site>: <place> ready (<qty> <unit>). Material plan for this area (wastage <range>)." with the action **Plan material**. It opens the material plan for that place. If no indent is made within 24 hours, the director is told.
- The to-do closes when an indent is made from the material plan of that place.
- When the handover was recorded, a "Handover date passed" to-do of that place (sent to the site engineer and planning) closes too.

**Hands off**
- Receives: the place from the client or the main contractor.
- Passes on: the ready place to planning for the material.

**When it goes wrong**
- "You cannot post progress on this site": you are not in this site's team. Ask the site engineer. {perm: site.update, site.edit}
- "Node not found": the place was removed. Reload the page.

### New area (/sites/:id/new-area)

Opened from **+ New area** on the site's **Overview**. Used from the phone when work is needed on
a place that is not on the site's list (not in the structure or the quotation). Only roles that
post site progress or edit sites can open it.

**On the page**
- **Name**: what the place is called on site. Required.
- **Area type**: the kind of area (from the survey's list), or "—".
- **Approximate size (sqm)**: a rough size.
- **Where (under)**: "the site", or the place it is in (for example the floor).
- **Take the photo**: a photo of the place. Required.
- **Note**: anything planning should know.
- **Send to planning**: sends the request and goes to the **Work fronts** page.

**Rules**
- A photo is required. Without it the form says "Take a photo of the place".
- Work and material can be booked on the new place while it waits for a decision.

**What happens next**
- Planning and every role that approves new areas (director, office admin) are told "New area asked for at <site>: <name>", with a link to **New areas**.
- The site's **Overview** shows "<n> new area waiting" until it is decided.

**When it goes wrong**
- "You cannot ask for areas on this site": you are not in this site's team. Ask the site engineer.
- "That place is not on this site": the place in **Where (under)** was removed. Pick another.
- After **Send to planning**, the Work fronts page shows no message that it was sent. Check **New areas** on the Overview: the waiting count goes up by one.

### AutoCAD takeoff (/sites/:id/takeoff)

Opened from **AutoCAD takeoff** in the site's **More** list. The app reads the site's .dwg
drawings: room labels with sizes and waterproofing notes. You trace what has no label, map each
area to a place on the site, and accept it into the survey and the measurement book. Walls in
these drawings are loose lines, so no outline is drawn on its own.

**On the page**
- The drawing list: each revision of each drawing with its file name and read status (**ready**, **queued**, **reading**, **failed**).
- **Read the drawing** (on a revision not read yet): asks "Architect (their layer mapping is saved and reused)" and queues the drawing. A large drawing takes a minute or two. The page shows the progress. {perm: takeoff.edit}
- **Read again**: reads the revision again (for example after a failure). {perm: takeoff.edit}
- **Open**: opens a read drawing. The first read drawing opens by itself.
- "No AutoCAD drawings on this site yet: add the .dwg (or .dxf) in the site's Drawings." when there is nothing to read.
- The facts line: the units, layers, dimensions, the texts found ("All texts" and "On the mapped layers"), and warnings: "(unitless: set the unit before tracing)", "<n> areas on an unknown sheet", "<n> sheets guessed (no frame): confirm them".
- **Search the texts…**: finds texts on the drawing. Click one to move the view there.
- The drawing: drag to move, wheel to zoom, **Zoom in**, **Zoom out** and **Fit**. Click an area to select it.
- **Trace a new area** (or **Trace <area>** when an area is selected): starts tracing. Click the corners; each click snaps to the walls. Double-click inside a room to get an outline proposed from the walls. {perm: takeoff.edit}
- **Undo corner**, **Finish** (3 corners or more) and **Cancel** while tracing. A new area asks for its "Name of the area (for example TERRACE, LADIES TOILET)". {perm: takeoff.edit}
- **Use this outline** takes the proposed outline. **Correct its corners** lets you move them first. {perm: takeoff.edit}

**The side tabs**
- **Areas (<n>)**: the areas found. **Show**: **Areas we waterproof** or **Every labelled area**.
- Each area: name, floor, change since the last revision, sheet, waterproofing notes, sunk depth and side walls; **Label** (the size written on the drawing and its sqm); **Traced** (sqm, and "<n> % off the label: check" in red when they differ too much); the survey's figure for the same place when there is one.
- **sheet guessed**: **Confirm** keeps the guessed sheet, or pick **— another sheet —**. **sheet unknown**: **— pick the sheet —**. {perm: takeoff.edit}
- **Place** ("— place on the site —") and **Area type** ("— area type —"): map the area. {perm: takeoff.edit}
- **To the survey**: accepts the area into the site's survey "AutoCAD takeoff: <drawing title>" (a draft survey, method cad). Grey until the area has a place and a size. {perm: takeoff.edit}
- **Survey + measurement book**: also puts it in the measurement book. {perm: measurement.edit}
- **Leave out** (or **Leave out all <n>** for a label found several times): drops the area from the list. **Bring back** undoes it. {perm: takeoff.edit}
- **Same as a floor for other floors…**: copies the mapped areas of one floor (**Same as**) to the ticked floors, onto the places with the same names there. **Copy the mapped areas** does it. {perm: takeoff.edit}
- "<n> waterproofing notes not near any area": notes the app could not tie to an area. Check them on the drawing.
- **Layers**: which layers are walls, rooms, dimensions, text, and which to hide. **Show** ticks hide or show a layer on screen. **Architect** and **Save the mapping** save the roles for this architect's later drawings; the areas are found again. {perm: takeoff.edit}
- **Changes**: what a new revision added, resized and removed against the last read revision. The mapping is kept.
- **Quantities**: the accepted areas per floor, per system and per area type.

**Rules**
- An accepted area is locked here. Change it in the survey.
- Accepted areas feed the survey's material, the material plan (places without a BOQ item) and the 3D view.
- An estimate of this site warns about missed areas: every accepted area that is not in the estimate and not left out with a reason is listed there. Accept late areas knowing the estimate will flag them.
- Billing accepts areas into the measurement book. {perm: takeoff.edit}

**Hands off**
- Receives: the .dwg uploaded in **Drawings** by the site engineer or the office.
- Passes on: the accepted areas to the survey (site engineer, planning), to the measurement book (billing) and to the estimate (estimator).

**When it goes wrong**
- "Taking off areas is for billing, planning and the site engineer": your role can only look. {perm: takeoff.view}
- "Only AutoCAD drawings (.dwg or .dxf) can be read for areas": the revision is a PDF or an image. {perm: takeoff.edit}
- "It is being read now": wait for the read to finish. {perm: takeoff.edit}
- "The drawing's geometry is missing on the server: read the drawing again": press **Read again**. {perm: takeoff.edit}
- "Set the drawing's unit first: it says unitless": the drawing has no unit, and this page has no control to set one. Ask the architect for the drawing saved with its units and upload it as a new revision. {perm: takeoff.edit}
- "An outline needs at least three corners": click at least three corners. {perm: takeoff.edit}
- "No wall found in every direction from that point: click the corners instead": the walls have gaps. Click the corners. {perm: takeoff.edit}
- "<area> is accepted into the survey; change it there" or "<area> is accepted; its trace is kept as it was": change it in the survey. {perm: takeoff.edit}
- "<area>: map it to a place on the site first" or "<area>: no size yet; trace it first": pick the **Place**, or trace the area. {perm: takeoff.edit}
- "<area> is not mapped under <floor>" or "A target floor is not on this site": map the source floor's areas first, then copy. {perm: takeoff.edit}
- "That place is not on this site": reload the page and pick the place again. {perm: takeoff.edit}
- "Billing accepts areas into the measurement book": use **To the survey**. {perm: takeoff.edit}

### Building model (/sites/:id/building)

Opened from **Build from AutoCAD** or **Edit the building model** in **3D building**. It turns
the AutoCAD drawing into the real building for the X-ray view: each typical plan once, with its
outline, the floors it is for, its columns, stairs, lifts and beams. The rooms come from the areas
traced and mapped in the AutoCAD takeoff, raised on their floors with their sunk depth. Everyone
who sees the site can open it; only roles with the building right can change it.

**On the page**
- **See it in 3D**: opens the site's **3D building** section.
- **Save** (or **Save (version <n>)**): saves the model as a new version. Grey until something changed. {perm: building.edit}
- **Start from a drawing** (before there is a model): the site's AutoCAD drawings. A drawing not read yet shows its state, with **Read the drawing** or **Read the drawing again** for roles that may read drawings, else "Ask billing or planning to read it."
- **Build from this drawing**: makes the first model from a read drawing: its plans become floor types, the floors come from the plan titles, the levels from the section. {perm: building.edit}
- **Choose the IFC file** (under "The client's BIM file (IFC)"): keeps the client's BIM model with the site. It is shown as it is in **3D building**. {perm: building.edit}
- "A newer revision is read: <drawing> rev <n>." with **Move the model onto it**: moves the model to the new revision. What still matches is kept, and **What the new drawing revision changed** lists the plans, columns and rooms kept, new, resized and gone. {perm: building.edit}

**Floor types (left)**
- Each floor type with its floors, outline area, column count (✓ when confirmed) and cores. Click one to work on it.
- **+ Add a floor type from a plan…**: adds a plan not used yet. {perm: building.edit}
- **Walls (off for a roof or a terrace)** (tick) and **Remove this floor type** (its floors fall back to the reference plan). {perm: building.edit}
- **Floors this plan is for**: for example "3-12, or 2,3,5"; G or 0 is the ground floor. {perm: building.edit}
- **1. Outline**: **Propose from the walls**, or **Trace** it by clicking the corners. {perm: building.edit}
- **2. Columns**: **Find columns**, then **Add / remove** by clicking the plan, then **Confirm**. The column size range is set by **Smallest column side (m)** and **Largest column side (m)**: save, then find again. {perm: building.edit}
- **3. Cores**: **Trace a stair** or **Trace a lift**. A stair can take its **Risers** (empty: worked out). **Remove** drops a core. {perm: building.edit}
- **4. Beams**: **Pick two columns** for each beam. **Clear** removes them all. {perm: building.edit}
- While tracing: **Finish** (3 corners or more) and **Undo**. Clicks snap to the walls. {perm: building.edit}

**Heights and floors**
- **Floor to floor (m)**, **Slab (m)**, **Plinth (m)**, **Stair riser (m)**, **Column from (m)** and **Column up to (m)**. {perm: building.edit}
- **Beams along the column lines**, **Show the client's BIM file (IFC)**, **BIM file limit for a laptop (MB)** and **Glow** (**Auto (off on weak devices)**, **Always on**, **Off**). {perm: building.edit}
- **Floors**: each floor of the site's structure with its **Type**, **Level (m)** and **Height (m)**. A floor without a type uses the reference plan. {perm: building.edit}
- "Section levels no floor uses: ...": levels on the drawing's section that no floor of the site has (basements, a tank, a roof room). Add the floor in **Structure**, or leave them.
- The plan (right): the drawing of the chosen floor type, with **Zoom in**, **Zoom out** and **Fit**.

**Rules**
- Each save is a new version. The X-ray view always shows the latest. {perm: building.edit}
- The rooms are not drawn here. Trace and accept them in the AutoCAD takeoff, mapped to the site's places.
- Limits on save: floor to floor 2 to 8 m, slab 0.05 to 0.6 m, plinth -5 to 3 m, column 0.1 to 1 m (from) and 0.2 to 2 m (up to), riser 0.1 to 0.25 m, BIM limit 10 to 600 MB, each floor 2 to 10 m high at a level between -30 and +400 m. {perm: building.edit}

**When it goes wrong**
- "Building the 3D model needs building.edit on this site": your role can only look. {perm: site.view}
- "The drawing is not read yet": read it first (in the AutoCAD takeoff, or with **Read the drawing**). {perm: building.edit}
- "Start the model from a drawing first": press **Build from this drawing** first. {perm: building.edit}
- "No closed outline in the walls of this plan: trace it.": use **Trace**. {perm: building.edit}
- "At least 3 corners", or "The outline of <floor type> needs at least 3 corners": click more corners. {perm: building.edit}
- "<setting> must be between <low> and <high>", "Floor <name>: height between 2 and 10 m" or "Floor <name>: a level between -30 and +400 m": correct the figure and save again. {perm: building.edit}
- "Upload the IFC file (.ifc)" or "This is not an IFC file (it does not start with ISO-10303-21)": pick the .ifc export. {perm: building.edit}
- "The IFC file is over 600 MB: ask the client for a lighter export (one building, no furniture).": ask the client for a lighter export. {perm: building.edit}
- "The drawing could not be shown: <reason>" with **Read the drawing again**: read it again.

### Material plan (/sites/:id/material-plan)

Opened from the site's **Material plan** link, or from planning's "Front ready, plan material"
to-do. It shows how much of each product the site needs, from the survey quantities and each
system's consumption plus wastage, and lets you raise an indent from it.

**On the page**
- **By stage** (tab): the planned products per stage (BOQ item). Places taken off AutoCAD without a BOQ item are grouped as "AutoCAD takeoff (places without a BOQ item)".
- **By month** (tab): the same products per month of the planned start of their tasks. Unplanned ones are under "Not scheduled".
- The table has one row per product: **Product**, **Planned**, **On ready fronts**, **Indented**, **Delivered**, **Issued**, **Balance**, **Indent now**.
- **On ready fronts**: the part of the plan on work fronts marked ready.
- **Indented**: all indents of the site for the product, except cancelled and rejected ones.
- **Delivered**: received into the site's store (GRNs and transfers in).
- **Issued**: issued to the work, minus returns.
- **Balance**: planned minus issued.
- **Indent now** (field per product): filled in with what is on ready fronts and not yet indented. Change it as needed.
- **Create indent**: makes one indent with every product that has a quantity in **Indent now**, and opens it. It stays grey until at least one quantity is above zero. {perm: indent.create}
- When opened for one work front, a green note says "For the ready work front <place>" with the wastage used, and **Whole site** goes back to the plan of the whole site.
- "No area with a system on this site yet." means no area of the site has a system, so nothing can be planned.

**Rules**
- Only areas with a system are planned. A system component whose consumption is not filled in is left out until it is filled.
- For a work front, the wastage of its application (raft, footing ...) from Settings > Process rules is used at its upper figure. Otherwise the system's own wastage is used.
- Planning sees every site. Other roles see only the sites their indent access allows.
- The indent is made in **Submitted** status, with the remark "From the material plan", for the site's store. {perm: indent.create}

**What happens next**
- The indent waits for approval by a role that approves indents (director, office admin or store and purchase). {perm: indent.create}
- When the plan was opened for one work front, the indent closes planning's "Front ready, plan material" to-do for that front. Raised from the whole-site plan, it does not close those to-dos. {perm: indent.create}
- Once the indent is approved, store and purchase is told to place the PO.

**When it goes wrong**
- "Site not found": the site is not one you may see. Ask planning.
- "You cannot raise an indent for <site code>": the site is not one of yours. Ask the site's engineer or planning. {perm: indent.create}
- "<site code> is closed": a closed site takes no indents. {perm: indent.create}
- "Nothing to indent": every quantity was zero or empty. Fill in **Indent now**. {perm: indent.create}

### RFI zones (/sites/:id/zones)

Which zones of the site the client handed to us, and which went to another applicator, with the client's RFI signature. Open it from the site's **More** menu (**RFI zones**). It is shown to roles with site close-out or billing close-out work.

**On the page**
- One block per tower or wing, with a tile per flat and its areas. Green: ours, with the zone name. Grey: another applicator, by name. Plain: "not marked".
- The key under the blocks: ours, another applicator, not marked.
- **Zones and RFI signatures** (table): **Zone**, **Place**, **Handed to** ("us" or the applicator) and **RFI signed** (name and date, "(in the portal)" or "(recorded by staff)", or "not yet").
- **Site** (link at the top): back to the site.

**Rules**
- The page only shows the zones. It has no button to add a zone, record a signature or remove a zone.
- A flat takes the zone of the nearest place above it that has one.
- Measurements and bills outside our zones need a reason.
- The client signs the RFI in the portal. A signed zone is locked.

**What happens next**
- The billing checklist uses the zones to tell which flats are ours.

**When it goes wrong**
- Every flat says "not marked": no zones are set for the site. They cannot be added on this page; report it to the office admin.
- No blocks at all: the site has no towers or wings. Add them in the site's **Structure** tab.
- "Missing permission: closeout.site": your role cannot see the zones.
