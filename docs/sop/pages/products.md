---
page: /products
title: Products
routes: /products, /prices/:id
mark: Add product
---
**Products** is the master list of the materials we buy and use: code, name, brand, category, unit, pack, GST and HSN code. Roles that see cost also see each product's current purchase rate and freight, and keep the price history. Prices are never edited: a new price is a new row with its own date.

**On the page: Products (list)**
- **Search code, name or brand** (box): type and press Enter to search.
- **Category** (list): "All categories" or one material category.
- **⤓ Export Excel**: downloads the list with the same search and category. Cost columns are left out for roles that do not see cost.
- **Add product**: opens the **Add product** form. {perm: library.edit}
- **Import BOM**: opens **Import the company BOM**. {perm: bom.import}
- The table: **Code**, **Name**, **Brand**, **Category**, **Unit**, **Pack**, **GST %**. Inactive products are greyed.
- **Purchase rate** and **Freight** columns: the current price ("no price" when none). Click the rate to open the product's price page. {perm: tender.margin}
- **Prices** (on a row): opens the **Prices: <product>** window. {perm: tender.margin}
- **Edit** (on a row): opens the product in the form. {perm: library.edit}
- Below the table, the page buttons move through the list 25 at a time.

**The product form (Add product / Edit <name>)** {perm: library.edit}
- **Code** and **Name**: required. The code must be unique. {perm: library.edit}
- **Brand**, **Category** (active material categories), **Unit**. {perm: library.edit}
- **Pack size** and **Pack (bag, can, drum)**: leave the pack empty for no rounding to packs. {perm: library.edit}
- **GST %** (required, 18 by default) and **HSN / SAC code** (4 to 8 digits). {perm: library.edit}
- **Reorder level (unit)**: when the stock falls below it, an alert is raised for store and purchase. {perm: library.edit}
- **Also known as (other names in offers and specifications, separated by ;)**: other names the app should recognise as this product. {perm: library.edit}
- **Active**: untick to stop the product being offered in new work. {perm: library.edit}
- **Save** saves; **Cancel** closes without saving. {perm: library.edit}
- **Delete** (edit only): asks "Delete <name>?" and removes the product. A product used in a system cannot be deleted. {perm: library.edit}
- On an edit, emptying **Pack (bag, can, drum)**, **HSN / SAC code** or **Reorder level** and saving clears it. {perm: library.edit}

**The Import the company BOM window** {perm: bom.import}
- **Choose the BOM file (.xlsx)**, then **Preview**: reads the company BOM (a work item whose name ends with its unit, _SQFT, _SQMT, _RFT or _RMT, with its products in [ ] below it) and writes nothing yet. {perm: bom.import}
- **What it writes**: the counts of work items, product rows and products in the file, and the systems, brand options and components the import makes. Per sq ft and per rft figures are turned into per sqm and per rmt (× 10.7639, × 3.2808); the file's figure is kept beside them. {perm: bom.import}
- **Checks**: warnings only, the import still goes ahead: a sq ft and a sqm figure more than 3 % apart, two brands more than 3× apart for the same role, a sheet or mesh above 0.2 per sq ft, a work item with no unit (read per nos), an epoxy or PU item with no resin, a product twice in one recipe, labour rows left out. {perm: bom.import}
- **Not in the product master**: tick a name to create it (its name without the pack, the file's name as an alias, the last purchase price when the file gives one). A name not ticked leaves its lines out; the system is marked to confirm and its note names them. {perm: bom.import}
- **Systems**: each work item with its brand options; **Products** shows each option's products and figures. {perm: bom.import}
- **Default brand option**: the brand a system uses when none is chosen (else the first brand in the file); then **Import**. A system with the same name and unit is updated: its company BOM options are replaced and options made by hand are kept. {perm: bom.import}

**The Prices window (Prices: <product>)** {perm: tender.margin}
- The table: **Effective from**, **Purchase rate / unit**, **Freight / unit**, **Landed** (rate + freight), **Note**. **Current** marks the price in force; **Future** marks a price dated after today. {perm: tender.margin}
- **Add new price**: **Purchase rate (₹)** (required), **Freight / unit (₹)**, **Effective from** (today by default), **Note**; then **Add price**. {perm: library.edit}

**On the page: the price page (/prices/:id)** {perm: tender.margin}
- Opened from the **Purchase rate** link. The header shows the product, its brand and unit, and the **Current price** with its date and who entered it. {perm: tender.margin}
- **Price history**: **Date**, **Price**, **Change** (against the price before), **Source** (Vendor quote, Rate contract, PO, Entered, with the reference and the vendor), **Entered by**. A change above the limit (10 % by default) is shown in red. {perm: tender.margin}
- **New price**, **Source**, **Reference**, then **Add**: records a new price dated today. While you type, the line under it shows the last price used, its date, who entered it, and the change in %, marked when it is more than the limit. {perm: library.edit}
- **Freight per <unit>**: the freight history, per product, or per vendor and godown ("any" when general). The most specific one in force is used. {perm: tender.margin}
- **Freight per unit**, then **Add freight**: records a new freight for the product from today. {perm: library.edit}

**Rules**
- Prices and freight are never edited or deleted. A wrong price is put right by adding a new one.
- The current price is the latest one dated today or earlier.
- Rates in **Systems (rate calculator)**, rate workings and the margin checks use the current price plus freight.

**What happens next**
- A new price is used at once by every rate calculated after it. Prices entered on POs and rate contracts also land in this history.

**Hands off**
- Receives: new products found in old BOQ workings (accepted from **BOQ knowledge**), prices from POs and rate contracts.
- Passes on: products and prices to the estimator (systems and rate workings) and to purchase (POs).

**When it goes wrong**
- "A product with code <code> already exists": pick another code, or edit the existing product.
- "Unknown unit: <unit>": choose a unit from the list.
- "This product is used in a system; remove it there or deactivate it": untick **Active** instead of deleting.
- "Product not found": the product was deleted. Go back to the list.
- "No prices yet.": the product has never been priced. Add the first price.
