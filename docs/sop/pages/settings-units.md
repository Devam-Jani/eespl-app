---
page: /settings/units
title: Units & conversions
routes: /settings/units
mark: Add
---
The units the app knows, the other ways each is written in imported files, and the conversions
between units. Conversions work both ways and chain (sqm to sqft to rft). A conversion for one
product (for example 1 bag of a product = 25 kg) wins over a general one. Every change is written
to the audit log.

**On the page**
- **⤓ Export Excel**: downloads the conversions (from, to, factor, product) as an Excel file.

**Conversions**
- The table: **From** (always "1 <unit>"), **To**, **Factor** and **Applies to** (a product, or "all products").
- **Edit** (on a row): a box asks "1 <from> = ? <to>". Type the new factor and press OK.
- **×** (on a row): asks "Delete <from> → <to>?" and deletes the conversion.

**Add conversion**
- **1 of**: the unit you convert from.
- **equals**: the factor, a number above 0.
- **of**: the unit you convert to.
- **For product (optional)**: leave "all products", or pick one product the conversion is only for.
- **Add**: saves the conversion and clears the form.

**Try a conversion**
- **Quantity**, **From unit**, **To unit**, **Product**: type a quantity and pick the units (and a product if needed).
- **Convert**: shows the answer under the form, for example "1 sqm = 10.7639 sqft". Nothing is saved.

**Units**
- The table: **Code**, **Name** and **Also written as** (the other spellings found in BOQs and imports).
- **Edit** (on a row): opens **Unit <code>**.
- **Name**: the unit's full name.
- **Also written as (one per line; used by every import)**: one spelling per line. Every import reads these spellings as this unit.
- **Save**: saves the unit. **Cancel**: closes without saving.
- "RO" in a BOQ unit column means rate only: imports store no unit and mark the quantity "QRO".

**Rules**
- Units themselves are fixed; you can only change their name and spellings.
- One spelling may belong to one unit only.
- A conversion between two units (for the same product, or for all products) can exist once.

**What happens next**
- Indents, estimates, stores and imports use the new conversions and spellings at once.

**Hands off**
- Receives: new units or spellings found by estimators and stores in BOQs and supplier bills.
- Passes on: the conversions every quantity in the app is converted with.

**When it goes wrong**
- "Choose two different units": **1 of** and **of** are the same unit.
- "This conversion already exists": edit the existing row instead.
- "Unknown unit: <code>" or "Unknown product id: <n>": reload the page and pick again.
- "Already an alias of another unit: <spellings>": that spelling already means another unit. Remove it there first.
- "No conversion from <unit> to <unit>": (under **Try a conversion**) no chain of conversions links the two units. Add one.
