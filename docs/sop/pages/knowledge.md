---
page: /knowledge
title: BOQ knowledge
routes: /knowledge, /knowledge/templates/:id, /knowledge/match/tender/:id
---
**BOQ knowledge** is what our old BOQs say: the client lines, the build-ups in their workings, the place and the date, grouped into specification templates that a new BOQ starts from. The files are read from copies of the originals; the originals are never changed. Cost and margin are shown only to the estimator, planning and management.

**On the page: BOQ knowledge (home)**
- **Reading report**: **Files read**, **Failed** (red when any), **Scanned, not read**, **Not a BOQ**, **Lines found**, **With a working**, **With a place**, **With a date**, **Templates**. The line under it gives the files by type, the QRO, NQ and "to check" lines, and the folder read.
- "n files failed, with the reason" (fold-out): each failed file and why. "n scanned PDFs, not read (no OCR yet)" (fold-out): the scanned files that cannot be read yet.
- **Review queue** (fold-out): templates not reviewed yet, the most used first, with "n near-duplicate(s)" when similar templates exist. Click a template to open it.
- **Products to review (n)** (fold-out): products the old workings used that the product master does not have: **Name in the old workings**, **Old price**, **From**, **Suggested match**.
- **Merge into <product>** (on a product to review, when a match is suggested): the name becomes another name of that product, so the workings find it next time. {perm: knowledge.edit}
- **Accept**: adds it to **Products** with a code starting "BOQ-", unit kg, and the old price as its first price, marked to check. Check the unit and price in **Products**. {perm: knowledge.edit}
- **Reject**: drops it from the list. {perm: knowledge.edit}
- **Search** (box): searches the templates as you type. **Area** (list): "All areas" or one area. **show single-line templates** (tick box): also lists templates built from one line only.
- The template table: **Template** (click to open; **to check** and **reviewed** badges, the start of the description), **BOQs**, **Lines**, **Median rate** (per unit), **Latest**.

**On the page: one template (/knowledge/templates/:id)**
- The header: the name, **hidden** or **to check** badges, how many BOQs and lines, the unit, and "margin n here" when known.
- **Edit**: opens the edit card: **Name**, **Standard description (the client text)**, **Method statement (one step a line)**, then **Save**. Saving marks the template reviewed. {perm: knowledge.edit}
- **Hide** / **Show**: hides the template from the list, or shows it again. It also marks it reviewed. {perm: knowledge.edit}
- **Merge into** (box with "template no.", then **Merge into**): moves all this template's lines into the template with that number. This template is then empty. {perm: knowledge.edit}
- **Standard description** and **Method statement**: the text and the steps, with where the steps came from.
- **Products and consumption (from n working(s))**: per product the consumption per surface (median and count), the median price and freight, and the BOQs. "not in the product master" marks a product we do not have. Then the labour per sq ft and surface preparation per sqm. {perm: knowledge.cost}
- **Margin carried (on the selling price)**: the range and median margin over the workings, and the median per client. {perm: knowledge.cost}
- **Past rates by location**: type a city in **Location** (Ahmedabad by default). The small table gives min, median, latest and number of lines in that city, in its region and over all. Rates older than the set number of months are marked **old**.
- The rate table: **Date**, **Place**, **Rate**, **From** (file, sheet, row). Rows to check are yellow.
- The **Cost** and **Margin** columns of the rate table. {perm: knowledge.cost}
- **Fix** (on a rate row): opens a fix line: **Field** (rate, city, on_date, surface, coats, min_kg_sqm, template_id, hidden), **Value**, **Reason** (at least 5 characters), then **Save the fix**. The old value, the new one and the reason are kept and shown under "n change(s) by hand". Setting template_id moves the line to another template. {perm: knowledge.edit}
- "n near-duplicate(s): the same area and system, worded differently" (fold-out): similar templates. Click one to open it. {perm: knowledge.view}
- **Merge this into it** (on a near-duplicate): moves this template's lines into that template and opens it. {perm: knowledge.edit}
- "Costs and margins are for the estimator, planning and the director." shows to roles without cost.

**On the page: client BOQ matched to the library (/knowledge/match/tender/:id)**
- Opened from a tender. Each line of the client's own BOQ with the template that fits best, how sure the match is, and the median past rate near the tender's city.
- The table: **Client line**, **Template** (click to open it; "no template" when none fits), **Confidence** (green from 70 %, grey from 50 %, yellow below), **Median near**. Rows below 50 % are yellow; accepted rows are green.
- **Accept**: keeps the suggested template for that line and marks it **accepted**.
- **Change**: asks "Template number (blank: none)". A number sets that template; blank records that no template fits.

**Rules**
- A changed value on a line (rate, city, date, surface, coats...) always needs a reason of at least 5 characters, and the line is no longer "to check".
- Margins can only be fixed by roles that see cost.
- A product to review is decided once: accepted, merged or rejected.

**What happens next**
- The templates are what the client BOQ match of a tender suggests, so a cleaner library gives better matches.
- An accepted product appears in **Products**, with its old price to check.
- When a tender is marked won, its rate workings are added to the library as new evidence.

**Hands off**
- Receives: past BOQ files and their workings; a client BOQ imported on a tender.
- Passes on: templates and past rates to the estimator for tenders; new products to the product master.

**When it goes wrong**
- "Template not found": the template number does not exist. Check the number.
- "Pick another template to merge into": you typed this template's own number.
- "Give the reason for the change": write a reason of at least 5 characters.
- "Margins are not for your role": your role cannot change a margin.
- "Already decided": someone decided this product already. Reload.
- "Pick the product it is": the merge needs a product.
- "No access to tenders": your role cannot see tenders, so it cannot open a tender's match.
- "Line not found" or "Not found": the line was removed. Reload.
- **Merge this into it** that fails shows the reason under the near-duplicates (for example "Template not found": reload the page).
