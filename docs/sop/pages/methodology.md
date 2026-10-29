---
page: /methodology
title: Methodology builder
routes: /methodology, /methodology/systems/:id, /methodology/standards/:id, /methodology/m/:id, /sites/:id/methodology
---
The **Methodology builder** holds our method library (the systems and steps from our offers), the client standards read from their SOPs, and the methodology of each BOQ, checked item by item against the client's standard. The site's copy shows the stages, hold points and tests the site must follow.

**On the page: Methodology builder (home)**
- **Build the methodology of tender #n** (card): shown when the page is opened from a tender. Pick the **Client standard** ("The tender's client standard" by default) and press **Build**. The app builds the methodology from the tender's BOQ and opens it. {perm: methodology.edit}
- **Methodologies** (table): **Code** (click to open), **Title**, **Items**, **Version**, **Compliance** (n complies · n gaps · n to confirm). Opened from a tender, only that tender's methodologies are listed.
- **Client standards** (table): **Standard** (click to open), **Rules**, **To check**, **Approved makes**, **Guarantee**.
- **Method library** (table): **Code** (click to open), **System**, **Type**, **Suits**, **Steps**, **To confirm**, **From** (the offer and item it came from), **v** (version).

**On the page: one library system (/methodology/systems/:id)**
- The header: brand, type, the elements it suits and the offers it came from.
- **Where it suits and why**: the conditions, **Why we pick it**, competing options, **Guarantee**, **BOQ text**, **Measurement**. "to confirm" in red when a figure is missing.
- **To confirm (n)**: what is still missing. "n copy-paste errors fixed while seeding" (fold-out) lists the corrections made when the library was loaded.
- **Stages and steps**: each stage with its steps, product, consumption, waiting time and tools. "client's scope" marks steps the client does.
- **Hold points and tests**, **Checklist** (each question with Yes / No).
- **Products and their data sheets**: the data sheet values per product, what is missing, and the data sheet file (click to download).
- "Rates:" links to the matching templates of **BOQ knowledge**.
- **Change (with the reason; a new version)** (card): pick the **Field** (**Guarantee (years)**, **Why we pick it**, **BOQ text**, **Measurement rule**), type the **Value** and the **Reason** (at least 3 characters), then **Save**. The system gets a new version; giving the guarantee or the reason takes it off the "to confirm" list. The versions are listed below. {perm: methodology.edit}

**On the page: one client standard (/methodology/standards/:id)**
- The header: the client, the source, the approved makes and the guarantee.
- The counts: **SOPs read**, **Rules**, **To check**, **Contradictions**, **Formats**.
- **Rules (one per element and condition)**: **Element**, **Condition**, **Required system**, **SOP** (number, revision and page), **Status** (**ok** or **to check** with the note). Click a rule to open its minimum specs, tests and hold points, makes, checklist and guarantee; click again to close it.
- The SOP reference is a link that downloads the client's SOP file. {perm: methodology.compliance}
- **Contradictions (for the pre-bid queries)**: the topics where the client's SOPs give different values, with the pages.
- **Documents read**: each SOP with its revision, date, format, pages and rules found.

**On the page: one methodology (/methodology/m/:id)**
- The header: the code, revision, version, a link to the tender, and the counts **n complies**, **n gaps**, **n to confirm**.
- **Export for the client (Word + PDF)**: makes the client's copy. The files appear under **Files**; click a file name to download it.
- If a coverage is outside the library's range, a yellow box shows "Coverage outside the library: ..." and the client's copy is not made. **Send anyway — I have seen it** makes it as it is; **Not now** closes the box so you can correct the figure first.
- **Export internal**: makes the internal copy (with the compliance), listed under **Files**. {perm: methodology.compliance}
- **Check again**: runs the compliance check again against the client's standard. {perm: methodology.compliance}
- The coverage and T&C checks of the methodology, shown only when something is wrong. {perm: estimate.view}
- **Files**: the files made, with who they are for (client or internal). Internal files are listed only for roles that may see them.
- Each **Item**: its element and quantity; **Conditions** with where each came from, and in red the ones to confirm; "n place(s) from the drawings"; **Client rule**; **Our system (Option 1)** with why; **OR Option 2**.
- **Compliance** (table, per item): **Requirement**, **Client**, **Ours**, **Status** (**Complies**, **Gap**, **To confirm**), **Gap / choice**.
- On a make that is not on the client's list, the choice buttons: use a make on the client's approved list, or keep our make and ask the client to approve it before the bid (TPT). The chosen one is highlighted; the check runs again. {perm: methodology.edit}
- **Enter the real perimeter** (on a tank item): asks "The tank's real perimeter (m)" and "Where it comes from", and works the item out again. {perm: methodology.edit}
- The steps of each item, with **Edit** on each step: asks "The step" (the new text) and "Why it changes". Cancel or an empty reason changes nothing. Each edit makes a new version, listed under "Edits:". {perm: methodology.edit}
- **Pre-bid queries (n)**: the questions to ask the client before the bid (**Query**, **Reference**, **Kind**). **Status** (list): **open**, **sent** or **answered**. {perm: methodology.compliance}

**On the page: methodology on site (/sites/:id/methodology)**
- Opened from the site. The stages from the won BOQ's methodology, per item: **Stage**, **Weight**, **Inspection** ("checklist form (Yes / No)" when the stage has one), **Hold point** ("blocks the next stage until certified").
- **Pond tests**: **Test**, **Hours asked**, **Hours done**, **Photos**, **Result**.
- **Material tests on deliveries**: per product the tests (property, required value and standard, where it was asked), "also asked: ... the stricter is used" when two documents ask different values, **How often**, **Status**. "test certificate" when no test is set.
- This page only shows the plan; the inspections and tests are entered on the site's own screens.

**Rules**
- Every change to a library system, a step or a perimeter needs a reason and makes a new version; the version before is kept.
- A hold point must be inspected and certified before the next stage can start on site.
- A pond test passes only after its hours have run from start to end and the photos (start and end levels) are added.
- The make choice needs both the compliance and the edit permission. {perm: methodology.compliance}

**What happens next**
- The client's copy goes with the tender or quotation. The internal copy, the compliance and the pre-bid queries stay inside.
- When the tender is won, the site gets the stages, hold points and tests shown on the site's methodology page.

**Hands off**
- Receives: the tender's BOQ and the client's standard from the estimator; the method library.
- Passes on: the methodology to the estimator and sales for the bid; the stages and tests to planning and the site team.

**When it goes wrong**
- "Build it for a tender or a quotation": the builder needs a tender. Open it from the tender.
- "Coverage outside the library: ...": check the figure, or use **Send anyway — I have seen it**.
- "Missing permission: methodology.compliance": your role cannot make the internal copy.
- "Say why the system changes" / "Say why the step changes": give the reason.
- "Nothing changed": the new value is the same as the old one.
- "No such stage" / "No such step": the methodology changed meanwhile. Reload.
- "The tank's plan area and depth are not known": the item has no plan area or depth to work from.
- "System not found", "Standard not found", "Methodology not found", "Item not found", "Query not found": reload; the record was removed.
- "No data sheet" / "The data sheet file is not there": the product has no data sheet file. Ask for it to be uploaded.
- "The SOP file is not in data/methodology": the client's SOP file is missing on the server.
