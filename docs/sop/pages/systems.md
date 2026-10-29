---
page: /systems
title: Systems (rate calculator)
routes: /systems, /systems/:id
mark: New system
---
**Systems** are the rate build-up recipes, one per waterproofing system: which products, how much of each per unit, the wastage, the surface preparation, the labour and the default margin. The rate is worked out from today's product prices. Roles without cost see only the products a system uses.

**On the page: Systems (list)**
- **Search code or name** (box): type and press Enter to search.
- **⤓ Export Excel**: downloads the list with the same search.
- **New system**: opens the **New system** form. {perm: library.edit}
- The table: **Code**, **Name** (click it to open the system), **Products**, **Rate** (per unit). "not priced" means a product has no current price or a consumption is still to confirm; point at it to see which. Inactive systems are greyed.
- Below the table, the page buttons move through the list 25 at a time.

**The New system form** {perm: library.edit}
- **Code** (required, unique), **Unit** (sqm by default), **Name** (required), **Description**. {perm: library.edit}
- **Surface prep (₹ / unit)**, **Default margin %** (30 by default), **Labour rate (₹)**, **Labour per** (sqm or sqft). {perm: library.edit}
- **Create** makes the system and opens it, to add products and consumption. **Cancel** closes the form. {perm: library.edit}

**On the page: one system (/systems/:id)**
- The header: the name, the description, **To confirm** when figures are still missing, and the **Selling rate** per unit at the default margin.
- A yellow note under the header says why there is no rate, e.g. "No current price for: <products>" or "Consumption to confirm for: <products>".
- **Products used** (list): the products, with their brand. This is all that roles without cost see.
- **Build-up** (table): **Product**, **Consumption / unit**, **Coats**, **Wastage %**, **Site average** (the median actual consumption over completed areas on sites, with the number of areas when you point at it). An empty consumption shows "to confirm". {perm: tender.margin}
- **Surface prep (₹ / unit)**, **Default margin %**, **Labour rate (₹)**, **Labour per**: the system's settings. Greyed for roles that cannot edit. {perm: tender.margin}
- In the build-up, each row's **Product** list, **Consumption / unit**, **Coats** and **Wastage %** can be changed. Leave the consumption or the coats empty when not known: it is kept as "to confirm", never guessed. {perm: library.edit}
- **×** (on a row): removes the product from the build-up. **+ Add product** adds an empty row; choose the product in "Choose a product…". A row left without a product is dropped on save. {perm: library.edit}
- **Save system**: saves the build-up and the settings, shows "System saved." and works the rate out again. It is greyed until something changed. {perm: library.edit}
- **Rate calculator** (card): type a **Margin %** to see the rate at that margin: per product the **Qty incl. wastage**, the **Landed rate** (purchase + freight) and the **Cost**, then **Materials**, **Surface preparation**, **Labour**, **Cost**, the margin and the **Rate / unit**. It never saves anything. {perm: tender.margin}
- "Save the system to include unsaved changes in the calculation." shows while changes are not saved: the calculator uses the saved system. {perm: tender.margin}

**Rules**
- Only roles that both edit the library and see cost may create or change a system.
- A system has no rate while any product has no current price or any consumption is to confirm.
- The site average is shown beside the system's figure; it never changes the system by itself.
- Labour per sqft is turned into a rate per sqm (1 sqm = 10.7639 sqft) when the system is in sqm.

**What happens next**
- A saved change is used at once by every rate worked out after it (rate workings, margin checks, consumption variance on sites).

**Hands off**
- Receives: products and prices from **Products**; the site average from the material issued on sites.
- Passes on: the rates to the estimator's rate workings and quotations.

**When it goes wrong**
- "A system with code <code> already exists": pick another code.
- "Unknown unit: <unit>": choose a unit from the list.
- "Unknown product ids: [...]": a product was deleted meanwhile. Choose another product.
- "No current price for: <products>": add a price to those products in **Products**.
- "Consumption to confirm for: <products>": fill the consumption of those rows and save.
- "System not found": the system was deleted. Go back to the list.
