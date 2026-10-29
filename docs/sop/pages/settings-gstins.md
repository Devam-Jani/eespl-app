---
page: /settings/gstins
title: GSTIN addresses
routes: /settings/gstins
mark: Add GSTIN
---
The company's GST registrations, one row per GSTIN with its state and address. The row marked
**default** is used on bills and purchase orders unless another is chosen there. Every change is
written to the audit log.

**On the page**
- The table: **GSTIN**, **State**, **Address**, and a **default** badge on the default row. The default comes first.
- **⤓ Export Excel**: downloads the list (GSTIN, state, address, default) as an Excel file.
- **Add GSTIN**: opens the **Add GSTIN** form.
- **Edit** (on a row): opens the same form for that GSTIN.

**The form (Add GSTIN / Edit)**
- **GSTIN**: the 15-character number. It can only be typed when adding; it cannot be changed later.
- **State**: the state of the registration.
- **Address**: the registered address, on several lines if needed.
- **Default address**: tick it to make this the default. The old default loses its tick.
- **Save**: saves and closes the form; the list reloads.
- **Cancel**: closes without saving.
- **Delete**: shown when editing. Asks "Delete <GSTIN>?" and removes the row.

**Rules**
- The first GSTIN added becomes the default by itself.
- Only one GSTIN is the default at a time.
- To change a GSTIN number, add the new one and delete the old one.
- Untick **Default address** on the default row and there is no default until you tick another.

**What happens next**
- New bills and purchase orders take the default GSTIN and its address. Documents made before keep what they had.

**Hands off**
- Receives: the registration certificates from accounts.
- Passes on: the GSTIN and address used by billing and purchase.

**When it goes wrong**
- "GSTIN must look like 27AAPFU0939F1ZV (15 characters)": the number has the wrong shape.
- "GSTIN check digit is wrong; please re-check the number": one character is mistyped. Check it against the certificate.
- "This GSTIN is already in the address directory": it is already listed. Edit that row instead.
