---
page: /clients
title: Clients
routes: /clients
mark: Add client
---
The end clients we quote and work for (builders, developers, PMCs, contractors, government), with
their contacts. Leads, quotations, tenders and sites pick their client from here.

**On the page**
- **Search name, city or GSTIN** (box): type and press Enter.
- **⤓ Export Excel**: downloads the clients as searched.
- **Add client**: opens the **Add client** form. {perm: clients.edit}
- The table: **Name**, **Type**, **City**, **GSTIN**, **Primary contact** (name and phone or email), **Status** (Active or Inactive; inactive rows are greyed).
- **Edit** and **Delete** on a client you may change. A salesperson may change only the clients they created. {perm: clients.edit}
- **View** on the others: opens the form read only, with **Close**.
- **Previous** / **Next**: page through the list.

**The client form** {perm: clients.edit}
- **Name**, **Type** (Builder, Developer, PMC, Contractor, Government, Other), **GSTIN**, **PAN**, **City**, **State**, **Address**, **Notes**, **Active**.
- **Contacts**: **Name**, **Designation**, **Phone**, **Email**, **Primary** (one only), **×** removes a contact; **+ Add contact** adds a row. Rows without a name are not saved.
- **Save**: saves the client and its contacts ("... saved."). **Cancel** closes without saving.
- **Delete** (on the list): asks "Delete client ... and its contacts?".

**Rules**
- A new client belongs to whoever made it.
- A client with tenders cannot be deleted; set it inactive instead (untick **Active**).
- A won quotation without a client makes the client here by itself, from the quotation's firm, city and state.

**Hands off**
- Receives: new clients from sales, the estimator and planning.
- Passes on: the client to leads, quotations, tenders and sites.

**When it goes wrong**
- "GSTIN must look like 27AAPFU0939F1ZV (15 characters)" or "GSTIN check digit is wrong; please re-check the number": check the GSTIN against the client's invoice.
- "PAN must look like AAPFU0939F (10 characters)".
- "You can only change records you created" / "You can only delete records you created": ask whoever made the client, or the director.
- "... has n tenders; set it inactive instead".
