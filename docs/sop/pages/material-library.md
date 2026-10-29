---
page: /material-library
title: Material library
routes: /material-library
mark: Add a coverage
---
What a square metre takes of each product: its coverage per system, its wastage and its pack. Every
material estimate, site material request and margin check reads its figures from here. A product
with no coverage here makes them say they are not complete. Three tabs: **Products**, **Mix designs**
and **Changes**.

**On the page**
- **Products** (tab, with the count): one card per product that has at least one coverage. The card
  shows the wastage %, the pack (or "not set (quantity only)") and the unit, then a table of its
  coverages: **System** ("any system" when blank), **Value used**, **Min – max**, **Unit**,
  **Per sqm** (the value turned into the product's own unit per sqm), **Source** and **Document**.
- **Find a product** (search): filters the cards by name, code or brand.
- A coverage whose source is "to confirm" has a yellow badge: the figure is not yet backed by a data
  sheet, BOQ spec, method statement or site trial.
- **Document**: the file name of the attached data sheet; press it to download it.
- **Add a coverage**: opens the form for a coverage of any product. Type two letters of the product's
  name or code in **Product**, then choose it in **Pick it**. {perm: coverage.edit}
- **Wastage and pack** (on a product card): opens **Wastage %**, **Pack size** (in the product's unit;
  empty means the quantity is not put in packs) and **Pack** (bag, drum, pail, roll). **Save** keeps
  them. {perm: coverage.edit}
- **Add coverage** (on a product card): the same coverage form, for that product. {perm: coverage.edit}
- Coverage form fields: **System** (**Any system** is used where the product has no coverage for the
  line's own system), **Unit** (kg/sqm, L/sqm, sqm/kg, sqm/L, kg/sqft, sqm/sqm), **Value used**,
  **Source** (data sheet (TDS), BOQ spec, method statement, site trial, to confirm), **Min** (the data
  sheet's lowest), **Max** (and highest) and **Note**. **Save** keeps it. {perm: coverage.edit}
- **Edit** (on a coverage row): the same form, filled in. {perm: coverage.edit}
- **Delete** (on a coverage row): asks "Delete the coverage ...?" and removes it. {perm: coverage.edit}
- **Attach a document** / **Replace the document** with **Choose the document**: attaches a .docx,
  .xlsx or .xls to the coverage (the data sheet or trial record behind the figure). {perm: coverage.edit}
- **Mix designs** (tab): one card per mix (nodular concrete, plaster, brick bat, other) with its dry
  volume factor, parts, cement bag and admixture. Type a **Thickness (mm)** on the card and the table
  shows what a sqm and a sqft take of each component at that thickness, with how it is worked out.
  Nothing is saved by typing the thickness.
- **New mix design** / **Edit** (on a mix card): the mix form. Fields: **Code**, **Name**, **Kind**,
  **Thickness (mm)**, **Dry volume factor**, **Cement bag (kg)**, **Round kg/sqft to** (decimals, as the
  planning sheet; empty means not rounded), **Source**; the **Components** table (**Role**, **Product**,
  **Parts**, **Bulk density (kg/m³)**, and × to remove a row); **Add a component**; **Admixture**,
  **Admixture per cement bag** (L or kg per bag) and **Note**. **Save** keeps it. {perm: coverage.edit}
- **Changes** (tab): every change made to coverages, wastage and pack, documents and mix designs:
  when, what (for example "Coverage changed", "Wastage or pack changed") and each field before → after.

**Rules**
- Only roles with the library edit right see the add, edit, delete and attach buttons. Everyone else
  who can see estimates reads the library only.
- A product has at most one coverage per system and one "any system" coverage. A line of an
  estimate uses the coverage of its own system first, else the product's any-system coverage.
- Min must not be more than max, and the value used must sit between them.
- Wastage is 0 to 100 %. It is added on top of every quantity: area × coverage × (1 + wastage).
- In a mix design, the cement component's role must be "cement" for the admixture to be dosed per bag.
- A mix code is used once only.
- Every change is kept on the **Changes** tab, with the values before and after. Mix designs cannot
  be deleted.

**What happens next**
- A changed coverage or wastage changes, from then on, the quantities of every estimate that uses it
  (issued ones too: their areas and lines are fixed, but the quantities are worked out again from the
  library each time they are opened), the working shown to the site when it asks for material, and
  the margin checks. An Excel or PDF already downloaded keeps the old figures.
- A product that has no coverage here is marked "not complete" in estimates, and the site cannot ask
  for it (the request is refused).

**Hands off**
- Receives: data sheets, BOQ specs and site trial results from planning, estimating and the site.
- Passes on: the coverages and mix designs to planning (material estimates), the site (material
  requests) and the tender team (margin checks).

**When it goes wrong**
- "The product has a coverage in that system already: change it": use **Edit** on the existing row
  instead of adding a second one.
- "The min is more than the max": swap or correct the two figures.
- "The value used is outside its own min and max": put the value inside the range, or widen the range
  if the data sheet allows it.
- "<code> exists" (on a new mix design): the code is taken; pick another code or edit that mix.
- "Upload a photo (.jpg, .png, .webp, .heic) or a PDF or .docx, .xls, .xlsx": the attached file is of
  another type. "The file is larger than 15 MB" and "The file is empty" mean what they say.
- "No coverage in the library yet": no product has a coverage; add the first with **Add a coverage**.
- A product you are looking for is not listed: the list only shows products that already have a
  coverage. Use **Add a coverage** and find it there.
