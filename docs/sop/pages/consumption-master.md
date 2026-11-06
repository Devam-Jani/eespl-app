---
page: /consumption-master
title: Consumption master
routes: /consumption-master, /consumption-master/:id
mark: Add work item
---
One place for every work item (system) and how much of each product it takes, per brand. The company BOM import fills it; here it is kept up. Rates built from it (a quotation, a tender's rate working, an estimate) read today's figures; an issued estimate and a sent quotation keep the figures they used.

**On the page: Consumption master (list)**
- **Brand options with no brand's name**: options the company BOM named "Standard", "Standard (2)" or "SC", each with its work item; **Rename brand** gives it the maker's name. Nothing is renamed by itself.
- **Search name, brand, product or area** (box) and **Area** (list) narrow the list.
- The table: **Work item** (a warning "outside TDS" when a figure is outside its product's data sheet), **Unit** (sqm, sq ft, rmt, rft, nos), **Areas** (those set here, else read from the name), **Type**, **Brand options**.
- **Add work item**: **Name**, **Unit**, **System type** and **Areas it fits**, then **Add**; the new work item opens. {perm: consumption.edit}

**A work item**
- **Areas and type**: the areas it fits and its system type, used to rank the options for a BOQ line. Tick an area or choose a type to set it; **Why (kept with the change)** is saved with it. {perm: consumption.edit}
- One card per brand option: each product's **Step**, **Product**, consumption **Per sqm** (or rmt) and **Per sq ft / rft**, **Wastage** (or "included": a sheet's or mesh's overlap is in the figure), **Coats**, and the **TDS range** of its data sheet (per coat × coats when the sheet gives it per coat); "⚠" when the figure is outside it, and the warning above the table.
- **Price** with **update rate**: the product's current price and where it came from; **update rate** adds a new price row (per the product's unit, or per pack, converted once). Under the table: material, labour and cost per unit and the selling rate at the default margin on the selling price, at today's prices. {perm: tender.margin, consumption.cost}
- **✎** on a product: consumption, **Wastage %**, **Wastage included**, **Coats** and **Why it changes**, which is required and kept with the change. **×** removes the product (asks why). **Add a product** adds one to the option. {perm: consumption.edit}
- **Copy to another brand**: the other brand's name and, for each product, the product to swap in (or kept); **Copy** makes the new brand option. {perm: consumption.edit}
- **Formulation (mix design)** and **Thickness mm**, then **Work it out**: the mix's cement, sand and admixture become the option's products with their consumption worked from the thickness. {perm: consumption.edit}
- **Add a brand option**: a new, empty brand option. {perm: consumption.edit}
- **Rename brand** (on a brand option): the maker's name and why; "Standard" or "SC" is refused as a name, and so is a brand the work item already has. {perm: consumption.edit}
- **Changes**: every change with when, who, what, the old and new value and why.
